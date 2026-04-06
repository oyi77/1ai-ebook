# Manga/Comics Full Generation Capability — SDD+TDD Plan
**RALPLAN-DR Consensus: APPROVED** (Planner → Architect → Critic, 2 iterations)
**Date:** 2026-04-06

---

## ADR

**Decision:** Implement comics/manga generation as a separate `ComicsOrchestrator` with top-level delegation from `PipelineOrchestrator.run_full_pipeline()`. Comics-specific stages: ScriptEngine → CharacterSheet → PanelArtGenerator → PageComposer → ComicsExporter.

**Drivers:**
1. `generate_image()` already exists on OmnirouteClient — no new API surface needed
2. PIL/Pillow already installed — page composition feasible without new heavy dependencies
3. Separate orchestrator avoids regression risk to existing 230-line `_run_pipeline()`

**Alternatives considered:**
- Option A (extend ManuscriptEngine): ❌ text engine becomes messy hybrid with image logic
- Option C (microservice): ❌ over-engineered, breaks unified pipeline

**Consequences:** `fpdf2` is the only new dependency (~200KB, pure-Python). Character consistency ~60-70% via description injection (img2img deferred to v2). RTL text in speech bubbles deferred (page/panel order is RTL-aware; dialogue text is Latin/ASCII for MVP).

**Follow-ups:** img2img character anchor using portrait reference panel, Japanese vertical text rendering, RTL Arabic/Hebrew speech bubbles.

---

## New ProductModes

```python
MANGA    = "manga"      # Japanese, right-to-left pages, B&W, screen tones
MANHWA   = "manhwa"     # Korean, left-to-right, color webtoon vertical scroll
MANHUA   = "manhua"     # Chinese, left-to-right, color webtoon
COMICS   = "comics"     # Western, left-to-right, page format, color
```

---

## Panel JSON Schema (required for AC-1)

```python
PANEL_SCHEMA = {
    "panel_id": str,              # "ch1-p3-pan2"
    "scene_description": str,     # "Wide shot: rooftop at dusk, Akira at edge"
    "characters_present": list,   # ["Akira", "Villain"]
    "dialogue": [
        {"character": str, "text": str, "is_sfx": bool}
    ],
    "sfx": list,                  # ["BOOM", "CRASH"]
    "framing": str,               # "wide_shot|close_up|medium|over_shoulder|extreme_close_up"
    "panel_size": str,            # "normal|large|splash"
}
PAGE_SCHEMA   = {"page_number": int, "layout": str, "panels": [PANEL_SCHEMA]}
CHAPTER_SCHEMA = {"number": int, "title": str, "pages": [PAGE_SCHEMA]}
SCRIPT_SCHEMA = {
    "title": str, "format": str,
    "characters": [{"name": str, "visual_description": str, "role": str}],
    "chapters": [CHAPTER_SCHEMA],
}
```

---

## Components

### 1 — ScriptEngine (`src/pipeline/comics/script_engine.py`)

```python
class ComicsScriptEngine:
    def generate(self, project_brief: dict, strategy: dict) -> dict
    # One generate_structured() call per chapter to avoid token limits
    # Persists to script.json
```

**Style prompts by format:**
```python
FORMAT_CONVENTIONS = {
    "manga":   "Japanese manga conventions: RTL page order, B&W with screen tones, expressive chibi reactions",
    "manhwa":  "Korean manhwa webtoon: LTR, full color, vertical scroll panels, clean digital art",
    "manhua":  "Chinese manhua: LTR, full color webtoon, detailed backgrounds",
    "comics":  "Western comics: LTR page layout, bold outlines, cel shading, dynamic superhero poses",
}
```

**Tests (`tests/test_pipeline/comics/test_script_engine.py` — 5):**
- `test_script_has_required_fields` — all PANEL_SCHEMA keys present
- `test_panels_have_scene_descriptions`
- `test_dialogue_structure_valid`
- `test_manga_format_recorded_in_script`
- `test_script_saved_to_disk`

---

### 2 — CharacterSheet (`src/pipeline/comics/character_sheet.py`)

```python
@dataclass
class Character:
    name: str
    visual_description: str  # injected into every panel prompt
    role: str                # "protagonist|antagonist|supporting"

class CharacterSheet:
    def build_from_script(self, script: dict) -> None
    def get_panel_prompt_context(self, characters_present: list[str]) -> str
    def save(self, path: Path) -> None
    def load(self, path: Path) -> None
```

**Tests (`tests/test_pipeline/comics/test_character_sheet.py` — 4):**
- `test_build_from_script_extracts_characters`
- `test_panel_prompt_context_contains_descriptions`
- `test_missing_character_gracefully_omitted`
- `test_save_load_roundtrip`

---

### 3 — PanelArtGenerator (`src/pipeline/comics/panel_art_generator.py`)

```python
class PanelArtGenerator:
    def generate_page_panels(
        self,
        page: dict,
        character_sheet: CharacterSheet,
        style: str,
        panels_dir: Path,
    ) -> dict[str, Path]   # panel_id → PNG path
```

**Parallelism:** `ThreadPoolExecutor(max_workers=config.comics_parallel_workers)` per page.

**Prompt:** `"{scene_description}. {character_context}. {framing} shot. {style_prompt}. No text, no speech bubbles."`

**Error handling:**
```python
with ThreadPoolExecutor(max_workers=config.comics_parallel_workers) as executor:
    futures = {executor.submit(self._generate_one, panel, ...): panel for panel in panels}
    for future in as_completed(futures):
        panel = futures[future]
        try:
            result = future.result()
        except Exception as e:
            logger.warning("panel_generation_failed", panel_id=panel["panel_id"], error=str(e))
            result = self._make_placeholder(panel)  # PIL fallback, NEVER raises
        results[panel["panel_id"]] = result
```

**Atomic writes:** Write to `panel_id.tmp.png`, then `rename()` to `panel_id.png` — resume-safe under concurrent execution.

**Resume-safe:** Check `panel_path.exists()` before any API call.

**PIL placeholder:** light gray background, centered scene description text, "[AI image unavailable]" label.

**Tests (`tests/test_pipeline/comics/test_panel_art_generator.py` — 5):**
- `test_panel_cached_if_exists` — no API call if PNG exists
- `test_fallback_creates_valid_png`
- `test_fallback_image_correct_dimensions`
- `test_style_prompt_contains_format_keywords`
- `test_parallel_failure_uses_placeholder` — one future raises, others succeed, all panels produced

---

### 4 — PageComposer (`src/pipeline/comics/page_composer.py`)

```python
class PageComposer:
    LAYOUTS = {
        "2x2":              [(0,0,.5,.5),(.5,0,1,.5),(0,.5,.5,1),(.5,.5,1,1)],
        "splash":           [(0,0,1,1)],
        "3-panel":          [(0,0,1,.4),(0,.4,.5,1),(.5,.4,1,1)],
        "4-panel-vertical": [(0,0,1,.25),(0,.25,1,.5),(0,.5,1,.75),(0,.75,1,1)],
    }

    def compose_page(
        self,
        page: dict,
        panel_images: dict[str, Image.Image],
        rtl: bool = False,
        output_size: tuple = (1200, 1694),
    ) -> Image.Image

    def compose_webtoon_strip(
        self,
        pages: list[Image.Image],
        panel_width: int = 800,
    ) -> Image.Image
```

**RTL support:** When `rtl=True`, panel order within page reversed (right→left, top→bottom). Page content ordering in the reader is determined by `ComicInfo.xml`, not filename reversal.

**Speech bubble rendering:**
```python
def _draw_speech_bubble(self, draw, text, position, font):
    # 1. textwrap.wrap(text, width) to fit bubble
    # 2. ImageDraw.textbbox() to measure wrapped text dimensions
    # 3. draw.rounded_rectangle() for bubble body
    # 4. draw.polygon() for tail pointing to speaker
    # 5. draw.text() for wrapped lines
```

**SFX rendering:** Large bold text, random ±10° rotation, positioned at panel edge.

**Known limitation:** Speech bubble text is always LTR (Latin/ASCII). RTL script rendering deferred to v2.

**Tests (`tests/test_pipeline/comics/test_page_composer.py` — 6):**
- `test_2x2_layout_has_4_panels`
- `test_splash_layout_fills_full_page`
- `test_rtl_reverses_panel_order`
- `test_speech_bubble_rendered_on_page`
- `test_output_size_matches_spec`
- `test_webtoon_strip_height_equals_sum_of_pages`

---

### 5 — ComicsExporter (`src/export/comics_exporter.py`)

```python
class ComicsExporter:
    def export(self, project_id: str, pages: list[Image.Image], fmt: str) -> dict
    def _export_cbz(self, pages, output_path) -> Path
    # page_001.png, page_002.png... + ComicInfo.xml
    def _export_webtoon(self, pages, output_path) -> Path
    # Single tall PNG via PageComposer.compose_webtoon_strip()
    def _export_pdf(self, pages, output_path) -> Path
    # fpdf2: pdf.add_page() + pdf.image() per page
```

**CBZ RTL:** Include `ComicInfo.xml` with `<Manga>YesAndRightToLeft</Manga>` for RTL formats. Standard file naming (`page_001.png`) — no reversal needed.

**Tests (`tests/test_export/test_comics_exporter.py` — 5):**
- `test_cbz_is_valid_zip_with_pngs`
- `test_cbz_pages_ordered_correctly`
- `test_cbz_rtl_has_comicinfo_xml`
- `test_webtoon_strip_is_single_tall_image`
- `test_pdf_export_creates_file`

---

### 6 — ComicsOrchestrator (`src/pipeline/comics/comics_orchestrator.py`)

Manages its own status updates, webhook firing, and stage checkpointing (mirrors `PipelineOrchestrator` patterns, does NOT share code — avoids regression risk).

**Stage order:**
```
1. Script        → script.json             → set_metadata("stage:script", "completed")
2. CharSheet     → character_sheet.json    → set_metadata("stage:character_sheet", "completed")
3. PanelArt      → panels/{id}.png         → set_metadata("stage:panel_art", "completed")
4. PageCompose   → pages/page_NNN.png      → set_metadata("stage:pages", "completed")
5. ComicsQA      → verify all PNGs valid   → set_metadata("stage:qa", "completed")
6. Export        → exports/{cbz,webtoon,pdf} → set_metadata("stage:export", "completed")
```

**ComicsQA (lightweight):** Verify all expected panel PNG files exist and `PIL.Image.open()` succeeds on each. No prose scoring, no word count.

**Progress callbacks:** 0-10% (script), 10-20% (chars), 20-80% (panels), 80-90% (pages), 90-95% (QA), 95-100% (export).

---

### 7 — Delegation in `PipelineOrchestrator` (~10 lines added)

```python
COMICS_MODES = {"manga", "manhwa", "manhua", "comics"}

def run_full_pipeline(self, project_id, on_progress=None, ...):
    project = self.repo.get_project(project_id)
    if project.get("product_mode") in COMICS_MODES:
        from src.pipeline.comics.comics_orchestrator import ComicsOrchestrator
        comics = ComicsOrchestrator(
            db_path=self.db_path,
            projects_dir=self.projects_dir,
            ai_client=self.ai_client,
        )
        return comics.run(project_id, on_progress=on_progress)
    # existing ebook pipeline — ZERO lines changed below this point
    ...
```

**Note:** `ProductMode` enum in `src/db/models.py` must be updated FIRST — `ProjectIntake` validates product_mode against the enum.

---

### 8 — UI Updates (`app/pages/2_Create_Ebook.py`)

```python
"manga":   "🎌 Manga — Japanese, right-to-left, B&W",
"manhwa":  "🇰🇷 Manhwa — Korean webtoon, color, vertical scroll",
"manhua":  "🇨🇳 Manhua — Chinese webtoon, color",
"comics":  "💥 Comics — Western page format, color",

# Comics-specific fields:
if product_mode in {"manga", "manhwa", "manhua", "comics"}:
    pages_per_chapter = st.slider("Pages per Chapter", 4, 24, 8)
    panels_per_page   = st.selectbox("Panel Layout", ["2x2 (4 panels)", "3-panel", "4-panel-vertical", "splash"])
    art_style         = st.selectbox("Art Style", ["detailed", "simple", "chibi", "realistic"])
```

---

## conftest.py update

```python
import io
from PIL import Image
from unittest.mock import MagicMock

def _make_minimal_png(width=64, height=64) -> bytes:
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# In mock_ai_client fixture — ADD:
client.generate_image = MagicMock(return_value=_make_minimal_png())
```

---

## Acceptance Criteria (12)

| # | Criterion | Test |
|---|---|---|
| AC-1 | ScriptEngine output has all PANEL_SCHEMA required fields | test_script_has_required_fields |
| AC-2 | CharacterSheet save/load preserves all character descriptions | test_save_load_roundtrip |
| AC-3 | PanelArtGenerator skips cached panels | test_panel_cached_if_exists |
| AC-4 | PanelArtGenerator PIL fallback on API failure, no raise | test_fallback_creates_valid_png |
| AC-5 | PageComposer 2x2 places 4 panels in correct grid positions | test_2x2_layout_has_4_panels |
| AC-6 | Speech bubbles appear on composed page with dialogue text | test_speech_bubble_rendered_on_page |
| AC-7 | RTL mode reverses panel order within page | test_rtl_reverses_panel_order |
| AC-8 | CBZ export is valid ZIP containing ordered PNG files | test_cbz_is_valid_zip_with_pngs |
| AC-9 | Webtoon export is single PNG with height = sum of page heights | test_webtoon_strip_is_single_tall_image |
| AC-10 | manga product_mode routes to ComicsOrchestrator.run() | test_comics_mode_routes_to_comics_orchestrator |
| AC-11 | E2E: manga mode → script → pages → CBZ exists on disk | test_e2e_manga_pipeline |
| AC-12 | config.comics_parallel_workers defaults to 4 | test_comics_config_defaults |

---

## Verification Steps

1. `pytest tests/test_pipeline/comics/ -v` — 18 unit tests pass
2. `pytest tests/test_export/test_comics_exporter.py -v` — 5 tests pass
3. `pytest tests/test_e2e_comics.py -v` — E2E golden path passes
4. `pytest tests/ -q --tb=no` — existing 226 tests still pass (no regression)
5. Open `ebook.aitradepulse.com`, select Manga mode, generate a 3-chapter test book
6. Download CBZ, open in YACReader/CDisplayEx, verify RTL page order
7. Download webtoon PNG, verify single tall image

---

## File Impact Map

```
NEW (14 files):
  src/pipeline/comics/__init__.py
  src/pipeline/comics/script_engine.py
  src/pipeline/comics/character_sheet.py
  src/pipeline/comics/panel_art_generator.py
  src/pipeline/comics/page_composer.py
  src/pipeline/comics/comics_orchestrator.py
  src/export/comics_exporter.py
  tests/test_pipeline/comics/__init__.py
  tests/test_pipeline/comics/test_script_engine.py     (5 tests)
  tests/test_pipeline/comics/test_character_sheet.py   (4 tests)
  tests/test_pipeline/comics/test_panel_art_generator.py (5 tests)
  tests/test_pipeline/comics/test_page_composer.py     (6 tests)
  tests/test_export/test_comics_exporter.py            (5 tests)
  tests/test_e2e_comics.py                             (2 tests)

MODIFIED (7 files):
  src/db/models.py              — 4 new ProductMode values (do FIRST)
  src/pipeline/pipeline_profile.py — 4 comics profiles
  src/pipeline/orchestrator.py  — ~10 lines at top of run_full_pipeline()
  src/config.py                 — comics_parallel_workers: int = 4
  app/pages/2_Create_Ebook.py   — comics modes + UI fields
  requirements.txt              — add fpdf2>=2.7.0
  conftest.py                   — add generate_image mock to mock_ai_client
```

---

## Implementation Order (SDD+TDD)

**Phase 1 — Pure logic (parallel):**
- Write test_character_sheet.py → implement character_sheet.py
- Write test_page_composer.py → implement page_composer.py

**Phase 2 — Script + Art (parallel):**
- Write test_script_engine.py → implement script_engine.py
- Write test_panel_art_generator.py → implement panel_art_generator.py

**Phase 3 — Export + Orchestration:**
- Write test_comics_exporter.py → implement comics_exporter.py
- Implement comics_orchestrator.py
- Wire into PipelineOrchestrator + update models/config/UI

**Phase 4 — E2E:**
- Write test_e2e_comics.py → run pipeline → verify passes
- Full regression: `pytest tests/ -q --tb=no` → 226+ pass

Each phase: write failing tests → implement → green.
