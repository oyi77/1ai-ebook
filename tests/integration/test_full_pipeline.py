import pytest
from pathlib import Path


@pytest.mark.integration
def test_full_pipeline_integration(test_db_path, temp_project_dir):
    from src.pipeline.orchestrator import PipelineOrchestrator
    from src.db.repository import ProjectRepository
    from src.db.schema import create_tables
    from unittest.mock import MagicMock
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    create_tables(conn)
    conn.close()

    repo = ProjectRepository(test_db_path)
    project_id = repo.create_project(
        title="Test Integration Ebook",
        idea="How to test an ebook generation pipeline",
        product_mode="lead_magnet",
        chapter_count=2,
    )

    mock_client = MagicMock()
    mock_client.generate_structured = MagicMock(
        side_effect=[
            {
                "audience": "test",
                "pain_points": [],
                "promise": "test",
                "positioning": "test",
                "tone": "test",
                "goal": "test",
            },
            {
                "titles": ["Test"],
                "subtitles": ["Test"],
                "best_title": "Test",
                "best_subtitle": "Test",
                "chapters": [
                    {
                        "title": "Ch1",
                        "summary": "Sum",
                        "subchapters": [],
                        "estimated_word_count": 500,
                    }
                ],
            },
        ]
    )
    mock_client.generate_text = MagicMock(return_value="Chapter content here.")

    orchestrator = PipelineOrchestrator(
        db_path=test_db_path,
        projects_dir=temp_project_dir,
    )
    orchestrator.ai_client = mock_client

    progress_updates = []

    def on_progress(p, s):
        progress_updates.append((p, s))

    result = orchestrator.run_full_pipeline(project_id, on_progress=on_progress)

    assert result["status"] == "completed"
    assert len(progress_updates) > 0

    project_dir = temp_project_dir / str(project_id)
    assert (project_dir / "strategy.json").exists()
    assert (project_dir / "outline.json").exists()
    assert (project_dir / "manuscript.md").exists()

    # Verify DOCX TOC heading via DocxGenerator
    from src.export.docx_generator import DocxGenerator
    from docx import Document as DocxDocument

    docx_gen = DocxGenerator(projects_dir=temp_project_dir)
    docx_result = docx_gen.generate(project_id=project_id, title="Test")
    docx_path = docx_result["docx"]
    doc = DocxDocument(str(docx_path))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert "Table of Contents" in headings, "TOC heading missing from generated DOCX"


@pytest.mark.integration
def test_streamlit_form_submission(test_db_path, temp_project_dir):
    from src.pipeline.intake import ProjectIntake
    from src.db.schema import create_tables
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    create_tables(conn)
    conn.close()

    intake = ProjectIntake(test_db_path)
    project = intake.create_project(
        idea="Test Streamlit form with long enough idea",
        product_mode="paid_ebook",
        chapter_count=3,
    )

    assert project["id"] is not None
    assert project["status"] == "draft"
    assert project["product_mode"] == "paid_ebook"


@pytest.mark.integration
def test_export_includes_all_files(test_db_path, temp_project_dir):
    from src.export.export_orchestrator import ExportOrchestrator
    from src.db.repository import ProjectRepository
    from src.db.schema import create_tables
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    create_tables(conn)
    conn.close()

    repo = ProjectRepository(test_db_path)
    project_id = repo.create_project(
        title="Export Test",
        idea="Testing export functionality",
        product_mode="lead_magnet",
    )

    project_dir = temp_project_dir / str(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "chapters").mkdir(exist_ok=True)
    (project_dir / "chapters" / "1.md").write_text("# Chapter 1\n\nContent")
    (project_dir / "manuscript.md").write_text("# Chapter 1\n\nContent")
    (project_dir / "cover").mkdir(exist_ok=True)
    (project_dir / "outline.json").write_text('{"best_title": "Test"}')

    from PIL import Image

    (project_dir / "cover" / "cover.png").write_bytes(
        Image.new("RGB", (10, 10)).tobytes()
    )

    orchestrator = ExportOrchestrator(
        db_path=test_db_path,
        projects_dir=temp_project_dir,
    )

    result = orchestrator.export(project_id)

    assert result["status"] == "completed"
    exports_dir = project_dir / "exports"
    assert (exports_dir / "manifest.json").exists()
