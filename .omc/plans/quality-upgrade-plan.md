# Ebook Quality Upgrade — SDD+TDD Plan
**RALPLAN-DR Consensus: APPROVED** (Planner → Architect → Critic, 2 iterations)
**Date:** 2026-04-06

---

## ADR

**Decision:** Implement 8-pillar quality upgrade with new `ProseScorer`, `ChapterStructureChecker`, `BookStructureGenerator` services, EPUB3 compliance fixes, and a post-QA retry loop with failure context.

**Drivers:**
1. Current QA has 5 heuristics but misses Flesch readability, passive voice, MATTR — the most measurable AI-slop signals
2. Generated ebooks have no front/back matter (no copyright, no TOC page, no glossary, no About Author)
3. Retry loop is blind — retries use identical prompt with no failure context

**Alternatives considered:**
- Option A (incremental patches): Fast but leaves structural gaps unfixed
- Option C (spaCy/BERT): Out of scope — 500MB+ deps, high latency

**Why Option B (new services + structural chapters):** Quantifiable thresholds, testable, no heavyweight deps.

**Consequences:** +27 tests, +3 new pipeline modules, 4 modified modules, `textstat` added to requirements.

**Follow-ups:** epubcheck validation, ±10% word count (after calibration data), ML-based coherence scoring.

---

## Pillars

### Pillar 1 — `ProseScorer` (NEW: `src/pipeline/prose_scorer.py`)

```python
@dataclass
class ProseScorerResult:
    flesch_reading_ease: float     # target: 60–75 (nonfiction)
    fk_grade_level: float          # target: 8–11
    gunning_fog: float             # target: ≤ 13
    smog_index: float              # target: 8–11
    passive_voice_ratio: float     # target: < 0.10
    avg_sentence_length: float     # target: 15–20
    sentence_length_stdev: float   # target: > 5
    mattr_500: float               # target: ≥ 0.55
    ai_slop_density: float         # target: < 1.0 per 500 words
    paragraph_avg_sentences: float # target: 3–5
    score: float                   # 0.0–1.0 composite
    violations: list[str]

class ProseScorer:
    def score(self, text: str, genre: str = "nonfiction") -> ProseScorerResult
```

**Key implementation notes:**
- `textstat` for Flesch/FK/Gunning Fog/SMOG (advisory — capped penalty, NOT hard blocker)
- Passive voice regex with irregular participles:
  ```python
  IRREGULAR = r"broken|shown|built|written|driven|caught|spoken|taken|given|made|known|seen|done|gone|found|told|kept|left|held|brought|bought|thought|fought|sought|taught|won|run|hung|struck|chosen|frozen|stolen|worn|torn|born|drawn|grown|thrown|blown|flown|sworn|cut|hit|put|set|let|bid|cast|cost|hurt|burst|spread|read|led|fed|fled|bled|bred|met|felt|smelt|spelt|heard|meant|dealt|leant|dreamt|learnt|bent|spent|sent|lent|said|paid|laid|made|had|been|got"
  PASSIVE = re.compile(rf'\b(was|were|is|are|been|be|being)\s+(\w+ed|{IRREGULAR})\b', re.IGNORECASE)
  ```
  Known limitation: false-positive on adjectives ("was excited") — acceptable ~5% rate.
- MATTR: pure Python sliding 500-word window TTR
- Constructor-injected into QAEngine (no ABC — matches codebase pattern)
- **Migrate** `tests/test_pipeline/test_qa_prose.py` into `tests/test_pipeline/test_prose_scorer.py` (rewrite calls to `ProseScorer.score()`, not `qa._check_prose_quality()`)

**43 AI slop patterns:**
```python
SLOP_PATTERNS = [
    r'\bdelve\b', r"\bit's worth noting\b", r'\bin conclusion\b',
    r'\bas we explore\b', r"\bin today's fast[- ]paced world\b",
    r'\bit is important to note\b', r'\bfurthermore\b', r'\bmoreover\b',
    r'\badditionally\b', r'\bneedless to say\b', r'\bin today\'s world\b',
    r'\bit is worth noting\b', r'\btapestry\b', r'\blandscape\b',
    r'\brealm\b', r'\bnotably\b', r'\bindeed\b', r'\bit should be noted\b',
    r'\bin summary\b', r'\bserves as\b', r'\bstands as\b', r'\bfosters?\b',
    r'\bunderscore[sd]?\b', r'\bshowcase[sd]?\b', r'\bbolsters?\b',
    r'\bgarners?\b', r'\benhances?\b', r'\bpivotal\b', r'\bcrucial\b',
    r'\brobust\b', r'\bcomprehensive\b', r'\bmeticulous\b', r'\bintricate\b',
    r'\bnuanced\b', r'\bprofound\b', r'\bgroundbreaking\b',
    r'\bcutting[- ]edge\b', r'\binnovative\b', r"\blet's explore\b",
    r'\bwe will explore\b', r'\bin this chapter(?:,? we will)?\b',
    r'\bthis chapter (?:covers|explores|discusses)\b',
    r'\bit goes without saying\b', r'\bthereby (?:fostering|creating|enabling)\b',
    r'\bnot just .{0,30} but also\b', r'\bsynergy\b', r'\bnexus\b',
    r'\bparadigm shift\b', r'\bgame[- ]changer\b', r'\bdynamic\b',
    r'\bvibrant\b', r'\bcompelling\b', r'\bseamless(?:ly)?\b',
]
```

**Tests (`tests/test_pipeline/test_prose_scorer.py` — 9 tests):**
- `test_flesch_on_clean_prose` — known-good text scores 60–75
- `test_flesch_on_ai_slop` — slop text scores < 50
- `test_passive_voice_ratio_below_threshold` — clean text < 0.10
- `test_passive_voice_detects_irregular` — "was written by" detected
- `test_mattr_returns_value_in_range` — diverse prose ≥ 0.55
- `test_mattr_repetitive_prose` — repetitive text < 0.55
- `test_ai_slop_density_flagged` — "moreover furthermore notable robust" > 1.0
- `test_ai_slop_density_clean` — professional prose < 1.0
- `test_paragraph_avg_sentences` — 9-sentence paragraphs penalized

---

### Pillar 2 — `ChapterStructureChecker` (NEW: `src/pipeline/chapter_structure_checker.py`)

Scope: NET-NEW validations only (does NOT duplicate existing action-steps/summary checks in qa_engine.py).

```python
@dataclass
class ChapterStructureResult:
    has_narrative_hook: bool      # first paragraph NOT meta-description
    h2_count: int                 # target: 2–8
    has_case_study: bool          # H2 or aside with "case study|example|story"
    prohibited_openers: list[str] # banned opening phrases detected
    structure_score: float        # 0.0–1.0

class ChapterStructureChecker:
    def check(self, chapter_text: str) -> ChapterStructureResult
```

**Prohibited opener patterns:**
- `r'^In this chapter(?:,? we will)?'`
- `r'^This chapter (?:covers|explores|discusses)'`
- `r'^As we discussed in the previous chapter'`
- `r'^\w+ is defined as'`
- `r'^In today\'s'`

**Tests (`tests/test_pipeline/test_chapter_structure.py` — 6 tests):**
- `test_narrative_hook_detected`
- `test_meta_opener_rejected`
- `test_h2_count_too_low` — 1 H2 fails
- `test_h2_count_too_high` — 9 H2s fails
- `test_case_study_detected`
- `test_structure_score_perfect`

---

### Pillar 3 — `BookStructureGenerator` (NEW: `src/pipeline/book_structure.py`)

```python
class BookStructureGenerator:
    def generate_front_matter(self, project: dict, outline: dict) -> None
    # Persists to projects/{id}/front_matter/:
    #   toc_page.md   (auto-built from outline, no AI call)
    #   title_page.md (no AI call — template)
    #   copyright.md  (no AI call — template)
    #   dedication.md (AI-generated 1-2 sentences)
    #   preface.md    (AI-generated 200-300 words)

    def generate_back_matter(self, project: dict, style_ctx: StyleContext) -> None
    # Persists to projects/{id}/back_matter/:
    #   glossary.md     (from style_ctx.established_terminology, no AI if empty)
    #   about_author.md (AI-generated 100-200 words)
```

**Resume logic:** Check file existence before each AI call — no re-generation if file already written.

**Pipeline stage order (updated):**
```
1. Strategy      → set_metadata("stage:strategy", "completed")
2. Outline       → set_metadata("stage:outline", "completed")
3. FrontMatter   → set_metadata("stage:front_matter", "completed")  ← NEW
4. Manuscript    → set_metadata("stage:manuscript", "completed")
5. BackMatter    → set_metadata("stage:back_matter", "completed")   ← NEW
6. Cover         → set_metadata("stage:cover", "completed")
7. QA            → set_metadata("stage:qa", "completed")
8. [post-QA retry loop — if QA failed]                              ← NEW
9. Export        → set_metadata("stage:export", "completed")
```

**EPUB integration:** `epub_generator.py` loads `front_matter/*.md` and `back_matter/*.md` in order before/after body chapters.

**Tests (`tests/test_pipeline/test_book_structure.py` — 5 tests):**
- `test_front_matter_title_page_written`
- `test_front_matter_toc_matches_outline`
- `test_front_matter_copyright_contains_year`
- `test_back_matter_has_about_author`
- `test_glossary_contains_established_terms`

---

### Pillar 4 — EPUB3 Compliance (`src/export/epub_generator.py`)

**Changes:**
- Add `<nav epub:type="landmarks">` in nav document alongside existing TOC nav
- CSS body: `font-size: 1em`, `line-height: 1.5` (unitless), margins in `em`
- All images: `max-width: 100%`, wrapped in `<figure epub:type="figure"><figcaption>`
- Front matter pages: `epub:type="titlepage"`, `epub:type="copyright-page"`, etc.
- Back matter pages: `epub:type="backmatter"` + specific subtype

**Tests (`tests/test_export/test_epub_quality.py` — 5 tests):**
- `test_epub_has_landmarks_nav`
- `test_chapter_epub_type_present`
- `test_css_uses_relative_units` — no `px` or `pt` in body rules
- `test_css_line_height_on_body` — value between 1.2 and 1.6
- `test_images_have_alt_text`

---

### Pillar 5 — Style Guide Expansion (`src/pipeline/style_guide.py`)

**Changes:**
- `banned_phrases`: 13 → 43 (sync with ProseScorer's SLOP_PATTERNS)
- Add `readability_target: dict = field(default_factory=lambda: {"nonfiction": {"fre_min": 60, "fre_max": 75}})`
- Add `passive_voice_threshold: float = 0.10`
- Add `paragraph_max_sentences: int = 8`
- `detect_violations()` returns `(list[str], float)` — violations + density
- `to_system_prompt_block("large")`: add readability instruction ("Write at Flesch Reading Ease 60–70")

---

### Pillar 6 — QA Engine Integration (`src/pipeline/qa_engine.py`)

**Changes:**
- Replace `_check_prose_quality()` with delegation to injected `ProseScorer`
- Add `_check_chapter_structure()` using `ChapterStructureChecker`
- Fix hardcoded string at line 129: `f"±{tolerance*100:.0f}%"` (was `"±20%"`)
- Fix positional chapter indexing bug → match by title (consistent with `_check_structure`)
- Default `qa_word_count_tolerance`: `0.20 → 0.15`
- New config keys in `config.py`:
  ```python
  qa_word_count_tolerance: float = 0.15        # was 0.20
  qa_readability_enabled: bool = True
  qa_structure_check_enabled: bool = True
  qa_post_qa_retries: int = 2
  ```

**Post-QA retry loop in `PipelineOrchestrator._run_pipeline()`:**
```python
# Between QA stage and Export stage:
if not qa_report["passed"]:
    for attempt in range(config.qa_post_qa_retries):
        failing_chapters = extract_failing_chapters(qa_report)
        for ch_idx, failure_context in failing_chapters:
            ms_engine.regenerate_chapter(ch_idx, failure_context)
        qa_report = qa_engine.run(project_id)
        if qa_report["passed"]:
            break
    else:
        repo.update_project_status(project_id, "failed")
        return  # DO NOT export below threshold
```

New method: `ManuscriptEngine.regenerate_chapter(chapter_idx: int, failure_context: str) -> str`
- Injects `failure_context` into generation prompt: "Previous attempt failed: {failure_context}. Please fix these issues."
- Adds structured logging of retry attempt, word count achieved vs target.

**Tests (update `tests/test_pipeline/test_qa_engine.py` — 4 new):**
- `test_qa_fails_on_ai_slop_chapter`
- `test_qa_fails_on_high_passive_voice`
- `test_qa_passes_on_professional_prose`
- `test_qa_error_message_reflects_tolerance`

---

### Pillar 7 — E2E Quality Tests (`tests/test_e2e_quality.py` — 2 tests)

```python
PROFESSIONAL_PROSE = """..."""  # Pre-written 1500-word chapter passing all thresholds
AI_SLOP_PROSE = """Moreover, in today's fast-paced world, it is worth noting that..."""

def test_full_pipeline_produces_quality_ebook(tmp_path):
    # mock_ai returns PROFESSIONAL_PROSE for chapters
    # → pipeline runs → qa_report["passed"] is True → EPUB created
    assert qa_report["passed"] is True
    assert (tmp_path / "exports/ebook.epub").exists()

def test_full_pipeline_fails_on_ai_slop(tmp_path):
    # mock_ai returns AI_SLOP_PROSE for chapters
    # → QA catches it → project marked "failed"
    assert qa_report["passed"] is False
    assert project["status"] == "failed"
```

---

### Pillar 8 — Export Page Quality Report (`app/pages/4_Export.py`)

- `st.metric` for: Flesch Grade, Passive Voice %, Vocabulary Richness (MATTR), AI Slop Density, Structure Score
- Color badge: 🟢 within target / 🟡 borderline / 🔴 failed
- Per-chapter breakdown in expander

---

## Acceptance Criteria

| # | Criterion | Test |
|---|---|---|
| AC-1 | ProseScorer.score() returns Flesch 60–75 on clean prose | test_flesch_on_clean_prose |
| AC-2 | Passive voice ratio < 0.10 on clean chapter | test_passive_voice_ratio_below_threshold |
| AC-3 | AI slop density > 1.0 on slop-heavy text | test_ai_slop_density_flagged |
| AC-4 | ChapterStructureChecker detects prohibited openers | test_meta_opener_rejected |
| AC-5 | Front matter has title page + copyright + TOC | test_front_matter_toc_matches_outline |
| AC-6 | EPUB has landmarks nav | test_epub_has_landmarks_nav |
| AC-7 | QA fails on AI-slop chapter | test_qa_fails_on_ai_slop_chapter |
| AC-8 | Word count tolerance 15%; error message reflects config value | test_qa_word_count_tolerance + test_qa_error_message_reflects_tolerance |
| AC-9 | E2E: realistic prose → QA passes → EPUB created | test_full_pipeline_produces_quality_ebook |
| AC-10 | Post-QA retry includes failure context in prompt | test_retry_includes_failure_context |
| AC-11 | MATTR returns ≥ 0.55 on diverse prose | test_mattr_returns_value_in_range |

---

## Verification Steps

1. `pytest tests/test_pipeline/test_prose_scorer.py -v` — 9 tests pass
2. `pytest tests/test_pipeline/test_chapter_structure.py -v` — 6 tests pass
3. `pytest tests/test_pipeline/test_book_structure.py -v` — 5 tests pass
4. `pytest tests/test_export/test_epub_quality.py -v` — 5 tests pass
5. `pytest tests/test_e2e_quality.py -v` — golden passes, slop fails
6. `pytest --cov=src tests/ -q` — coverage ≥ 80% on new modules
7. Generate test ebook via UI → Export page shows per-metric scores with color badges

---

## File Impact Map

```
ADD:
  src/pipeline/prose_scorer.py
  src/pipeline/chapter_structure_checker.py
  src/pipeline/book_structure.py
  tests/test_pipeline/test_prose_scorer.py        (9 tests — migrated from test_qa_prose.py)
  tests/test_pipeline/test_chapter_structure.py   (6 tests)
  tests/test_pipeline/test_book_structure.py      (5 tests)
  tests/test_export/test_epub_quality.py          (5 tests)
  tests/test_e2e_quality.py                       (2 tests)

MODIFY:
  src/pipeline/qa_engine.py
  src/pipeline/style_guide.py
  src/pipeline/manuscript_engine.py     (7-part prompt, regenerate_chapter method)
  src/pipeline/orchestrator.py          (FrontMatter/BackMatter stages, post-QA retry loop)
  src/export/epub_generator.py          (landmarks nav, front/back matter, CSS)
  src/config.py                         (qa_word_count_tolerance=0.15, new keys)
  app/pages/4_Export.py                 (expanded quality report)
  requirements.txt                      (add textstat>=0.7.3)

DELETE:
  tests/test_pipeline/test_qa_prose.py  (merged into test_prose_scorer.py)
```

---

## Implementation Order (SDD+TDD)

**Phase 1 (pure logic, no pipeline integration):**
- Write test_prose_scorer.py → implement prose_scorer.py
- Write test_chapter_structure.py → implement chapter_structure_checker.py
- Expand style_guide.py banned phrases

**Phase 2 (pipeline integration):**
- Write test_book_structure.py → implement book_structure.py
- Update qa_engine.py (delegate, fix string, fix indexing bug, tolerance)
- Update orchestrator.py (new stages, post-QA retry loop)
- Update manuscript_engine.py (regenerate_chapter method)

**Phase 3 (export + E2E):**
- Write test_epub_quality.py → update epub_generator.py
- Write test_e2e_quality.py → run full pipeline, iterate until passing
- Update Export page UI

Each phase: write failing tests first → implement → run tests → green.
