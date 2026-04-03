import shutil
import subprocess
from pathlib import Path


class PdfConverter:
    def __init__(self, libreoffice_path: str | None = None):
        if libreoffice_path:
            self.libreoffice_path = libreoffice_path
        else:
            self.libreoffice_path = shutil.which("libreoffice") or shutil.which(
                "soffice"
            )

    def convert(self, docx_file: Path | str) -> dict:
        docx_file = Path(docx_file)

        if not self.libreoffice_path:
            raise RuntimeError("LibreOffice not found. Please install libreoffice.")

        output_dir = docx_file.parent

        try:
            result = subprocess.run(
                [
                    self.libreoffice_path,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(docx_file),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as e:
            raise RuntimeError("LibreOffice not found. Please install libreoffice.") from e

        if result.returncode != 0:
            raise RuntimeError(f"PDF conversion failed: {result.stderr}")

        pdf_file = output_dir / f"{docx_file.stem}.pdf"

        if not pdf_file.exists():
            raise RuntimeError(f"PDF file not created at {pdf_file}")

        return {"pdf": pdf_file}

    def check_installation(self) -> bool:
        return self.libreoffice_path is not None
