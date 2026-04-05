# 1AI Ebook Generator — Improvement Plan

**Date:** 2026-04-05  
**Status:** Rev 2 (post Architect + Critic review)  
**Priority areas:** Human-quality writing, Robustness, Error handling, Test coverage, Integrations, EPUB3 compliance

---

## Requirements Summary

The system is production-ready for core workflows (pipeline, UI, DOCX/PDF/EPUB export) but needs improvements across six pillars:

1. **Human-quality prose** — AI-generated chapters read flat; lack narrative voice, transitions, hooks, case studies, and structural variety
2. **Robustness** — ~20 silent exception handlers swallow errors across 15+ files; no logging; resume-on-failure is fragile and incompatible with voice consistency
3. **Error handling** — Errors are invisible to operators and users; no structured logging
4. **Test coverage** — Integrations, MCP server, API server have zero tests
5. **Integrations** — `IntegrationManager` is a stub; webhook invocation not implemented
6. **Export quality** — EPUB3 semantic markup missing; EPUB/PDF failures invisible in manifest

> **Architect note:** MOBI export is out of scope. Amazon KDP accepts EPUB3 directly since 2021; `kindlegen` was deprecated in 2020. Replacing with EPUB3 compliance.

---

## Acceptance Criteria

All criteria are testable with concrete pass/fail conditions.

- [ ] **AC-1** `pytest --cov=src` reports ≥90% line coverage on `src/integrations/`, `src/mcp/`, and `src/api/`
- [ ] **AC-2** Zero silent exception handlers remain in `src/` — verified by running: `python -c "import ast, sys, pathlib; bad=[(f,n.lineno) for f in pathlib.Path('src').rglob('*.py') for t in [ast.parse(f.read_text())] for n in ast.walk(t) if isinstance(n,ast.ExceptHandler) and (not n.body or (len(n.body)==1 and isinstance(n.body[0],(ast.Pass,ast.Return)) and not any('log' in ast.unparse(s) for s in n.body)))]; [print(f) for f in bad]; sys.exit(len(bad))"` — exits 0 when all handlers log. Graceful fallback paths (cover renderer, config load) use `logger.info`; unexpected failures use `logger.warning`.
- [ ] **AC-3** `IntegrationManager.invoke_webhook()` POSTs with HMAC-SHA256 signature, circuit breaker (trips after 2 consecutive failures, 5-min cooldown), background thread (non-blocking), and audit log in `integration_logs` table
- [ ] **AC-4** EPUB3 output passes `epub:type` attribute validation on chapter, introduction, and conclusion elements; EPUB/PDF export results include `status: success|failed|skipped` in `manifest.json`
- [ ] **AC-5** A generated chapter in `quality_level="thorough"` scores: sentence-length stddev ≥ 5, banned-phrase count ≤ 2, hedge-word density ≤ 8% — all measurable by `QAEngine._check_prose_quality()`
- [ ] **AC-6** `QAEngine.run()` returns `scores["prose_quality"]` ≥ 0.8 for a well-formed chapter; `RefinementEngine.refine()` is invoked per chapter when `quality_level="thorough"`
- [ ] **AC-7** Pipeline resumes correctly after any single-stage failure: completed stage flags in `project_metadata` (via `INSERT OR REPLACE`) prevent regeneration; `StyleContext` loaded from `projects/{id}/style_context.json` on resume
- [ ] **AC-8** Every chapter generation call in `_generate_chapter()` receives the `StyleGuide` constraint block (voice anchor, banned phrases, gold-standard paragraph) in `base_system`
- [ ] **AC-9** `ErrorClassifier.classify(exception)` returns a user-friendly string for `PermanentAPIError`, `TimeoutError`, `json.JSONDecodeError`, and generic exceptions; classified messages stored in `jobs.error_message` (verified by `tests/test_pipeline/test_error_classifier.py`)

---

## Implementation Steps

> **Sprint ordering (Architect-mandated):** Pillar 2 (robustness/logging) ships in Sprint 1 alone. Pillar 1 (writing quality) begins Sprint 2 — so StyleGuide debugging has structured logging available from day one.

---

### PILLAR 2 — Robustness *(Sprint 1 — Foundation)*

#### 2.1 Structured Logging (`src/logger.py`) — NEW FILE

- Add `structlog` to `requirements.txt`
- `setup_logging(level="INFO")` — JSON output in production (`LOG_FORMAT=json`), colored console otherwise
- Call at entrypoints: `app/main.py` and `src/api/server.py`
- **Remediate ALL silent exception handlers** — run `grep -rn "except" src/` to enumerate all ~35 handlers; ~20 are silent. Every `except: pass` becomes `except Exception as e: logger.warning("<context>", error=str(e), module=__name__)`.
  - Confirmed locations (non-exhaustive — grep is authoritative):
    - `src/config.py` — `load()` silent fail
    - `src/pipeline/orchestrator.py` — marketing kit silent pass
    - `src/pipeline/refinement_engine.py` — returns original content silently
    - `src/pipeline/qa_engine.py` — consistency check silent None
    - `src/pipeline/model_tracker.py` — resets stats silently
    - `src/pipeline/token_calibrator.py` — silent load fail
    - `src/cover/cover_generator.py` — multiple locations in `generate()` and `_generate_html_cover()`
    - `src/export/docx_generator.py` — cover picture, chapter parsing
    - `src/export/epub_generator.py` — cover add
    - `src/export/export_orchestrator.py` — EPUB generation, PDF conversion
    - `src/integrations/manager.py` — load fail
    - `src/utils.py` — utility function
    - `src/research/ebook_reference.py` — two API call failures
    - `src/api/server.py` — auth, admin generation

**New file:** `src/logger.py`  
**Modified:** All files listed above + `app/main.py`, `src/api/server.py`

#### 2.2 Pipeline Resume Hardening

- `PipelineOrchestrator._check_progress()` — add DB-side stage flags alongside filesystem check
- Use `project_metadata` table with `key = "stage:{name}"`, `value = "completed"`
- **Schema change required:** Add `UNIQUE(project_id, key)` constraint to `project_metadata` to prevent duplicate rows on repeated resume cycles. Use `INSERT OR REPLACE` for all stage flag writes.
- **Persist `StyleContext` to disk** — after each chapter in `ManuscriptEngine.generate()`, call `style_ctx.save(project_dir / "style_context.json")`. In `_check_progress()` resume path, load it via `StyleContext.load(path)`. Without this, resumed chapters lose all accumulated voice context (recurring metaphors, previous chapter ending, established terminology) — directly contradicting AC-7 + AC-8.
  - Add `save(path)` / `load(path)` / `load_or_default(path)` classmethods to `StyleContext` using `dataclasses.asdict()` + `json.dump()`

**Modified:** `src/pipeline/orchestrator.py` (`_check_progress`, `run_full_pipeline`)  
**Modified:** `src/pipeline/manuscript_engine.py` (`generate` — save `StyleContext` after each chapter)  
**Modified:** `src/pipeline/style_context.py` — add `save()`, `load()`, `load_or_default()` methods  
**Modified:** `src/db/schema.py` — add `UNIQUE(project_id, key)` to `project_metadata`

#### 2.3 Retry Hardening for AI Calls

- Add jitter to backoff in `OmnirouteClient.generate_text()` and `generate_structured()`: `wait = (2**attempt) + random.uniform(0, 1)` (currently `+ 0.1` fixed — `ai_client.py` retry loop)
- Add `ai_request_timeout` and `ai_max_retries` to `PipelineConfig` (currently hardcoded as `timeout=300`, `max_retries=3`)
- Distinguish transient (5xx, timeout, connection error) vs permanent (4xx) more precisely — current code catches `"400"|"401"|"403"|"404"` string matching; add `httpx.TimeoutException` and `httpx.ConnectError` to transient list

**Modified:** `src/ai_client.py` (both retry loops)  
**Modified:** `src/config.py` — add `ai_request_timeout: int = 300`, `ai_max_retries: int = 3`

#### 2.4 Export Manifest Status Fields

- `ExportOrchestrator._create_manifest()` currently only records files that exist — a failed EPUB is indistinguishable from "not attempted"
- Change each format entry to include `status: "success" | "failed" | "skipped"` and optional `error` field
- In `_generate_epub()` and `_generate_pdf()` catch blocks, write the failure status to a per-format result dict that is passed to `_create_manifest()`

**Modified:** `src/export/export_orchestrator.py` (`_generate_epub`, `_generate_pdf`, `_create_manifest`)

---

### PILLAR 1 — Human-Quality Writing *(Sprint 2+)*

#### 1.1 Style Guide System (`src/pipeline/style_guide.py`) — NEW FILE

Research: Professional authors create a **Style Reference Sheet** before writing — a voice anchor, banned phrases, sentence-length range, POV, and a gold-standard paragraph. Pass it as a system-prompt prefix at every chapter call.

- `StyleGuide` dataclass fields:
  - `voice_anchor: str` — target reader description (age, job, frustration level)
  - `pov: str` — `"second-person"` | `"first-person"` | `"third-person"` (default: second)
  - `banned_phrases: list[str]` — `["delve", "it's worth noting", "in conclusion", "as we explore", "in today's fast-paced world", "it is important to note", "furthermore", "moreover", "additionally"]`
  - `sentence_length_range: tuple[int, int]` — e.g., `(12, 18)` average words
  - `tone_adjectives: list[str]` — e.g., `["direct", "warm", "skeptical", "never preachy"]`
  - `gold_standard_paragraph: str` — 3-5 sentence exemplar prose (AI-generated by `StrategyPlanner`)
- `StyleGuide.to_system_prompt_block() -> str` — returns formatted injection string (~150 tokens)
- **Model-tier gating:** Add `model_capability_tier: str = "medium"` to `PipelineConfig` (values: `"small"` | `"medium"` | `"large"`). For `"small"` (7B models like `qwen2.5:7b`), inject only banned phrases and tone adjectives. For `"large"`, inject full style guide including gold-standard paragraph. This prevents prompt complexity from degrading coherence on small models — one config knob, not 4 boolean flags.
- `StrategyPlanner` generates `StyleGuide` from the strategy and saves `style_guide.json` to project dir

**New file:** `src/pipeline/style_guide.py`  
**Modified:** `src/pipeline/manuscript_engine.py` — `_generate_chapter()` base_system construction  
**Modified:** `src/pipeline/strategy_planner.py` — generate + save `style_guide.json`  
**Modified:** `src/config.py` — add `model_capability_tier: str = "medium"`

#### 1.2 Chapter Structure Enrichment

Research: O'Reilly/Wiley house style follows: **opener → body → callouts → case study → summary → action steps → bridge**. This is what separates professional ebooks from AI-generated ones.

**Implementation approach — single structured AI call per chapter (Architect recommendation):**

Instead of adding 5-8 separate AI calls per chapter (which would triple the current ~60 calls for a 10-chapter book to ~150+), extend the existing outro call into a **single structured generation** call that returns all enrichment elements as JSON via `generate_structured()`. This keeps the call count at 3 per chapter (intro, N×subchapter, structured_outro_with_enrichment).

Structured outro call schema:
```json
{
  "chapter_summary_bullets": ["str", "str", "str"],
  "callout_insight": "str",
  "case_study": {"name": "str", "conflict": "str", "resolution": "str"},
  "action_steps": ["str", "str", "str"],
  "bridge_sentence": "str"
}
```

Rendered into markdown in `_generate_chapter()`:
- `> **Key Insight:** {callout_insight}`
- `**Example: {name}'s Story** — {conflict}. {resolution}.`
- `### Chapter Summary` + bullets
- `### Action Steps` + numbered list
- bridge sentence as closing paragraph

Hook rotation (no extra AI call — prompt instruction only, in intro generation):
- Chapter index % 3 == 0: micro-anecdote
- Chapter index % 3 == 1: counterintuitive claim
- Chapter index % 3 == 2: problem statement that makes reader feel seen
- Banned hook: "In today's world...", "As we explore..."

**Modified:** `src/pipeline/manuscript_engine.py` — `_generate_chapter()` outro section  
**Modified:** `src/config.py` — add `chapter_enrichment_enabled: bool = True`

#### 1.3 Voice Consistency Across Chapters

- Extend `StyleContext` with `recurring_metaphors: list[str] = field(default_factory=list)` and `established_terminology: dict[str, str] = field(default_factory=dict)`
- After each chapter generation, extract key terms by prompting AI: "List 2-3 domain-specific terms or metaphors introduced in this chapter as JSON: `{\"terms\": [{\"term\": str, \"definition\": str}]}`"
- Merge extracted terms into `style_ctx.established_terminology`
- Include in subchapter system prompt: "Maintain these established terms: {terms_block}"
- **Critically:** `StyleContext` is now persisted to disk after each chapter (see 2.2) — voice consistency survives crash/resume

**Modified:** `src/pipeline/manuscript_engine.py` — `_generate_chapter()`, `generate()`  
**Modified:** `src/pipeline/style_context.py` — new fields (disk persistence already covered in 2.2)

#### 1.4 Prose Quality Gate (QA)

Add `QAEngine._check_prose_quality(chapter_content, language) -> dict` (English-only checks — skip for non-`"en"` languages):
- **Banned phrases**: regex scan for style guide list — `score -= 0.1` per hit above 2
- **Sentence uniformity**: `stddev(sentence_word_counts)` — score 1.0 if stddev ≥ 5, 0.0 if < 3
- **Abstract opener**: flag if chapter starts with known AI patterns — `score -= 0.15`
- **Hedge density**: `count(hedge_words) / sentence_count` — flag if > 8%, `score -= 0.1`
- **Architecture check**: verify `### Chapter Summary` and `### Action Steps` headings present — `score -= 0.2` each if missing

Returns `{"prose_quality": float, "details": {...}}`. Add to `scores` dict in `QAEngine.run()`. Threshold: flag if `prose_quality < 0.8`.

**Modified:** `src/pipeline/qa_engine.py` — `run()`, new `_check_prose_quality()` method  
**Modified:** `app/pages/4_Export.py` — display `prose_quality` score as badge

---

### PILLAR 3 — Error Handling *(Sprint 3)*

#### 3.1 User-Facing Error Messages

- Add `ErrorClassifier` mapping exception types → user-friendly messages:
  - `PermanentAPIError` → "AI provider rejected the request. Check your API key or model name."
  - `TimeoutError` → "AI request timed out. Try again or reduce chapter length."
  - `json.JSONDecodeError` → "AI returned malformed output. Retrying automatically..."
  - Generic → "Generation failed unexpectedly. Check the logs for details."
- Surface in `app/pages/3_Progress.py` and `app/pages/2_Create_Ebook.py`
- Store classified message in `jobs.error_message` (not raw exception string)

**New file:** `src/pipeline/error_classifier.py`  
**Modified:** `src/api/server.py`, `src/pipeline/orchestrator.py`  
**Modified:** `app/pages/3_Progress.py`, `app/pages/2_Create_Ebook.py`

---

### PILLAR 4 — Test Coverage *(Sprint 4)*

#### 4.1 Integration Tests

- `tests/test_integrations/test_integration_manager.py` — add, list, delete, `invoke_webhook` (mock `httpx`), circuit breaker tripping after 2 failures
- `tests/test_integrations/test_webhook_signing.py` — HMAC-SHA256 signature generation + verification

#### 4.2 MCP Server Tests

- `tests/test_mcp/test_mcp_server.py` — test all 8 tools: `list_projects`, `create_project`, `generate`, `get_status`, `get_export_info`, `research_market`, `list_files`, `read_file`

#### 4.3 API Server Tests

- Extend `tests/test_api/test_server.py` — authentication, project CRUD, job status, download endpoint

#### 4.4 Style Guide Tests

- `tests/test_pipeline/test_style_guide.py` — `StyleGuide.to_system_prompt_block()`, banned phrase rendering, model-tier gating output difference

#### 4.5 StyleContext Persistence Tests

- `tests/test_pipeline/test_style_context.py` — `save()`, `load()`, `load_or_default()` round-trip

#### 4.6 QA Prose Quality Tests

- `tests/test_pipeline/test_qa_prose.py` — `_check_prose_quality()` with known-good and known-bad chapter fixtures

---

### PILLAR 5 — Integrations *(Sprint 3)*

#### 5.1 Webhook Invocation (`src/integrations/manager.py`)

- `invoke_webhook(integration_id, event, payload)` — fire in background thread (non-blocking pipeline)
- HTTP POST with:
  - `X-Signature-SHA256: hmac_sha256(secret, json_body)` header
  - `Content-Type: application/json`
  - `X-Event: {event}` header
- **Circuit breaker** (not just retry): track `consecutive_failures` per integration in `integration_logs`. Trip after 2 consecutive failures (set `circuit_open = True`, `circuit_open_until = now + 5min`). Skip invocation while circuit is open. Reset on first success.
- Retry: 2 attempts within the per-call execution (circuit handles persistent failures)
- Log every attempt to `integration_logs` table: `integration_id`, `event`, `status`, `http_status`, `error`, `timestamp`

**Modified:** `src/integrations/manager.py`  
**Modified:** `src/db/schema.py` — add `integration_logs` table with circuit breaker fields

#### 5.2 Pipeline Event Firing

Fire from `orchestrator.py`:
- `ebook.generation.started` — after DB status set to `generating`
- `ebook.generation.completed` — after QA passes
- `ebook.export.ready` — after export manifest written

**Modified:** `src/pipeline/orchestrator.py`

---

### PILLAR 6 — EPUB3 Compliance *(Sprint 3)*

*(MOBI removed — Amazon KDP accepts EPUB3 directly since 2021; `kindlegen` deprecated 2020)*

#### 6.1 EPUB3 Semantic Markup

- Add `epub:type` attributes: `chapter`, `introduction`, `conclusion`, `tip`, `note`
- EPUB CSS: `line-height: 1.5`, paragraph spacing not indent, `* * *` ornamental breaks between subchapter sections
- DOCX: `page-break-before` on each chapter heading style

#### 6.2 Export Manifest Format Status (see 2.4)

**Modified:** `src/export/epub_generator.py`  
**Modified:** `src/export/docx_generator.py`  
**Modified:** `app/pages/4_Export.py` — remove MOBI button, add EPUB3 compliance badge

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| StyleContext desync on resume (new voice fields lost after crash) | Medium | High | Persist to `style_context.json` after each chapter (section 2.2); `load_or_default()` on resume — mitigated |
| Webhook circuit breaker doesn't fire in background thread (blocking) | Low | High | Circuit breaker state stored in DB; background thread does not block pipeline — mitigated |
| EPUB silent failure invisible in manifest | Medium | Medium | Per-format `status` field in manifest (section 2.4) — mitigated |
| Duplicate `project_metadata` rows on repeated resume | Medium | Medium | `UNIQUE(project_id, key)` + `INSERT OR REPLACE` (section 2.2) — mitigated |
| Style guide injection degrades 7B model coherence | Medium | Medium | Model-tier gating (`"small"` injects only banned phrases + tone) — mitigated |
| Structured chapter enrichment JSON parsing fails | Low | Medium | `generate_structured()` already has JSON retry logic; fall back to plain outro on failure |
| Adding structlog increases test fixture complexity | Medium | Low | Use `structlog.testing.capture_logs()` in tests; no existing mocks need changes |
| Structured subchapters schema backward compat | Low | Low | `isinstance(sub, dict)` guard already in `manuscript_engine.py` |

---

## Verification Steps

1. `pytest --cov=src --cov-report=term-missing` — ≥90% on `integrations/`, `mcp/`, `api/`
2. `ruff check src/` — zero violations
3. `grep -rn "except" src/ | grep -E ":\s*pass$|return$" | grep -v logger` — zero results (AC-2)
4. Generate ebook with `quality_level="thorough"` — inspect `qa_report.json` for `prose_quality ≥ 0.8`, verify `### Action Steps` and `### Chapter Summary` headings in manuscript
5. Trigger webhook with `curl` to test endpoint — verify `X-Signature-SHA256` header, confirm `integration_logs` row written
6. Kill pipeline after chapter 3 of a 5-chapter book — resume — verify: chapters 1-3 not regenerated, chapter 4 opens with consistent terminology from chapter 3, `style_context.json` loaded (AC-7 + AC-8 together)
7. Inspect `manifest.json` after a forced EPUB failure — verify `"status": "failed"` present (AC-4)
8. Validate EPUB3 output: `epub:type` on chapter elements, `line-height: 1.5` in CSS (AC-4)
9. Disable integration endpoint — run 3 consecutive pipeline runs — verify circuit opens after 2 failures, 3rd run skips webhook call with `circuit_open` log

---

## Implementation Order

| Sprint | Tasks | Rationale |
|--------|-------|-----------|
| 1 | Pillar 2 (all: logging, resume, retry, manifest status) | Foundation first — logging exists before quality features land |
| 2 | Pillar 1.1 (StyleGuide) + 1.3 (Voice consistency) | StyleGuide depends on logging for debug visibility |
| 2 | Pillar 1.2 (Chapter structure enrichment) | Builds on StyleGuide |
| 2 | Pillar 1.4 (Prose QA gate) | Validates 1.1 + 1.2 output |
| 3 | Pillar 5 (Integrations webhook + circuit breaker) | Unblocks partner workflows |
| 3 | Pillar 6 (EPUB3 compliance) | Self-contained, no dependencies |
| 3 | Pillar 3.1 (Error messages) | Polish layer |
| 4 | Pillar 4 (All tests) | Lock in all changes with coverage |

---

## ADR — Architecture Decision Record

**Decision:** Implement full 6-pillar improvement plan with architect-mandated modifications.

**Drivers:**
1. User requires ebooks indistinguishable from human writing
2. Silent failures make production debugging impossible
3. Webhook integrations and EPUB3 compliance are partner/distribution requirements

**Alternatives Considered:**
- *Option B (Writing Quality Only)*: Rejected — leaves silent failures and untested modules, which compound as writing quality features add call complexity
- *MOBI export*: Rejected — Amazon KDP accepts EPUB3 directly; `kindlegen` deprecated 2020; Calibre is a 500MB dependency
- *5-8 AI calls per chapter for enrichment*: Rejected — triples call count to ~150/book; replaced with single structured JSON call
- *4 boolean config flags for chapter features*: Rejected — replaced with single `model_capability_tier` knob

**Why Chosen:** Full plan with robustness-first sequencing ensures: (a) failures are visible before complexity increases, (b) StyleContext persistence makes voice consistency + resume work together, (c) circuit breaker prevents webhook failures from blocking pipeline.

**Consequences:**
- Sprint 1 ships zero user-visible features (robustness only) — set expectations accordingly
- `model_capability_tier` field added to `PipelineConfig` — users on 7B models get degraded style injection automatically
- MOBI users must export EPUB and upload to KDP directly (already works)

**Follow-ups:**
- Token cost estimation for chapter enrichment structured call — measure before Sprint 2 ships
- Consider `QAEngine` prose quality check as a pre-export gate (fail export if score < 0.6)
- Evaluate `RefinementEngine` running on prose quality failures specifically (targeted refinement)

---

## Files Summary

**New files (9):**
- `src/logger.py`
- `src/pipeline/style_guide.py`
- `src/pipeline/error_classifier.py`
- `tests/test_integrations/test_integration_manager.py`
- `tests/test_integrations/test_webhook_signing.py`
- `tests/test_mcp/test_mcp_server.py`
- `tests/test_pipeline/test_style_guide.py`
- `tests/test_pipeline/test_style_context.py`
- `tests/test_pipeline/test_qa_prose.py`
- `tests/test_pipeline/test_error_classifier.py`

**Modified files (16):**
- `src/ai_client.py` — jitter, transient error classification
- `src/config.py` — `model_capability_tier`, `ai_request_timeout`, `ai_max_retries`, `chapter_enrichment_enabled`
- `src/pipeline/manuscript_engine.py` — style guide injection, structured enrichment call, StyleContext persistence
- `src/pipeline/style_context.py` — `recurring_metaphors`, `established_terminology`, `save()`, `load()`, `load_or_default()`
- `src/pipeline/style_guide.py` — (new, listed above)
- `src/pipeline/strategy_planner.py` — generate + save `style_guide.json`
- `src/pipeline/orchestrator.py` — webhook events, resume hardening, logging, error classifier
- `src/pipeline/qa_engine.py` — `_check_prose_quality()`, `prose_quality` score
- `src/integrations/manager.py` — webhook invocation, circuit breaker
- `src/db/schema.py` — `UNIQUE(project_id, key)`, `integration_logs` table
- `src/export/export_orchestrator.py` — per-format status in manifest
- `src/export/epub_generator.py` — EPUB3 semantic markup, CSS
- `src/export/docx_generator.py` — chapter page breaks, logging
- `src/api/server.py` — logging, error classifier integration
- `app/pages/4_Export.py` — prose quality badge, EPUB3 compliance badge
- `requirements.txt` — `structlog`

**Migration note:** Adding `UNIQUE(project_id, key)` to the existing `project_metadata` table requires a table rebuild on existing databases (`CREATE TABLE new_table ... INSERT INTO new_table SELECT ... DROP TABLE ... ALTER TABLE RENAME`). For fresh installs, the constraint is added directly in `schema.py`. The `DatabaseManager` should detect existing tables via `PRAGMA table_info` and apply migration if the constraint is absent.

**Changelog from Rev 1:**
- Removed MOBI scope (section 6.1 deleted, `src/export/mobi_converter.py` removed from new files)
- Reordered sprints: Pillar 2 Sprint 1 alone; Pillar 1 Sprint 2
- Added `StyleContext.save()/load()` to sections 1.3 and 2.2
- Replaced 4 boolean config flags with `model_capability_tier`
- Replaced 5-8 chapter enrichment AI calls with single structured JSON call
- Expanded silent exception inventory from 9 to ~20 locations (AC-2 now grep-verifiable)
- Added `UNIQUE(project_id, key)` to section 2.2 (schema change required)
- Added circuit breaker to section 5.1 (not just retry)
- Added per-format `status` field to export manifest (section 2.4)
- Fixed AC-4 (MOBI → EPUB3 compliance), AC-5 (heuristic proxy, not AI eval), AC-6 (separate refinement from QA score)
- Replaced stale line-number references with method names throughout
- Added ADR section
