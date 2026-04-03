import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the server at a temp DB and projects dir so tests are isolated."""
    db_file = tmp_path / "test.db"
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Patch module-level paths in server before importing app
    import src.api.server as server_mod
    monkeypatch.setattr(server_mod, "DB_PATH", db_file)
    monkeypatch.setattr(server_mod, "PROJECTS_DIR", projects_dir)
    # Clear progress state between tests
    server_mod._generation_progress.clear()
    return db_file, projects_dir


@pytest.fixture()
def client(tmp_db):
    from src.api.server import app
    return TestClient(app)


@pytest.fixture()
def authed_headers():
    return {"X-API-Key": "dev-key-change-me"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_list_projects_empty(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_project_requires_auth(client):
    resp = client.post(
        "/api/projects",
        json={"title": "Test", "idea": "An idea about Python"},
    )
    # No key → FastAPI returns 422 (missing header) or 401 (wrong key)
    assert resp.status_code in (401, 422)


def test_create_project(client, authed_headers):
    resp = client.post(
        "/api/projects",
        json={
            "title": "My Ebook",
            "idea": "A practical guide to machine learning",
            "product_mode": "lead_magnet",
            "target_language": "en",
            "chapter_count": 5,
        },
        headers=authed_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["title"] == "My Ebook"


def test_get_project(client, authed_headers):
    # Create first
    create_resp = client.post(
        "/api/projects",
        json={"title": "Get Test", "idea": "Testing retrieval"},
        headers=authed_headers,
    )
    assert create_resp.status_code == 200
    project_id = create_resp.json()["id"]

    # Retrieve
    resp = client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == project_id
    assert data["title"] == "Get Test"


def test_export_endpoint(client, authed_headers):
    # Create a project
    create_resp = client.post(
        "/api/projects",
        json={"title": "Export Test", "idea": "Export data for adforge"},
        headers=authed_headers,
    )
    assert create_resp.status_code == 200
    project_id = create_resp.json()["id"]

    resp = client.get(f"/api/projects/{project_id}/export")
    assert resp.status_code == 200
    data = resp.json()

    # Check all required keys are present
    required_keys = [
        "project_id", "title", "description", "audience", "tone",
        "keywords", "ad_hooks", "suggested_price", "word_count",
        "cover_image_base64", "product_mode",
    ]
    for key in required_keys:
        assert key in data, f"Missing key: {key}"

    assert data["project_id"] == project_id
    assert data["title"] == "Export Test"
    assert isinstance(data["keywords"], list)
    assert isinstance(data["ad_hooks"], list)


def test_download_not_found(client, authed_headers):
    resp = client.get(
        "/api/projects/999/download/docx",
        headers=authed_headers,
    )
    assert resp.status_code == 404
