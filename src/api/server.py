import base64
import json
import os
import threading
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.db.database import DatabaseManager
from src.db.repository import ProjectRepository
from src.db.schema import create_tables

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("EBOOK_API_KEY", "dev-key-change-me")
DB_PATH = Path("data/ebook_generator.db")
PROJECTS_DIR = Path("projects")

# Module-level progress store keyed by project_id
_generation_progress: dict[int, dict] = {}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="AI Ebook Generator API", version="1.0")


# ---------------------------------------------------------------------------
# DB helper — initialises schema on first call
# ---------------------------------------------------------------------------

def _get_repo() -> ProjectRepository:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = DatabaseManager(DB_PATH)
    with db.get_connection() as conn:
        create_tables(conn)
    return ProjectRepository(DB_PATH)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def verify_api_key(x_api_key: str = Header(...)) -> str:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    title: str
    idea: str
    product_mode: str = "lead_magnet"
    target_language: str = "en"
    chapter_count: int = 5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}


@app.get("/api/projects")
def list_projects():
    repo = _get_repo()
    return repo.list_projects()


@app.post("/api/projects")
def create_project(
    body: CreateProjectRequest,
    _key: str = Depends(verify_api_key),
):
    repo = _get_repo()
    project_id = repo.create_project(
        title=body.title,
        idea=body.idea,
        product_mode=body.product_mode,
        target_language=body.target_language,
        chapter_count=body.chapter_count,
    )
    project = repo.get_project(project_id)
    return project


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    repo = _get_repo()
    project = repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/api/projects/{project_id}/generate")
def generate_project(
    project_id: int,
    _key: str = Depends(verify_api_key),
):
    repo = _get_repo()
    project = repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Prevent double-starts
    current = _generation_progress.get(project_id, {})
    if current.get("status") == "running":
        return {"project_id": project_id, "message": "Generation already running"}

    _generation_progress[project_id] = {
        "status": "running",
        "progress": 0,
        "message": "Starting...",
    }

    def _run():
        try:
            from src.pipeline.orchestrator import PipelineOrchestrator

            orchestrator = PipelineOrchestrator(
                db_path=str(DB_PATH),
                projects_dir=str(PROJECTS_DIR),
            )

            def on_progress(pct: int, msg: str):
                _generation_progress[project_id] = {
                    "status": "running",
                    "progress": pct,
                    "message": msg,
                }

            orchestrator.run_full_pipeline(project_id, on_progress=on_progress)
            _generation_progress[project_id] = {
                "status": "completed",
                "progress": 100,
                "message": "Complete!",
            }
        except Exception as exc:
            _generation_progress[project_id] = {
                "status": "failed",
                "progress": 0,
                "message": str(exc),
            }

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"project_id": project_id, "message": "Generation started"}


@app.get("/api/projects/{project_id}/status")
def get_status(project_id: int):
    repo = _get_repo()
    project = repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    progress = _generation_progress.get(
        project_id,
        {"status": project["status"], "progress": 0, "message": ""},
    )
    return {"project_id": project_id, "db_status": project["status"], **progress}


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: int):
    repo = _get_repo()
    project = repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = PROJECTS_DIR / str(project_id)

    # Strategy
    strategy: dict = {}
    strategy_file = project_dir / "strategy.json"
    if strategy_file.exists():
        with open(strategy_file) as f:
            strategy = json.load(f)

    # Marketing kit
    marketing_kit: dict = {}
    mk_file = project_dir / "marketing_kit.json"
    if mk_file.exists():
        with open(mk_file) as f:
            marketing_kit = json.load(f)

    # Cover image
    cover_image_b64 = ""
    cover_file = project_dir / "cover" / "cover.png"
    if cover_file.exists():
        with open(cover_file, "rb") as f:
            cover_image_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Manuscript word count
    word_count = 0
    manuscript_json = project_dir / "manuscript.json"
    if manuscript_json.exists():
        with open(manuscript_json) as f:
            mdata = json.load(f)
        word_count = sum(
            ch.get("word_count", 0) for ch in mdata.get("chapters", [])
        )

    description = (
        marketing_kit.get("book_description")
        or strategy.get("goal")
        or ""
    )

    return {
        "project_id": project_id,
        "title": project.get("title", ""),
        "description": description,
        "audience": strategy.get("audience", ""),
        "tone": strategy.get("tone", ""),
        "keywords": marketing_kit.get("keywords", []),
        "ad_hooks": marketing_kit.get("ad_hooks", []),
        "suggested_price": marketing_kit.get("suggested_price", "$9.99"),
        "word_count": word_count,
        "cover_image_base64": cover_image_b64,
        "product_mode": project.get("product_mode", ""),
    }


@app.get("/api/projects/{project_id}/download/{fmt}")
def download_file(
    project_id: int,
    fmt: str,
    _key: str = Depends(verify_api_key),
):
    if fmt not in ("docx", "pdf", "epub"):
        raise HTTPException(status_code=400, detail="Unsupported format. Use docx, pdf, or epub.")

    project_dir = PROJECTS_DIR / str(project_id)
    file_path = project_dir / "exports" / f"ebook.{fmt}"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File {fmt} not found for project {project_id}")

    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "epub": "application/epub+zip",
    }
    return FileResponse(
        path=str(file_path),
        media_type=media_types[fmt],
        filename=f"ebook-{project_id}.{fmt}",
    )
