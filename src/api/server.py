import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from src.db.database import DatabaseManager
from src.db.repository import ProjectRepository
from src.db.schema import create_tables
from src.models.validation import ProjectInput
from src.pipeline.error_classifier import ErrorClassifier

try:
    from src.logger import get_logger, setup_logging
    setup_logging()
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig()
    logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("EBOOK_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "EBOOK_API_KEY environment variable must be set. "
        "See .env.example for setup instructions."
    )

DB_PATH = Path("data/ebook_generator.db")
PROJECTS_DIR = Path("projects")

# Module-level progress store keyed by project_id
_generation_progress: dict[int, dict] = {}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="AI Ebook Generator API", version="1.0")

# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    return response

# ---------------------------------------------------------------------------
# CORS Configuration
# ---------------------------------------------------------------------------

allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8501").split(",")
allowed_origins = [origin.strip() for origin in allowed_origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Static files + templates
_WEB_DIR = Path(__file__).parent.parent / "web"
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
_templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

ADMIN_KEY = os.environ.get("ADMIN_KEY", API_KEY)

_OMNIROUTE_DB = Path.home() / ".omniroute" / "storage.sqlite"

OMNIROUTE_COMBOS_FREE = [
    "auto/free-chat", "auto/free-fast", "auto/free-reasoning",
    "auto/free-coding", "auto/free-vision", "auto/free-llama",
]
OMNIROUTE_COMBOS_PAID = [
    "auto/pro-fast", "auto/pro-chat", "auto/pro-reasoning",
    "auto/pro-coding", "auto/pro-vision",
    "auto/best-fast", "auto/best-chat", "auto/best-reasoning",
    "auto/best-coding", "auto/best-vision",
    "auto/claude-sonnet", "auto/claude-opus",
    "auto/gpt", "auto/gemini", "auto/deepseek",
    "auto/reasoning", "auto/coding", "auto/vision",
]


def _get_available_models() -> list[str]:
    """Read combo names from OmniRoute DB, fall back to hardcoded list."""
    if _OMNIROUTE_DB.exists():
        try:
            conn = sqlite3.connect(str(_OMNIROUTE_DB))
            rows = conn.execute("SELECT name FROM combos ORDER BY name").fetchall()
            conn.close()
            if rows:
                return [r[0] for r in rows]
        except Exception:
            pass
    return OMNIROUTE_COMBOS_FREE + OMNIROUTE_COMBOS_PAID


def _sign(value: str) -> str:
    return hmac.new(ADMIN_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _check_admin(admin_session: str | None) -> bool:
    if not admin_session:
        return False
    try:
        val, sig = admin_session.rsplit(".", 1)
        return hmac.compare_digest(sig, _sign(val))
    except Exception as e:
        logger.warning("Admin session check failed", error=str(e))
        return False


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

class CreateProjectRequest(ProjectInput):
    pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return _templates.TemplateResponse("landing.html", {
        "request": request,
        "year": datetime.now().year,
    })


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, error: str = ""):
    return _templates.TemplateResponse("admin/login.html", {
        "request": request,
        "error": error,
    })


@app.post("/admin/login")
def admin_login(response: Response, password: str = Form(...)):
    if password == ADMIN_KEY:
        val = "admin"
        session = f"{val}.{_sign(val)}"
        resp = RedirectResponse(url="/admin", status_code=302)
        resp.set_cookie("admin_session", session, httponly=True, samesite="lax", max_age=86400 * 7)
        return resp
    return RedirectResponse(url="/admin/login?error=Invalid+password", status_code=302)


@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie("admin_session")
    return resp


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return RedirectResponse(url="/admin/login", status_code=302)
    repo = _get_repo()
    projects = repo.list_projects(limit=1000)
    stats = {
        "total": len(projects),
        "completed": sum(1 for p in projects if p["status"] == "completed"),
        "generating": sum(1 for p in projects if p["status"] == "generating"),
        "failed": sum(1 for p in projects if p["status"] == "failed"),
        "draft": sum(1 for p in projects if p["status"] == "draft"),
    }
    projects_dir = PROJECTS_DIR
    storage_mb = 0
    if projects_dir.exists():
        storage_mb = round(sum(f.stat().st_size for f in projects_dir.rglob("*") if f.is_file()) / 1024 / 1024, 1)
    from src.config import get_config
    cfg = get_config()
    system = {"model": cfg.default_model, "storage_mb": storage_mb}
    return _templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "page_title": "Dashboard",
        "active_page": "dashboard",
        "stats": stats,
        "recent": projects[:10],
        "system": system,
    })


@app.get("/admin/projects", response_class=HTMLResponse)
def admin_projects_page(request: Request, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return RedirectResponse(url="/admin/login", status_code=302)
    repo = _get_repo()
    projects = repo.list_projects(limit=500)
    return _templates.TemplateResponse("admin/projects.html", {
        "request": request,
        "page_title": "Projects",
        "active_page": "projects",
        "projects": projects,
    })


@app.get("/admin/projects/{project_id}", response_class=HTMLResponse)
def admin_project_detail(project_id: int, request: Request, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        return RedirectResponse(url="/admin/login", status_code=302)
    repo = _get_repo()
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")
    project_dir = PROJECTS_DIR / str(project_id)
    files = []
    if project_dir.exists():
        for f in sorted(project_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(project_dir)
                files.append({"name": str(rel), "size": f"{f.stat().st_size // 1024} KB", "path": str(rel)})
    qa = {}
    qa_file = project_dir / "qa_report.json"
    if qa_file.exists():
        import json as _json
        qa = _json.loads(qa_file.read_text())
    cover_exists = (project_dir / "cover" / "cover.png").exists()
    return _templates.TemplateResponse("admin/project_detail.html", {
        "request": request,
        "page_title": f"Project #{project_id}",
        "active_page": "projects",
        "project": project,
        "files": files,
        "qa": qa,
        "cover_exists": cover_exists,
    })


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request, admin_session: str | None = Cookie(default=None), message: str = ""):
    if not _check_admin(admin_session):
        return RedirectResponse(url="/admin/login", status_code=302)
    from src.config import get_config
    cfg = get_config()
    return _templates.TemplateResponse("admin/settings.html", {
        "request": request,
        "page_title": "Settings",
        "active_page": "settings",
        "config": cfg,
        "message": message,
        "available_models": _get_available_models(),
    })


@app.post("/admin/api/settings")
async def admin_save_settings(request: Request, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        raise HTTPException(status_code=401)
    from src.config import get_config, reload_config
    cfg = get_config()
    form = await request.form()
    for key, val in form.items():
        if hasattr(cfg, key):
            attr = getattr(cfg, key)
            try:
                if isinstance(attr, float):
                    setattr(cfg, key, float(val))
                elif isinstance(attr, int):
                    setattr(cfg, key, int(val))
                else:
                    setattr(cfg, key, str(val))
            except (ValueError, TypeError):
                pass
    cfg.save()
    reload_config()
    return RedirectResponse(url="/admin/settings?message=Saved+successfully", status_code=302)


@app.get("/admin/api/stats")
def admin_api_stats(admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        raise HTTPException(status_code=401)
    repo = _get_repo()
    projects = repo.list_projects(limit=1000)
    return {
        "total": len(projects),
        "completed": sum(1 for p in projects if p["status"] == "completed"),
        "generating": sum(1 for p in projects if p["status"] == "generating"),
        "failed": sum(1 for p in projects if p["status"] == "failed"),
        "draft": sum(1 for p in projects if p["status"] == "draft"),
    }


@app.delete("/admin/api/projects/{project_id}")
def admin_delete_project(project_id: int, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        raise HTTPException(status_code=401)
    repo = _get_repo()
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404)
    project_dir = PROJECTS_DIR / str(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    repo.delete_project(project_id)
    return {"deleted": project_id}


@app.get("/admin/api/projects/{project_id}/cover")
def admin_project_cover(project_id: int, admin_session: str | None = Cookie(default=None)):
    if not _check_admin(admin_session):
        raise HTTPException(status_code=401)
    cover = PROJECTS_DIR / str(project_id) / "cover" / "cover.png"
    if not cover.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(cover), media_type="image/png")


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
                "message": ErrorClassifier.classify(exc),
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
    result = {"project_id": project_id, "db_status": project["status"], **progress}
    if result.get("status") == "failed" and result.get("message"):
        result["message"] = ErrorClassifier.classify_str(result["message"])
    return result


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


def _validate_project_path(path: Path) -> Path:
    """
    Validate that a file path is within the PROJECTS_DIR.
    
    Resolves the path to absolute form (handling symlinks and ..) and ensures
    it's contained within PROJECTS_DIR to prevent path traversal attacks.
    
    Args:
        path: Path to validate
        
    Returns:
        Resolved absolute path
        
    Raises:
        HTTPException: 403 if path is outside PROJECTS_DIR
    """
    try:
        resolved_path = path.resolve()
        resolved_projects_dir = PROJECTS_DIR.resolve()
        
        if not resolved_path.is_relative_to(resolved_projects_dir):
            raise HTTPException(status_code=403, detail="Access denied")
        
        return resolved_path
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=403, detail="Access denied") from e


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
    
    # Validate path to prevent directory traversal attacks
    validated_path = _validate_project_path(file_path)

    if not validated_path.exists():
        raise HTTPException(status_code=404, detail=f"File {fmt} not found for project {project_id}")

    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "epub": "application/epub+zip",
    }
    return FileResponse(
        path=str(validated_path),
        media_type=media_types[fmt],
        filename=f"ebook-{project_id}.{fmt}",
    )
