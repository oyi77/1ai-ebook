from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from src.ai_client import OmnirouteClient
from src.i18n.languages import language_instruction
from src.pipeline.style_context import StyleContext

if TYPE_CHECKING:
    from src.pipeline.pipeline_profile import PipelineProfile


class ManuscriptEngine:
    def __init__(
        self,
        ai_client: OmnirouteClient | None = None,
        projects_dir: Path | str = "projects",
    ):
        self.ai_client = ai_client or OmnirouteClient()
        self.projects_dir = Path(projects_dir)

    def generate(
        self,
        project_id: int,
        outline: dict,
        strategy: dict,
        on_progress: Optional[Callable[[int, str], None]] = None,
        profile: "PipelineProfile | None" = None,
        language: str = "en",
        quality_level: str = "fast",
        target_languages: list[str] | None = None,
    ) -> dict:
        from src.pipeline.refinement_engine import RefinementEngine

        self._quality_level = quality_level
        chapters = outline.get("chapters", [])
        project_dir = self.projects_dir / str(project_id)
        chapters_dir = project_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        manuscript_content = []
        chapter_metadata = []

        if on_progress:
            on_progress(0, "Starting manuscript generation...")

        style_ctx = StyleContext(tone=strategy.get("tone", "conversational"))

        if profile and getattr(profile, 'is_fiction', False):
            characters = []
            for role in ["protagonist", "antagonist"]:
                val = strategy.get(role, "")
                if val:
                    characters.append({"name": str(val), "role": role, "description": str(val)[:100]})
            if characters:
                style_ctx.characters = characters

        refiner = RefinementEngine(
            ai_client=self.ai_client,
            language=language,
            tone=strategy.get("tone", "conversational"),
            quality_level=quality_level,
        )

        for i, chapter in enumerate(chapters, 1):
            if on_progress:
                on_progress(
                    int((i - 1) / len(chapters) * 100),
                    f"Writing chapter {i}/{len(chapters)}...",
                )

            chapter_content = self._generate_chapter(
                chapter=chapter,
                strategy=strategy,
                chapter_num=i,
                total_chapters=len(chapters),
                language=language,
                style_ctx=style_ctx,
                profile=profile,
            )

            chapter_content = refiner.refine(chapter_content)

            chapter_file = chapters_dir / f"{i}.md"
            with open(chapter_file, "w") as f:
                f.write(chapter_content)

            manuscript_content.append(
                f"\n\n## {chapter.get('title', f'Chapter {i}')}\n\n"
            )
            manuscript_content.append(chapter_content)

            word_count = len(chapter_content.split())
            chapter_metadata.append(
                {
                    "chapter": i,
                    "title": chapter.get("title"),
                    "word_count": word_count,
                }
            )

            style_ctx.previous_chapter_ending = chapter_content[-400:]

        manuscript_file = project_dir / "manuscript.md"
        with open(manuscript_file, "w") as f:
            f.write("".join(manuscript_content))

        with open(project_dir / "manuscript.json", "w") as f:
            json.dump(
                {
                    "chapters": chapter_metadata,
                    "total_word_count": sum(c["word_count"] for c in chapter_metadata),
                },
                f,
                indent=2,
            )

        if on_progress:
            on_progress(100, "Manuscript generation complete!")

        editions: dict = {}
        if target_languages and len(target_languages) > 1:
            import logging
            for lang in target_languages[1:]:
                if on_progress:
                    on_progress(0, f"Generating {lang} edition...")
                try:
                    edition_result = self._generate_edition(
                        project_id=project_id,
                        outline=outline,
                        strategy=strategy,
                        language=lang,
                        profile=profile,
                        quality_level=getattr(self, '_quality_level', 'fast'),
                    )
                    editions[lang] = edition_result
                except Exception as e:
                    logging.warning(f"Failed to generate '{lang}' edition: {e}")
                    editions[lang] = {"error": str(e)}

        return {"manuscript": manuscript_file, "chapters": chapter_metadata, "editions": editions}

    def _generate_edition(
        self,
        project_id: int,
        outline: dict,
        strategy: dict,
        language: str,
        profile: "PipelineProfile | None" = None,
        quality_level: str = "fast",
    ) -> dict:
        from src.export.file_manager import FileManager
        fm = FileManager(self.projects_dir)
        edition_dir = fm.get_edition_dir(project_id, language)
        chapters_dir = edition_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        chapters = outline.get("chapters", [])
        style_ctx = StyleContext(tone=strategy.get("tone", "conversational"))
        manuscript_parts = []
        chapter_metadata = []

        for i, chapter in enumerate(chapters, 1):
            chapter_content = self._generate_chapter(
                chapter=chapter,
                strategy=strategy,
                chapter_num=i,
                total_chapters=len(chapters),
                language=language,
                profile=profile,
                style_ctx=style_ctx,
            )
            style_ctx.previous_chapter_ending = chapter_content[-400:]
            chapter_file = chapters_dir / f"{i}.md"
            chapter_file.write_text(chapter_content)
            manuscript_parts.append(f"\n\n## {chapter.get('title', f'Chapter {i}')}\n\n{chapter_content}")
            chapter_metadata.append({
                "chapter": i,
                "title": chapter.get("title"),
                "word_count": len(chapter_content.split()),
            })

        manuscript_file = edition_dir / "manuscript.md"
        manuscript_file.write_text("".join(manuscript_parts))
        return {"manuscript": str(manuscript_file), "chapters": chapter_metadata}

    def _generate_chapter(
        self,
        chapter: dict,
        strategy: dict,
        chapter_num: int,
        total_chapters: int,
        language: str = "en",
        style_ctx: StyleContext | None = None,
        profile: "PipelineProfile | None" = None,
    ) -> str:
        title = chapter.get("title", "")
        summary = chapter.get("summary", "")
        subchapters = chapter.get("subchapters", [])

        system_prompt = f"""You are an expert ebook writer. Write chapter {chapter_num} of {total_chapters} chapters.

Tone: {strategy.get("tone", "conversational")}
Audience: {strategy.get("audience", "general")}

Chapter title: {title}
Chapter summary: {summary}
Subchapters to cover: {", ".join(subchapters)}

Structure each chapter as follows:
- Hook (1 paragraph): open with a question, surprising fact, or brief anecdote to engage the reader
- Introduction (1 paragraph): overview of what this chapter covers
- Body sections: one section per subchapter, each with a markdown subheading (##) and 2-4 paragraphs
- Summary (1 paragraph): key takeaways from this chapter
- Transition (1 sentence): bridge to the next chapter's topic

{language_instruction(language)}"""

        if style_ctx is not None:
            system_prompt += f"\n\nStyle Guide:\n{style_ctx.to_prompt_block()}"

        if profile and getattr(profile, 'is_fiction', False):
            system_prompt += (
                "\n\nFiction Writing Guidelines:\n"
                "- Show don't tell: reveal character through action and dialogue, not description\n"
                "- Use dialogue to advance plot and reveal character\n"
                "- Include sensory details (sight, sound, smell, touch, taste)\n"
                "- Maintain consistent character voice and mannerisms\n"
                "- End each chapter with a hook that compels the reader to continue"
            )

        prompt = f"Write chapter {chapter_num}: {title}"

        content = self.ai_client.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=2000,
            temperature=0.7,
        )

        return content
