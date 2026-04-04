import json
from datetime import datetime
from pathlib import Path

from src.db.repository import ProjectRepository
from src.export.docx_generator import DocxGenerator
from src.export.epub_generator import EpubGenerator
from src.export.pdf_converter import PdfConverter


class ExportOrchestrator:
    def __init__(
        self,
        db_path: Path | str = "data/ebook_generator.db",
        projects_dir: Path | str = "projects",
    ):
        self.db_path = db_path
        self.projects_dir = projects_dir
        self.repo = ProjectRepository(db_path)

    def export(self, project_id: int) -> dict:
        project_dir = Path(self.projects_dir) / str(project_id)
        exports_dir = project_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)

        self._generate_docx(project_id, project_dir)
        self._generate_pdf(project_dir)
        self._generate_epub(project_id, project_dir)

        self._create_manifest(project_id, exports_dir)

        self.repo.update_project_status(project_id, "completed")

        return {
            "status": "completed",
            "project_id": project_id,
            "exports": {
                "docx": exports_dir / "ebook.docx",
                "pdf": exports_dir / "ebook.pdf",
                "epub": exports_dir / "ebook.epub",
            },
        }

    def _generate_docx(self, project_id: int, project_dir: Path) -> None:
        generator = DocxGenerator(projects_dir=project_dir.parent)
        title = "Ebook"

        outline_file = project_dir / "outline.json"
        if outline_file.exists():
            with open(outline_file) as f:
                outline = json.load(f)
                title = outline.get("best_title", "Ebook")

        result = generator.generate(project_id, title=title)
        return result

    def _generate_epub(self, project_id: int, project_dir: Path) -> None:
        try:
            title = "Ebook"
            outline_file = project_dir / "outline.json"
            if outline_file.exists():
                with open(outline_file) as f:
                    outline = json.load(f)
                    title = outline.get("best_title", "Ebook")

            generator = EpubGenerator(projects_dir=project_dir.parent)
            generator.generate(project_id, title=title)
        except Exception:
            pass

    def _generate_pdf(self, project_dir: Path) -> None:
        converter = PdfConverter()
        docx_file = project_dir / "exports" / "ebook.docx"

        if not docx_file.exists():
            raise FileNotFoundError(f"DOCX file not found: {docx_file}")

        try:
            converter.convert(docx_file)
        except RuntimeError as e:
            if "LibreOffice not found" in str(e):
                pass
            else:
                raise

    def _create_manifest(self, project_id: int, exports_dir: Path) -> None:
        manifest = {
            "project_id": project_id,
            "generated_at": datetime.now().isoformat(),
            "files": {},
        }

        for ext in ["docx", "pdf", "epub"]:
            file_path = exports_dir / f"ebook.{ext}"
            if file_path.exists():
                manifest["files"][ext] = {
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                }

        with open(exports_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
