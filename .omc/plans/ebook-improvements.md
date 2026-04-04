# Ebook Generator — Improvement Plan (Rev 3 — APPROVED)
**Created:** 2026-04-03 | **Revised:** 2026-04-03 (consensus approved after 2 Architect/Critic iterations)  
**Scope:** Quality, Language, Novel Mode, AI Cover, Robustness

---

## Requirements Summary

| # | Requirement | Current State | Gap |
|---|-------------|---------------|-----|
| 1 | Rapi tata bahasa (clean grammar/prose) | No grammar enforcement; QA consistency is stub returning 0.9 | Add grammar refinement pass (opt-in) + AI-based QA consistency check (opt-in) |
| 2 | Cover elegan/premium | Pillow: solid color rectangle + centered text | Integrate image generation AI (DALL-E 3 via OmniRoute); fail-fast Pillow fallback |
| 3 | Content tidak berantakan (organized) | No structure enforcement in prompts | Add structured writing guidelines + section-level prompts |
| 4 | Content terformat baik (well-formatted) | `_apply_styles()` is empty stub, never called from `generate()` | Implement and wire DOCX styles |
| 5 | Konsistensi konten/karakter (consistency) | Only 200-char `previous_summary`; no character/style context | StyleContext dataclass passed to every chapter |
| 6 | Multi-language per ebook | `target_language` is label only; single language only | Language-specific system prompts; multi-language batch export; DB schema migration |
| 7 | AI image generation for cover | No image API call; Pillow placeholder only | `OmnirouteClient.generate_image()` → DALL-E 3 via proxy |
| 8 | Novel mode | Only 4 product modes; no fiction/narrative support | Add `novel` product_mode via `PipelineProfile` abstraction |
| 9 | All world languages incl. Indonesian | No Unicode/RTL support; no language metadata | Language registry, Unicode fonts, RTL DOCX support |
| 10 | Robust, Reliable, Tested | Stub QA, empty styles, 1 integration test, fragile JSON parsing | Fix JSON parsing in Phase 1, ≥80% test coverage, typed interfaces |

---

## Acceptance Criteria

- [ ] AC-1: Grammar check — `QAEngine._check_consistency()` calls AI when `quality_level="thorough"`, returns a float score based on real analysis; score < 0.8 adds issues to QA report; when `quality_level="fast"` returns a neutral score without API call
- [ ] AC-2: Cover image — `CoverGenerator.generate()` calls `ai_client.generate_image()`; on success saves PNG and sets `brief.json["method"] = "ai"`; on `RuntimeError`/`NotFoundError`/404, falls back to enhanced Pillow immediately (no retry) and sets `brief.json["method"] = "pillow"`
- [ ] AC-3: Content structure — `ManuscriptEngine._generate_chapter()` system prompt string contains the literal section labels: "Hook", "Introduction", "Body sections", "Summary", "Transition" (verifiable by asserting on the prompt string); output contains ≥3 paragraphs per chapter (verifiable by counting `\n\n` splits)
- [ ] AC-4: DOCX formatting — `DocxGenerator._apply_styles(doc)` sets body font Calibri 11pt, H1 18pt bold, H2 14pt; `_apply_styles` is called from `generate()` before `doc.save()`; `_add_toc()` uses `self.projects_dir / str(project_id) / "toc.md"` — verified by asserting on returned `Document` object styles
- [ ] AC-5: Consistency — `ManuscriptEngine.generate()` constructs a `StyleContext` instance before the chapter loop; `StyleContext` is passed as a parameter to `_generate_chapter()`; QA consistency score ≥ 0.8 on `quality_level="thorough"` for a well-structured test manuscript
- [ ] AC-6: Multi-language — `ProjectIntake.create_project()` accepts `target_languages: list[str]`; DB stores it as JSON in `project_metadata` table; `ManuscriptEngine` generates per-language editions; editions saved to `projects/{id}/editions/{lang}/manuscript.md`; tests assert both `editions/en/` and `editions/id/` exist for a `["en","id"]` project
- [ ] AC-7: AI image cover — `OmnirouteClient.generate_image(prompt, size)` implemented using `client.images.generate()`; `supports_images` flag caches first probe result; test with real mock asserts PNG bytes returned; test with `NotFoundError` mock asserts Pillow fallback triggered
- [ ] AC-8: Novel mode — `ProductMode.NOVEL` added to enum; `VALID_PRODUCT_MODES` derived from enum; strategy response schema includes `protagonist`, `antagonist`, `central_conflict` keys; novel manuscript system prompt string contains "Show don't tell" and "dialogue" (verifiable by asserting on the prompt string)
- [ ] AC-9: Language registry — `src/i18n/languages.py` contains `SUPPORTED_LANGUAGES` dict with ≥16 entries including `"id"` (Indonesian); `"ar"`, `"he"`, `"fa"`, `"ur"` have `"rtl": True`; DOCX generator applies `w:bidi` element for RTL paragraphs; test generates DOCX with `language="ar"` and asserts `w:bidi` in paragraph XML
- [ ] AC-10: Test coverage — `pytest --cov=src` reports ≥80% line coverage (baseline to be established by running `pytest --cov=src --cov-report=term` before any changes); all new modules have unit tests; integration test exercises full pipeline with real SQLite and file I/O (AI still mocked)

---

## Implementation Steps

### Phase 1 — Foundation (prerequisite for all other phases)

**Step 1.0 — Establish coverage baseline**  
Run `pytest --cov=src --cov-report=term-missing` before any changes; record baseline in `tests/coverage-baseline.txt`.

**Step 1.1 — Fix `generate_structured()` JSON extraction (moved from Phase 6)**  
File: `src/ai_client.py:86-93`  
Issues: no null check on `content`; regex only strips start/end fences (not embedded); `json.JSONDecodeError` caught by broad `except Exception` that triggers unnecessary retries.  
Fix:
```python
def _parse_json_response(self, content: str | None) -> dict:
    if content is None:
        raise ValueError("AI response content is None")
    # strip markdown fences (handles ```json, ```, and embedded fences)
    content = re.sub(r'^```(?:json)?\s*', '', content.strip())
    content = re.sub(r'\s*```$', '', content)
    # find first JSON object or array
    match = re.search(r'(\{.*\}|\[.*\])', content, re.DOTALL)
    if match:
        content = match.group(1)
    return json.loads(content)
```
Replace inline parse logic in `generate_structured()` with `return self._parse_json_response(content)`.  
Catch `json.JSONDecodeError` separately from `Exception` — do NOT retry on parse errors (these are permanent, not transient).

**Step 1.2 — Derive `VALID_PRODUCT_MODES` from enum**  
File: `src/pipeline/intake.py:7`  
Change:
```python
from src.db.models import ProductMode
VALID_PRODUCT_MODES = {m.value for m in ProductMode}
```
This eliminates the duplicate string set and guarantees Phase 4's `NOVEL` addition is automatically picked up.

**Step 1.3 — Introduce `PipelineProfile` abstraction**  
New file: `src/pipeline/pipeline_profile.py`  
```python
from dataclasses import dataclass, field

@dataclass
class PipelineProfile:
    product_mode: str
    strategy_extra_fields: dict = field(default_factory=dict)  # additional AI response schema fields
    chapter_structure: str = "hook→intro→body→summary→transition"  # injected into manuscript prompt
    qa_rules: list[str] = field(default_factory=list)  # extra QA checks for this mode
    is_fiction: bool = False  # enables character sheet tracking in StyleContext
    genre: str | None = None

PROFILES: dict[str, PipelineProfile] = {
    "lead_magnet": PipelineProfile(product_mode="lead_magnet"),
    "paid_ebook": PipelineProfile(product_mode="paid_ebook"),
    "bonus_content": PipelineProfile(product_mode="bonus_content"),
    "authority": PipelineProfile(product_mode="authority"),
}
```
Orchestrator reads `PROFILES[project["product_mode"]]` and passes the profile to each stage.  
Each stage accepts `profile: PipelineProfile | None = None` and falls back to the default if not provided.

**Orchestrator wiring specifics** (file: `src/pipeline/orchestrator.py`):
- Around line 94-99: after building `project_brief`, add `profile = PROFILES.get(project["product_mode"], PipelineProfile(product_mode=project["product_mode"]))`
- Pass `profile=profile` to each stage call: `StrategyPlanner.generate()` (~line 105), `OutlineGenerator.generate()` (~line 120), `ManuscriptEngine.generate()` (~line 140), `CoverGenerator.generate()` (~line 160), `QAEngine.run()` (~line 175)

**Step 1.4 — Fix `DocxGenerator._add_toc()` path bug**  
File: `src/export/docx_generator.py:67-78`  
- Add `project_id: int` parameter to `_add_toc(doc, project_id)` and `generate()`
- Change `project_dir = self.projects_dir` → `project_dir = self.projects_dir / str(project_id)`
- Wire `_apply_styles(doc)` call in `generate()` before `doc.save()` (currently dead code — never called)

**Step 1.5 — Language-specific system prompts**  
New file: `src/i18n/__init__.py` (empty)  
New file: `src/i18n/languages.py` — see Phase 5, Step 5.1 (create now, use in Phase 5)  
Helper function: `language_instruction(lang_code: str) -> str`  
- `"en"` → `"Write entirely in English. Use natural English grammar and idioms."`
- `"id"` → `"Tulis seluruhnya dalam Bahasa Indonesia. Gunakan tata bahasa Indonesia yang baku dan natural."`
- Unknown code → `"Write entirely in {lang_code}."`  
Inject into system prompts in `strategy_planner.py:42`, `outline_generator.py:20`, `manuscript_engine.py:103`.

**Step 1.6 — Integration test TOC assertion**  
File: `tests/integration/test_full_pipeline.py`  
Add assertion: after `DocxGenerator.generate()`, open generated DOCX and assert TOC heading `"Table of Contents"` exists in document body (verifies the path fix).

---

### Phase 2 — Content Quality

**Step 2.1 — `StyleContext` dataclass**  
New file: `src/pipeline/style_context.py`:
```python
from dataclasses import dataclass, field

@dataclass
class StyleContext:
    tone: str
    vocabulary_level: str = "general"  # "simple", "general", "technical"
    recurring_terms: list[str] = field(default_factory=list)
    characters: list[dict] = field(default_factory=list)  # populated for novel mode
    previous_chapter_ending: str = ""  # last 400 chars of previous chapter

    def to_prompt_block(self) -> str:
        lines = [
            f"Tone: {self.tone}",
            f"Vocabulary level: {self.vocabulary_level}",
        ]
        if self.recurring_terms:
            lines.append(f"Key terms to use consistently: {', '.join(self.recurring_terms)}")
        if self.characters:
            summaries = [f"{c['name']} ({c['role']}): {c['description'][:50]}" for c in self.characters]
            lines.append(f"Characters: {'; '.join(summaries)}")
        if self.previous_chapter_ending:
            lines.append(f"Previous chapter ended: \"{self.previous_chapter_ending}\"")
        return "\n".join(lines)
```
`StyleContext` is the source of truth for cross-chapter state; strategy dict provides initial values but StyleContext evolves through chapters.

**Step 2.2 — Wire StyleContext into ManuscriptEngine**  
File: `src/pipeline/manuscript_engine.py`  
- Build `StyleContext` from `strategy` dict before chapter loop
- Replace `previous_summary = chapter_content[:200]` with `style_ctx.previous_chapter_ending = chapter_content[-400:]`
- Pass `style_ctx` to `_generate_chapter()`; inject `style_ctx.to_prompt_block()` as "Style Guide" block in system prompt
- For novel mode (`profile.is_fiction`): populate `style_ctx.characters` from strategy character sheets before loop

**Step 2.3 — Structured chapter prompt**  
File: `src/pipeline/manuscript_engine.py:103-114`  
Replace generic "Write engaging content" with:
```
Structure:
- Hook (1 paragraph): open with a question, fact, or anecdote
- Introduction (1 paragraph): overview of this chapter
- Body sections: one section per subchapter, each with a subheading and 2-4 paragraphs
- Summary (1 paragraph): key takeaways from this chapter
- Transition (1 sentence): bridge to the next chapter topic
```

**Step 2.4 — Real QA consistency check (opt-in)**  
File: `src/pipeline/qa_engine.py`  
- `QAEngine.__init__` accepts `ai_client: OmnirouteClient | None = None` and `quality_level: str = "fast"`
- `_check_consistency()` when `quality_level="thorough"`: sends first 300 + last 300 chars of manuscript to AI; asks for 0.0–1.0 consistency score; timeout 60s per call; on AI failure returns 0.9 (graceful degradation, logs warning)
- When `quality_level="fast"`: returns 0.9 (existing behavior)

**Step 2.5 — Grammar RefinementEngine (opt-in)**  
New file: `src/pipeline/refinement_engine.py`  
- `RefinementEngine(ai_client, language, tone, quality_level="fast")`
- `refine(content: str) -> str`: when `quality_level="thorough"`, sends chapter to AI with editorial prompt; timeout 60s; on failure returns original content (graceful degradation)
- When `quality_level="fast"`: returns content unchanged
- `ManuscriptEngine` accepts `quality_level: str = "fast"` and passes to `RefinementEngine`

---

### Phase 3 — AI Cover Generation

**Step 3.1 — Add `generate_image()` to `OmnirouteClient`**  
File: `src/ai_client.py`  
```python
def probe_image_support(self) -> bool:
    """Check once if proxy supports images endpoint; caches result.
    
    Note: detection happens lazily on the first real generate_image() call
    (catches NotFoundError/404) rather than sending a separate probe request,
    to avoid burning quota on a test generation.
    """
    return self._supports_images is not False  # None = unknown (assume True), False = confirmed unsupported

def generate_image(self, prompt: str, size: str = "1024x1024", model: str = "dall-e-3") -> bytes:
    if self._supports_images is False:
        raise RuntimeError("Image generation not supported by this OmniRoute proxy")
    try:
        response = self.client.images.generate(
            model=model, prompt=prompt, size=size,
            response_format="b64_json", n=1
        )
        self._supports_images = True
        import base64
        return base64.b64decode(response.data[0].b64_json)
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower() or "NotFound" in type(e).__name__:
            self._supports_images = False  # cache: proxy does not support images
        raise RuntimeError(f"Image generation unavailable: {e}") from e
```
Initialize `self._supports_images: bool | None = None` in `__init__`.

**Step 3.2 — Update `CoverGenerator` to use AI image (fail-fast fallback)**  
File: `src/cover/cover_generator.py`  
- Try `ai_client.generate_image(prompt)` — if `RuntimeError` (proxy doesn't support) or any exception: immediately fall back to Pillow (no retry); set `brief.json["method"] = "pillow"`; log warning
- On success: save raw bytes; set `brief.json["method"] = "ai"`
- Enhanced Pillow fallback: gradient background, centered title, subtitle line, thin border

---

### Phase 4 — Novel Mode

**Step 4.1 — Add `ProductMode.NOVEL` to enum**  
File: `src/db/models.py:8-12`  
Add `NOVEL = "novel"` — `VALID_PRODUCT_MODES` in `intake.py` auto-updates via Step 1.2.

**Step 4.2 — `NOVEL` `PipelineProfile`**  
File: `src/pipeline/pipeline_profile.py` (created in Step 1.3)  
```python
PROFILES["novel"] = PipelineProfile(
    product_mode="novel",
    strategy_extra_fields={
        "protagonist": str, "antagonist": str,
        "setting": str, "central_conflict": str,
        "narrative_arc": str, "genre": str,
    },
    chapter_structure="scene→conflict→resolution→cliffhanger",
    qa_rules=["character_name_consistency"],
    is_fiction=True,
)
```

**Step 4.3 — Novel-specific stage prompts (via PipelineProfile)**  
Files: `strategy_planner.py`, `outline_generator.py`, `manuscript_engine.py`  
Each stage checks `profile.is_fiction` and adjusts prompt accordingly:  
- Strategy: includes `strategy_extra_fields` in `response_schema`
- Outline: requests character sheets, act structure, scene summaries
- Manuscript system prompt: adds "Show don't tell. Use dialogue and sensory details."

**Step 4.4 — Novel UI page**  
File: `app/pages/2_✍️_Create_Ebook.py`  
Genre selector (Fantasy, Romance, Thriller, Sci-Fi, Mystery, Literary Fiction) shown when Novel mode selected; passed into strategy as `genre` field.

---

### Phase 5 — Multi-Language & i18n

**Step 5.1 — Language registry**  
File: `src/i18n/languages.py` (created in Step 1.5, expanded here)  
```python
SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "rtl": False, "font_hint": "Calibri"},
    "id": {"name": "Indonesian (Bahasa Indonesia)", "rtl": False, "font_hint": "Calibri"},
    "ar": {"name": "Arabic", "rtl": True, "font_hint": "Arial"},
    "zh": {"name": "Chinese (Simplified)", "rtl": False, "font_hint": "SimSun"},
    "ja": {"name": "Japanese", "rtl": False, "font_hint": "MS Mincho"},
    "ko": {"name": "Korean", "rtl": False, "font_hint": "Malgun Gothic"},
    "hi": {"name": "Hindi", "rtl": False, "font_hint": "Mangal"},
    "he": {"name": "Hebrew", "rtl": True, "font_hint": "Arial"},
    "fa": {"name": "Persian (Farsi)", "rtl": True, "font_hint": "Arial"},
    "ur": {"name": "Urdu", "rtl": True, "font_hint": "Arial"},
    "es": {"name": "Spanish", "rtl": False, "font_hint": "Calibri"},
    "fr": {"name": "French", "rtl": False, "font_hint": "Calibri"},
    "de": {"name": "German", "rtl": False, "font_hint": "Calibri"},
    "pt": {"name": "Portuguese", "rtl": False, "font_hint": "Calibri"},
    "ru": {"name": "Russian", "rtl": False, "font_hint": "Times New Roman"},
    "tr": {"name": "Turkish", "rtl": False, "font_hint": "Calibri"},
}
```

**Step 5.2 — DB schema migration for `target_languages`**  
File: `src/db/schema.py`  
Add `project_metadata` row at project creation for `target_languages` (JSON array string).  
Do NOT modify the `projects` table `target_language TEXT` column — keep for backward compatibility with existing projects.  
`ProjectRepository.get_target_languages(project_id)` reads from `project_metadata` where `key="target_languages"`; returns `["en"]` if not present (backward compatible).  
Existing projects created before this change are treated as single-language (`target_language` column value).

**Step 5.3 — Multi-language generation**  
File: `src/pipeline/manuscript_engine.py`  
`ManuscriptEngine.generate()` accepts `target_languages: list[str] = None`.  
When multiple languages: for each language after the first, call `_generate_edition(lang, outline, strategy)` which re-runs chapter generation with language-injected prompts; saves to `projects/{id}/editions/{lang}/`.  
**On edition failure**: log error, mark edition as failed in `project_metadata`, continue with remaining languages (graceful degradation per Principle 3).

**Step 5.4 — Path parameterization for edition isolation**  
The following methods currently hardcode `projects/{id}/` and must accept an optional `edition_dir: Path | None = None` override:

| File | Method | Current path construction |
|------|---------|--------------------------|
| `src/pipeline/manuscript_engine.py:25-27` | `generate()` | `project_dir = self.projects_dir / str(project_id)` |
| `src/pipeline/manuscript_engine.py:52-53` | `generate()` | `chapters_dir = project_dir / "chapters"` |
| `src/pipeline/qa_engine.py:83-85` | `save_report()` | `project_dir / "qa_report.json"` |
| `src/export/docx_generator.py:23` | `generate()` | `project_dir / "exports"` |
| `src/export/file_manager.py:13-17` | `ensure_directories()` | `self.projects_dir / str(project_id)` |

Fix: Add `get_edition_dir(project_id, lang=None)` to `FileManager`:
```python
def get_edition_dir(self, project_id: int, lang: str | None = None, primary_lang: str = "en") -> Path:
    """Returns edition output dir. Primary language uses the base path for backward compat.
    
    If no English in the project's target_languages, caller passes primary_lang=target_languages[0].
    This avoids hardcoding "en" as always-primary for non-English projects.
    """
    base = self.get_project_dir(project_id)
    if lang and lang != primary_lang:
        return base / "editions" / lang
    return base
```
All multi-language runs for non-primary languages use `get_edition_dir(project_id, lang)` as their output root.

**Step 5.5 — RTL DOCX support**  
File: `src/export/docx_generator.py`  
```python
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def _set_rtl(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement('w:bidi')
    bidi.set(qn('w:val'), '1')
    pPr.append(bidi)
```
`DocxGenerator.generate()` accepts `language: str = "en"`; applies `_set_rtl()` to all body paragraphs when `SUPPORTED_LANGUAGES.get(language, {}).get("rtl", False)`.

---

### Phase 6 — Robustness & Test Coverage

**Step 6.1 — Harden `OmnirouteClient` retry logic**  
File: `src/ai_client.py`  
Distinguish transient (429, 503, connection error) from permanent (400, 401, 404, `json.JSONDecodeError`) errors:
- Transient: retry with exponential backoff (already implemented)
- Permanent: raise immediately without retry; wrap in typed `PermanentAPIError`

**Step 6.2 — Input validation**  
File: `src/pipeline/intake.py`  
- `target_languages` validation: no duplicates; ≤10 languages; warn (log) but accept unknown codes
- Idea text: strip control characters, normalize Unicode whitespace

**Step 6.3 — Content safety integration**  
Files: `src/pipeline/qa_engine.py` (primary wiring point) + `src/pipeline/content_safety.py` (exists, unused)  
Wire `ContentSafety.check_content()` into `QAEngine.run()`: instantiate `ContentSafety()`, pass full manuscript text, append its `issues` to the QA issues list; never block generation (graceful degradation). The File Change Index entry for `content_safety.py` is "wire into orchestrator" but the actual call site is `qa_engine.py` — `content_safety.py` itself does not change.

**Step 6.4 — Test files to add/expand**

| File | Purpose |
|------|---------|
| `tests/test_pipeline/test_refinement_engine.py` | Unit tests for grammar refinement (fast=passthrough, thorough=mocked AI call) |
| `tests/test_pipeline/test_style_context.py` | Unit tests for StyleContext.to_prompt_block(), character injection |
| `tests/test_pipeline/test_pipeline_profile.py` | Unit tests for profile lookup, novel profile fields |
| `tests/test_i18n/test_languages.py` | RTL detection, language_instruction() output, Indonesian entry |
| `tests/test_ai_client.py` | Expand: generate_image(), _parse_json_response(), PermanentAPIError vs retry |
| `tests/test_export/test_docx_generator.py` | Expand: styles applied, RTL XML, TOC path fix, _apply_styles wired |
| `tests/integration/test_full_pipeline.py` | Expand: multi-language editions, novel mode, cover fallback, TOC content |

**Step 6.5 — Coverage gate**  
File: `pyproject.toml` — add `COV=1` env-var opt-in pattern via `conftest.py` so `pytest` default run stays fast; `pytest --cov=src` always works explicitly.

---

## Minimum Viable Improvement Set

If only 2 phases can be shipped, prioritize:
1. **Phase 1** (unblocks everything, fixes existing bugs)
2. **Phase 2** (highest user-visible quality impact: structured prompts + StyleContext)

Phases 3-6 are independent improvements that can ship incrementally.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OmniRoute proxy doesn't support `images.generate` | High | Medium | `probe_image_support()` caches result; fail-fast to Pillow (no retry waste) |
| Multi-language generation triples API cost/time | High | Medium | Sequential per-language; `max_languages=10` guard; edition failure is non-fatal |
| AI-generated novel content is incoherent across chapters | Medium | High | StyleContext characters + RefinementEngine (thorough mode) + QA |
| RTL DOCX broken on some Word versions | Low | Medium | Use `w:bidi` OOXML (Word 2007+); test with Arabic sample |
| Novel mode context window overflow from character sheets | Medium | Medium | Character descriptions capped at 50 words each; full sheets in `characters.json` |
| JSON parse failure silently retried | High (before fix) | Medium | Step 1.1 separates `json.JSONDecodeError` from transient errors — no retry on parse failure |
| Phase 5 breaks existing projects | Medium | High | `target_language` column unchanged; `get_edition_dir()` returns base path for primary lang; backward compatible |

---

## Verification Steps

1. **Phase 1.1 (JSON fix)**: Inject `None` as AI response content; assert `ValueError` raised, not `AttributeError`; inject JSON wrapped in prose; assert parsed correctly
2. **Phase 1.2 (enum sync)**: Add a test: `assert ProductMode.NOVEL.value in ProjectIntake.VALID_PRODUCT_MODES` — must pass after adding NOVEL to enum
3. **Phase 1.4 (TOC fix)**: Call `DocxGenerator.generate(project_id=1)` with temp dir; assert `Document` body contains "Table of Contents" heading
4. **Phase 2.3 (prompt structure)**: Assert `"Hook"` and `"Transition"` appear in the system prompt string returned by `_build_chapter_prompt()`
5. **Phase 3.2 (cover fallback)**: Mock `generate_image` to raise `RuntimeError`; call `CoverGenerator.generate()`; assert `cover/brief.json["method"] == "pillow"`; assert `cover/cover.png` exists
6. **Phase 4.2 (novel profile)**: Assert `PROFILES["novel"].is_fiction == True` and `"protagonist"` in `PROFILES["novel"].strategy_extra_fields`
7. **Phase 5.4 (edition isolation)**: Create project with `target_languages=["en","id"]`; assert `projects/1/editions/id/manuscript.md` exists; assert `projects/1/manuscript.md` also exists (primary)
8. **Phase 5.5 (RTL)**: Generate DOCX with `language="ar"`; parse XML; assert `w:bidi` element in first paragraph's `pPr`
9. **Coverage**: Run `pytest --cov=src --cov-report=term-missing`; assert line coverage ≥ 80%
10. **Latency opt-in**: Run `ManuscriptEngine` with `quality_level="fast"`; assert no calls to `ai_client.generate_text` beyond chapter generation itself (mock call count check)

---

## File Change Index

| File | Change | Phase |
|------|--------|-------|
| `src/ai_client.py` | `_parse_json_response()`, `generate_image()`, `probe_image_support()`, retry hardening | 1.1, 3.1, 6.1 |
| `src/pipeline/intake.py` | Derive `VALID_PRODUCT_MODES` from enum; `target_languages` param; input sanitization | 1.2, 5.2, 6.2 |
| `src/pipeline/pipeline_profile.py` | **New**: `PipelineProfile` dataclass + `PROFILES` dict | 1.3 |
| `src/i18n/__init__.py` | **New**: empty package marker | 1.5 |
| `src/i18n/languages.py` | **New**: `SUPPORTED_LANGUAGES` registry + `language_instruction()` | 1.5, 5.1 |
| `src/export/docx_generator.py` | Fix TOC path, wire `_apply_styles()`, RTL support, `project_id` param | 1.4, 5.5 |
| `src/pipeline/style_context.py` | **New**: `StyleContext` dataclass | 2.1 |
| `src/pipeline/manuscript_engine.py` | Wire StyleContext, structured prompt, novel branch, multi-lang, quality_level | 2.2, 2.3, 4.3, 5.3 |
| `src/pipeline/refinement_engine.py` | **New**: grammar refinement pass (opt-in) | 2.5 |
| `src/pipeline/qa_engine.py` | Real consistency check (opt-in), content_safety wiring | 2.4, 6.3 |
| `src/pipeline/strategy_planner.py` | Language instructions, novel extra fields via profile | 1.5, 4.3 |
| `src/pipeline/outline_generator.py` | Language instructions, novel arc/character sheet via profile | 1.5, 4.3 |
| `src/pipeline/content_safety.py` | Wire into orchestrator (exists, currently unused) | 6.3 |
| `src/cover/cover_generator.py` | AI image + fail-fast Pillow fallback + enhanced Pillow | 3.2 |
| `src/db/models.py` | Add `ProductMode.NOVEL` | 4.1 |
| `src/db/schema.py` | No DDL change; backward-compat via `project_metadata` | 5.2 |
| `src/db/repository.py` | `get_target_languages()` method | 5.2 |
| `src/export/file_manager.py` | `get_edition_dir(project_id, lang)` method | 5.4 |
| `app/pages/2_✍️_Create_Ebook.py` | Novel genre selector, multi-language select | 4.4 |
| `tests/` | 7 new/expanded test files | 6.4 |
| `tests/coverage-baseline.txt` | **New**: coverage baseline record | 6.4 |
| `pyproject.toml` | Coverage opt-in note | 6.5 |

---

## ADR — Architecture Decision Record

**Decision**: Keep the sequential pipeline; add `PipelineProfile`, `StyleContext`, `RefinementEngine`, and `src/i18n/` as supporting modules; introduce fail-fast image fallback.

**Drivers**:
1. Backward compatibility — existing projects and tests must keep working
2. Testability — each new module must be independently unit-testable with `mock_ai_client`
3. OmniRoute proxy constraints — image generation and model selection depend on proxy support; design must tolerate absence

**Alternatives Considered**:
- **Option B: Async DAG orchestrator** — natural extension points for product modes and multi-language; would eliminate the product-mode branching problem in pipeline stages. Rejected because the orchestrator is compiled (`.pyc` only in tree), restructuring it is out-of-scope, and the `PipelineProfile` abstraction captures 80% of the benefit at 10% of the cost.
- **Option C: External services (DeepL, Midjourney)** — best translation quality; real AI art. Rejected because it adds external API keys, costs, and dependencies outside the self-hosted OmniRoute ecosystem; cultural context in prose is better preserved by LLM translation than neural MT.

**Why Chosen**: Additive modules are the minimum change to deliver all 10 improvements. The `PipelineProfile` abstraction prevents option-A's main failure mode (conditional sprawl) without requiring an orchestrator rewrite.

**Consequences**:
- `ManuscriptEngine` is the heaviest file (StyleContext + novel mode + multi-lang + quality_level). Extract `_build_system_prompt()` helper to keep `_generate_chapter()` < 30 lines.
- Multi-language generation is sequential — acceptable since it runs as a background job
- "Additive over rewrite" principle has one acknowledged exception: Phase 5 restructures the output directory (edition isolation). This is a managed exception: `get_edition_dir()` provides a stable API; the base path for the primary language is unchanged.

**Follow-ups**:
- Evaluate parallel chapter generation (asyncio) once StyleContext is stable in production
- Consider EPUB export (`ebooklib`) alongside DOCX/PDF
- Revisit DAG orchestrator if >3 product modes require deeply different stage configurations
- Per-language TOC files: currently `OutlineGenerator._save_outline()` writes one `toc.md` in the primary language; multi-language editions reuse it. Add per-language `toc.md` generation in a follow-up once the edition directory structure is stable

---

## Revision Changelog (iteration 2 → 3, post-approval)
- **Step 3.1**: `probe_image_support()` replaced with lazy detection — capability flag set on first real `generate_image()` call (404/NotFound → `_supports_images=False`); no separate probe request burns quota
- **Step 5.4**: `get_edition_dir()` accepts `primary_lang` parameter instead of hardcoding `"en"` — handles non-English projects correctly
- **Step 1.3**: Added orchestrator wiring specifics (line numbers, which calls get `profile=profile`)
- **Step 6.3**: Clarified content_safety call site is `qa_engine.py` not orchestrator; `content_safety.py` itself unchanged
- **ADR Follow-ups**: Added per-language TOC as known deferred item

## Revision Changelog (iteration 1 → 2)
- **Added Step 1.0**: coverage baseline before any changes
- **Added Step 1.1**: moved JSON hardening from Phase 6 to Phase 1 (Architect R3, Critic critical finding)
- **Added Step 1.2**: derive `VALID_PRODUCT_MODES` from Pydantic enum (Architect R2, Critic critical finding)
- **Added Step 1.3**: `PipelineProfile` dataclass with field list (Architect R1, Critic major finding)
- **Added Step 1.6**: integration test TOC assertion (Architect 4.2)
- **AC-3 clarified**: "hook-body-summary structure" is a prompt-string requirement (verifiable by asserting on prompt string), not an output requirement
- **AC-8 clarified**: "Show don't tell" and "dialogue" are prompt-string requirements (verifiable), not subjective quality metrics
- **Phase 2.4/2.5**: RefinementEngine and AI QA now explicitly opt-in via `quality_level` parameter; timeout 60s; graceful degradation on failure
- **Phase 3.1**: added `probe_image_support()` + `_supports_images` cache; fail-fast fallback (no retry on image API failure)
- **Phase 5.2**: DB migration strategy specified — `project_metadata` table, backward compatible with `target_language` column
- **Phase 5.3**: edition failure is non-fatal; pipeline continues with remaining languages
- **Phase 5.4**: explicit table of all 5 methods requiring path parameterization; `get_edition_dir()` as centralized resolver
- **Step 6.3**: wired `content_safety.py` (existed but unused) into manuscript QA pass
- **Added**: Minimum Viable Improvement Set section
- **ADR**: updated to acknowledge Phase 5 directory restructuring as a managed exception to "Additive over rewrite"
