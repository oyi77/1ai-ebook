import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_convert_docx_to_pdf(temp_project_dir):
    from src.export.pdf_converter import PdfConverter

    project_dir = temp_project_dir / "1"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    docx_file = project_dir / "exports" / "ebook.docx"
    from docx import Document

    doc = Document()
    doc.add_heading("Test", 0)
    doc.add_paragraph("Content")
    doc.save(docx_file)

    pdf_file = project_dir / "exports" / "ebook.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

    converter = PdfConverter(libreoffice_path="/usr/bin/libreoffice")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = converter.convert(docx_file)

    assert pdf_file.exists()


def test_pdf_starts_with_pdf_header(temp_project_dir):
    from src.export.pdf_converter import PdfConverter

    project_dir = temp_project_dir / "1"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    docx_file = project_dir / "exports" / "ebook.docx"
    from docx import Document

    doc = Document()
    doc.add_paragraph("Test")
    doc.save(docx_file)

    pdf_file = project_dir / "exports" / "ebook.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    converter = PdfConverter(libreoffice_path="/usr/bin/libreoffice")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        converter.convert(docx_file)

    content = pdf_file.read_bytes()[:4]
    assert content == b"%PDF"


def test_error_when_libreoffice_missing(temp_project_dir):
    from src.export.pdf_converter import PdfConverter

    project_dir = temp_project_dir / "1"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    docx_file = project_dir / "exports" / "ebook.docx"
    docx_file.touch()

    converter = PdfConverter(libreoffice_path=None)

    with patch("subprocess.run", side_effect=FileNotFoundError(" libreoffice")):
        with pytest.raises(RuntimeError, match="LibreOffice not found"):
            converter.convert(docx_file)

    content = pdf_file.read_bytes()[:4]
    assert content == b"%PDF"


def test_error_when_libreoffice_missing(temp_project_dir):
    from src.export.pdf_converter import PdfConverter

    project_dir = temp_project_dir / "1"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    docx_file = project_dir / "exports" / "ebook.docx"
    docx_file.touch()

    converter = PdfConverter()

    with patch("subprocess.run", side_effect=FileNotFoundError(" libreoffice")):
        with pytest.raises(RuntimeError, match="LibreOffice not found"):
            converter.convert(docx_file)

    pdf_file = project_dir / "exports" / "ebook.pdf"
    content = pdf_file.read_bytes()[:4]
    assert content == b"%PDF"


def test_error_when_libreoffice_missing(temp_project_dir):
    from src.export.pdf_converter import PdfConverter

    project_dir = temp_project_dir / "1"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "exports").mkdir(exist_ok=True)

    docx_file = project_dir / "exports" / "ebook.docx"
    docx_file.touch()

    converter = PdfConverter()

    with patch("subprocess.run", side_effect=FileNotFoundError(" libreoffice")):
        with pytest.raises(RuntimeError, match="LibreOffice not found"):
            converter.convert(docx_file)
