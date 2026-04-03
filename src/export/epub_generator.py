try:
    from ebooklib import epub
except ImportError as e:
    raise ImportError(
        "ebooklib is required for EPUB export. Install it with: pip install ebooklib"
    ) from e

import re
from pathlib import Path


CSS = """\
body { font-family: Georgia, serif; margin: 2em; line-height: 1.6; }
h1 { color: #333; font-size: 2em; margin-top: 1em; }
h2 { color: #555; font-size: 1.5em; margin-top: 0.8em; }
p { margin: 0.5em 0; }
strong { font-weight: bold; }
em { font-style: italic; }
"""


def _md_to_html(text: str) -> str:
    """Convert basic markdown text block to HTML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Escape any remaining HTML-unsafe chars that weren't from markdown
    # (title lines handled separately, so this is body text only)
    paragraphs = re.split(r"\n{2,}", text.strip())
    parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Don't double-wrap heading lines that might sneak in
        if para.startswith("<h"):
            parts.append(para)
        else:
            parts.append(f"<p>{para}</p>")
    return "\n".join(parts)


def _parse_manuscript(content: str) -> list[dict]:
    """Split manuscript on ## chapter boundaries. Returns list of {title, body}."""
    chapters = []
    current_title = None
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                chapters.append({"title": current_title, "body": "\n".join(current_lines)})
            current_title = line[3:].strip()
            current_lines = []
        else:
            if current_title is not None:
                current_lines.append(line)
            # Lines before first ## are ignored (preamble / # title)

    if current_title is not None:
        chapters.append({"title": current_title, "body": "\n".join(current_lines)})

    return chapters


class EpubGenerator:
    def __init__(self, projects_dir: Path | str = "projects"):
        self.projects_dir = Path(projects_dir)

    def generate(
        self,
        project_id: int,
        title: str = "Ebook",
        subtitle: str = "",
        author: str = "Author",
        language: str = "en",
    ) -> dict:
        project_dir = self.projects_dir / str(project_id)
        exports_dir = project_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)

        book = epub.EpubBook()
        book.set_title(title)
        book.set_language(language)
        book.add_author(author)

        # CSS
        style = epub.EpubItem(
            uid="style",
            file_name="style/main.css",
            media_type="text/css",
            content=CSS.encode(),
        )
        book.add_item(style)

        # Cover image
        cover_file = project_dir / "cover" / "cover.png"
        if cover_file.exists():
            try:
                cover_data = cover_file.read_bytes()
                book.set_cover("cover.png", cover_data)
            except Exception:
                pass

        # Parse manuscript into chapters
        manuscript_file = project_dir / "manuscript.md"
        chapter_items: list[epub.EpubHtml] = []

        if manuscript_file.exists():
            content = manuscript_file.read_text(encoding="utf-8")
            chapters = _parse_manuscript(content)
        else:
            chapters = []

        if not chapters:
            # Fallback: single title page
            chapters = [{"title": title, "body": subtitle or ""}]

        for idx, ch in enumerate(chapters, start=1):
            ch_title = ch["title"]
            ch_body_html = _md_to_html(ch["body"])

            html_content = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<!DOCTYPE html>'
                f"<html xmlns=\"http://www.w3.org/1999/xhtml\">"
                f"<head>"
                f'<title>{ch_title}</title>'
                f'<link rel="stylesheet" type="text/css" href="../style/main.css"/>'
                f"</head>"
                f"<body>"
                f"<h2>{ch_title}</h2>"
                f"{ch_body_html}"
                f"</body></html>"
            )

            item = epub.EpubHtml(
                title=ch_title,
                file_name=f"chapter_{idx:03d}.xhtml",
                lang=language,
            )
            item.content = html_content.encode("utf-8")
            item.add_item(style)
            book.add_item(item)
            chapter_items.append(item)

        # TOC and navigation
        book.toc = tuple(
            epub.Link(item.file_name, item.title, f"ch{i}")
            for i, item in enumerate(chapter_items, start=1)
        )
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        book.spine = ["nav"] + chapter_items

        epub_path = exports_dir / "ebook.epub"
        epub.write_epub(str(epub_path), book)

        return {"epub": epub_path}
