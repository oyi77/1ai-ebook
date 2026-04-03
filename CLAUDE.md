# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_pipeline/test_intake.py

# Run a single test by name
pytest tests/test_pipeline/test_intake.py::TestProjectIntake::test_create_project

# Run by marker
pytest -m unit
pytest -m integration

# Lint
ruff check

# Run with coverage
pytest --cov=src
```

## Environment

Copy `.env.example` to `.env`. The only required env var is:

- `OMNIROUTE_BASE_URL` — defaults to `http://localhost:20128/v1` (local OmniRoute proxy)

The `OMNIROUTE_API_KEY` has a hardcoded default fallback in `src/ai_client.py`; no key config is needed for local dev.

PDF export requires LibreOffice: `libreoffice` or `soffice` must be on `PATH`.

## Architecture

This is an AI-powered ebook generation pipeline with a Streamlit frontend (not yet in `src/`), SQLite persistence, a file-based project store, and a background job queue.

### AI Client (`src/ai_client.py`)

`OmnirouteClient` wraps the OpenAI SDK pointed at a local OmniRoute proxy (`localhost:20128/v1`). It is **not** the OpenAI API. All pipeline stages receive an injected `OmnirouteClient`; tests mock it via `mock_ai_client` fixture. Two methods: `generate_text` (returns str) and `generate_structured` (parses JSON response into dict).

### Pipeline stages (`src/pipeline/`)

Stages run in order, each class taking injected dependencies:

1. **`ProjectIntake`** — validates user input, persists project to SQLite via `ProjectRepository`, returns project dict.
2. **`StrategyPlanner`** — calls AI to produce audience/tone/goal strategy; saves `strategy.json` to project dir.
3. **`OutlineGenerator`** — calls AI to produce chapter list with word count targets; saves `outline.json` and `toc.md`.
4. **`ManuscriptEngine`** — iterates chapters sequentially (passes previous chapter summary for continuity), writes each to `chapters/{n}.md`, aggregates into `manuscript.md`.
5. **`QAEngine`** — structural checks (chapter title matching) + word count ±20% tolerance; optional AI consistency check stub.
6. **`ContentSafety`** — keyword blocklist check + disclaimer injection.

An `orchestrator` module (compiled `.pyc` present, source not in tree) likely wires these together.

### Database (`src/db/`)

SQLite via `DatabaseManager`. Schema initialized on first connect (`src/db/schema.py`). Two repositories:
- `ProjectRepository` — CRUD for projects table; statuses: `draft → generating → completed/failed`
- `JobRepository` — CRUD for jobs table

Pydantic models in `src/db/models.py` define `Project`, `Job`, `ProductMode` (lead_magnet | paid_ebook | bonus_content | authority), and status enums.

### Job queue (`src/jobs/queue.py`)

`JobQueue` + `JobWorker` provide a SQLite-backed, threading-locked background queue. `JobWorker` runs a daemon thread polling for pending jobs and calling a `process_fn` callback.

### Export (`src/export/`)

- `DocxGenerator` — renders manuscript.md + cover.png into a `.docx` via `python-docx`
- `PdfConverter` — shells out to `libreoffice --headless --convert-to pdf`
- `FileManager` — project directory layout helper; project artifacts live at `projects/{project_id}/`

### Cover (`src/cover/cover_generator.py`)

Calls AI to generate a text prompt description, then renders a simple cover image with Pillow (solid color bg + centered title text). Color is keyed to `product_mode`.

### Project file layout

```
projects/{project_id}/
  strategy.json
  outline.json
  toc.md
  manuscript.md
  manuscript.json
  qa_report.json
  chapters/{n}.md
  cover/cover.png
  cover/prompt.txt
  exports/ebook.docx
  exports/ebook.pdf
```

### Test fixtures

`conftest.py` at repo root provides shared fixtures: `test_db_path`, `temp_project_dir`, `mock_ai_client`, `sample_project_brief`, `sample_strategy`, `sample_outline`. All AI calls in tests use `mock_ai_client` — no real network calls expected in unit tests.
