from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from src.ai_client import OmnirouteClient
from src.config import get_config
from src.i18n.languages import language_instruction
from src.pipeline.model_tracker import ModelTracker
from src.pipeline.style_context import StyleContext
from src.pipeline.token_calibrator import TokenCalibrator

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
        self.model_tracker = ModelTracker()
        self.token_calibrator = TokenCalibrator()

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
        manuscript_model: str | None = None,
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
                manuscript_model=manuscript_model,
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

        # Retry chapters that came out too short
        retry_fixes = self._retry_failed_chapters(
            chapters=chapters,
            chapters_dir=chapters_dir,
            strategy=strategy,
            language=language,
            style_ctx=style_ctx,
            profile=profile,
            manuscript_model=manuscript_model,
        )
        # Update chapter_metadata word counts for any retried chapters
        for chapter_num, new_content in retry_fixes.items():
            for meta in chapter_metadata:
                if meta["chapter"] == chapter_num:
                    meta["word_count"] = len(new_content.split())

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

    def _retry_failed_chapters(
        self,
        chapters: list[dict],
        chapters_dir: Path,
        strategy: dict,
        language: str,
        style_ctx,
        profile,
        manuscript_model: str | None,
        max_retries: int | None = None,
    ) -> dict[int, str]:
        """Re-generate chapters that are below the minimum word count. Returns {chapter_num: new_content}."""
        cfg = get_config()
        max_retries = max_retries or cfg.qa_max_retry_attempts
        fixes: dict[int, str] = {}

        for i, chapter in enumerate(chapters, 1):
            chapter_file = chapters_dir / f"{i}.md"
            if not chapter_file.exists():
                continue
            content = chapter_file.read_text()
            word_count = len(content.split())
            target = chapter.get("estimated_word_count", cfg.qa_min_chapter_words)
            min_words = int(target * (1 - cfg.qa_word_count_tolerance))
            if word_count >= min_words:
                continue

            for attempt in range(max_retries):
                retry_content = self._generate_chapter(
                    chapter=chapter,
                    strategy=strategy,
                    chapter_num=i,
                    total_chapters=len(chapters),
                    language=language,
                    style_ctx=style_ctx,
                    profile=profile,
                    manuscript_model=manuscript_model,
                )
                if len(retry_content.split()) >= min_words:
                    chapter_file.write_text(retry_content)
                    fixes[i] = retry_content
                    break

        return fixes

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
        manuscript_model: str | None = None,
    ) -> str:
        title = chapter.get("title", "")
        summary = chapter.get("summary", "")
        subchapters = chapter.get("subchapters", [])

        tone = strategy.get("tone", "conversational")
        audience = strategy.get("audience", "general")
        lang_instr = language_instruction(language)
        style_block = f"\n\nStyle Guide:\n{style_ctx.to_prompt_block()}" if style_ctx else ""
        fiction_block = (
            "\n\nFiction: show don't tell, use dialogue, sensory details, consistent character voice."
            if profile and getattr(profile, 'is_fiction', False) else ""
        )

        import os
        # Use caller-supplied model; fall back to env var, then hardcoded default.
        _default_model = os.getenv("EBOOK_MANUSCRIPT_MODEL", get_config().default_model)

        base_system = (
            f"You are an expert ebook writer. Tone: {tone}. Audience: {audience}.\n"
            f"Chapter {chapter_num}/{total_chapters}: {title}\nSummary: {summary}\n"
            f"{lang_instr}{style_block}{fiction_block}\n"
            "Do NOT repeat the section heading in the body text. Write in full paragraphs."
        )

        parts: list[str] = []

        # 1. Hook + introduction
        intro_target = max(300, chapter.get("estimated_word_count", 2000) * 0.15)
        intro_tokens = self.token_calibrator.calibrated_tokens("intro", int(intro_target))
        intro_model = manuscript_model or self.model_tracker.best_model("manuscript_intro", default=_default_model)
        _t0 = time.time()
        intro = self.ai_client.generate_text(
            prompt=(
                f"Write the opening for chapter '{title}'.\n"
                "Include:\n"
                "- Hook paragraph (question, surprising fact, or anecdote — NO heading)\n"
                "- Introduction paragraph (what this chapter covers)\n"
                "Do NOT include the chapter title. Start directly with the hook."
            ),
            system_prompt=base_system,
            model=intro_model,
            max_tokens=intro_tokens,
            temperature=0.7,
        )
        _latency = (time.time() - _t0) * 1000
        _success = len(intro.strip()) > 50
        _tokens = int(len(intro.split()) * 1.3)
        self.model_tracker.record(intro_model, "manuscript_intro", _success, _tokens, _latency)
        self.token_calibrator.record("intro", intro_tokens, len(intro.split()))
        parts.append(intro.strip())

        # 2. Each subchapter section
        sub_target = max(400, chapter.get("estimated_word_count", 2000) / max(len(subchapters), 1) * 0.7)
        sub_tokens = self.token_calibrator.calibrated_tokens("subchapter", int(sub_target))
        sub_model = manuscript_model or self.model_tracker.best_model("manuscript_subchapter", default=_default_model)
        for sub in subchapters:
            _t0 = time.time()
            section = self.ai_client.generate_text(
                prompt=(
                    f"Write the section '{sub}' for chapter '{title}'.\n"
                    "Write 3-5 substantial paragraphs covering the topic in depth.\n"
                    "Be specific, practical, and engaging. Do NOT include a heading — start directly with prose."
                ),
                system_prompt=base_system,
                model=sub_model,
                max_tokens=sub_tokens,
                temperature=0.7,
            )
            _latency = (time.time() - _t0) * 1000
            _success = len(section.strip()) > 50
            _tokens = int(len(section.split()) * 1.3)
            self.model_tracker.record(sub_model, "manuscript_subchapter", _success, _tokens, _latency)
            self.token_calibrator.record("subchapter", sub_tokens, len(section.split()))
            parts.append(f"\n\n### {sub}\n\n{section.strip()}")

        # 3. Summary + transition
        outro_target = max(150, chapter.get("estimated_word_count", 2000) * 0.10)
        outro_tokens = self.token_calibrator.calibrated_tokens("outro", int(outro_target))
        outro_model = manuscript_model or self.model_tracker.best_model("manuscript_outro", default=_default_model)
        _t0 = time.time()
        outro = self.ai_client.generate_text(
            prompt=(
                f"Write the closing for chapter '{title}'.\n"
                "Include:\n"
                "- Summary paragraph: 3-4 key takeaways from this chapter\n"
                "- Transition sentence: one sentence bridging to the next chapter"
            ),
            system_prompt=base_system,
            model=outro_model,
            max_tokens=outro_tokens,
            temperature=0.7,
        )
        _latency = (time.time() - _t0) * 1000
        _success = len(outro.strip()) > 50
        _tokens = int(len(outro.split()) * 1.3)
        self.model_tracker.record(outro_model, "manuscript_outro", _success, _tokens, _latency)
        self.token_calibrator.record("outro", outro_tokens, len(outro.split()))
        parts.append(f"\n\n{outro.strip()}")

        return "\n\n".join(parts)
