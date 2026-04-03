<!-- Generated: 2026-04-03 | Updated: 2026-04-03 -->

# ebook-generator

## Purpose
AI-powered ebook generation pipeline with a Streamlit multi-page frontend. Users submit an idea; the system runs sequential pipeline stages (strategy → outline → manuscript → QA → cover → export) backed by SQLite and a threaded job queue. All AI calls route through a local OmniRoute proxy.

## Key Files

| File | Description |
|------|-------------|
| `CLAUDE.md` | Developer guidance: commands, env setup, architecture overview |
| `pyproject.toml` | Project metadata, dependencies, pytest/ruff config |
| `.env.example` | Environment variable template (`OMNIROUTE_BASE_URL`, `APP_SECRET`, etc.) |
| `conftest.py` | Root pytest fixtures shared across all test suites |
| `pytest.ini` | Pytest configuration (mirrors `pyproject.toml` tool section) |
| `Dockerfile` / `docker-compose.yml` | Container build and service composition |
| `ebook-generator.service` | systemd service unit for production deployment |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | All application source code (see `src/AGENTS.md`) |
| `app/` | Streamlit frontend entry point and pages (see `app/AGENTS.md`) |
| `tests/` | Pytest test suites mirroring `src/` structure (see `tests/AGENTS.md`) |
| `docker/` | Container entrypoint script (see `docker/AGENTS.md`) |
| `projects/` | Runtime output — one subdirectory per generated ebook project |
| `data/` | Runtime job state persisted to disk |

## For AI Agents

### Working In This Directory
- Root-level files are config/infra only; application logic lives in `src/` and `app/`
- `projects/` and `data/` are runtime directories — never commit their contents
- All imports use the `src.*` namespace (e.g. `from src.pipeline.intake import ProjectIntake`)

### Testing Requirements
```bash
pytest              # full suite
pytest -m unit      # unit tests only
pytest -m integration
ruff check          # lint
```

### Common Patterns
- Pipeline stage classes accept an optional `ai_client` parameter for injection/mocking
- All pipeline stages write artifacts to `projects/{project_id}/` on disk
- SQLite DB path is passed explicitly; no global DB singleton

## Dependencies

### External
- `streamlit>=1.28` — frontend UI framework
- `openai>=1.3` — SDK used to call OmniRoute (OpenAI-compatible proxy)
- `python-docx>=1.1` — DOCX generation
- `Pillow>=10` — cover image rendering
- `pydantic>=2.5` — data models and validation
- `python-dotenv` — `.env` loading
- LibreOffice (system) — PDF conversion via subprocess

<!-- MANUAL: -->
