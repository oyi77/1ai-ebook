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
    from src.pipeline.style_guide import StyleGuide


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
        style_ctx: Optional[StyleContext] = None,
        style_guide: "StyleGuide | None" = None,
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

        if style_ctx is None:
            style_ctx = StyleContext.load_or_default(
                project_dir / "style_context.json",
                tone=strategy.get("tone", "conversational"),
            )

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
                style_guide=style_guide,
            )

            chapter_content = refiner.refine(chapter_content)

            # Extract terminology for voice consistency (skip if too short or AI unavailable)
            if len(chapter_content.split()) > 100:
                try:
                    term_result = self.ai_client.generate_structured(
                        prompt=(
                            f"From this chapter excerpt, identify 1-2 domain-specific terms or metaphors "
                            f"that should be used consistently throughout the ebook.\n\n"
                            f"{chapter_content[:800]}\n\n"
                            "Return JSON: {\"terms\": [{\"term\": \"string\", \"definition\": \"1 sentence\"}]}"
                        ),
                        system_prompt="You are an editor tracking terminology for consistency. Be concise.",
                        response_schema={"terms": list},
                        max_tokens=200,
                        temperature=0.3,
                    )
                    if isinstance(term_result, dict):
                        for t in term_result.get("terms", []):
                            if isinstance(t, dict) and t.get("term"):
                                style_ctx.established_terminology[t["term"]] = t.get("definition", "")
                except Exception:
                    pass  # term extraction is best-effort, never block chapter generation

            chapter_file = chapters_dir / f"{i}.md"
            with open(chapter_file, "w") as f:
                f.write(chapter_content)

            manuscript_content.append(
                f"\n\n---\n\n## Chapter {i}: {chapter.get('title', f'Chapter {i}')}\n\n"
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
            style_ctx.save(project_dir / "style_context.json")

        # Retry chapters that came out too short
        retry_fixes = self._retry_failed_chapters(
            chapters=chapters,
            chapters_dir=chapters_dir,
            strategy=strategy,
            language=language,
            style_ctx=style_ctx,
            profile=profile,
            manuscript_model=manuscript_model,
            style_guide=style_guide,
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
                        style_guide=style_guide,
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
        style_guide: "StyleGuide | None" = None,
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
                    style_guide=style_guide,
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
        style_guide: "StyleGuide | None" = None,
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
                style_guide=style_guide,
            )
            style_ctx.previous_chapter_ending = chapter_content[-400:]
            style_ctx.save(edition_dir / "style_context.json")
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

    def regenerate_chapter(self, chapter_idx: int, failure_context: str) -> str:
        """Re-generate a single chapter with QA failure context injected into prompt.

        Called by the post-QA retry loop in the orchestrator.
        """
        import structlog
        log = structlog.get_logger(__name__)
        log.info("regenerating_chapter", chapter_idx=chapter_idx, failure_context=failure_context[:100])

        # regenerate_chapter requires a project_id set on the instance;
        # callers must set self._project_id before calling this method.
        project_id = getattr(self, "_project_id", None)
        if project_id is None:
            raise RuntimeError("ManuscriptEngine._project_id must be set before calling regenerate_chapter")

        project_dir = self.projects_dir / str(project_id)
        outline_path = project_dir / "outline.json"
        strategy_path = project_dir / "strategy.json"
        style_ctx_path = project_dir / "style_context.json"

        import json as _json
        outline = _json.loads(outline_path.read_text()) if outline_path.exists() else {}
        strategy = _json.loads(strategy_path.read_text()) if strategy_path.exists() else {}
        style_ctx = (
            StyleContext.load_or_default(style_ctx_path, tone=strategy.get("tone", "conversational"))
            if style_ctx_path.exists()
            else StyleContext(tone=strategy.get("tone", "conversational"))
        )

        chapters = outline.get("chapters", [])
        if chapter_idx >= len(chapters):
            log.warning("chapter_idx_out_of_range", chapter_idx=chapter_idx)
            return ""

        chapter = chapters[chapter_idx]

        extra_instruction = (
            f"\n\nIMPORTANT: A previous attempt at this chapter failed quality review. "
            f"Specific issues to fix: {failure_context}\n"
            f"Please address these issues directly in your writing."
        )

        content = self._generate_chapter(
            chapter=chapter,
            chapter_num=chapter_idx + 1,
            total_chapters=len(chapters),
            strategy=strategy,
            style_ctx=style_ctx,
            extra_instruction=extra_instruction,
        )

        chapter_path = project_dir / "chapters" / f"{chapter_idx + 1}.md"
        chapter_path.write_text(content, encoding="utf-8")
        log.info("chapter_regenerated", chapter_idx=chapter_idx, words=len(content.split()))
        return content

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
        style_guide: "StyleGuide | None" = None,
        extra_instruction: str = "",
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

        style_guide_block = ""
        if style_guide is not None:
            tier = get_config().model_capability_tier
            style_guide_block = f"\n\n{style_guide.to_system_prompt_block(tier=tier)}"

        import os
        # Use caller-supplied model; fall back to env var, then hardcoded default.
        _default_model = os.getenv("EBOOK_MANUSCRIPT_MODEL", get_config().default_model)

        base_system = (
            f"You are an expert ebook writer. Tone: {tone}. Audience: {audience}.\n"
            f"Chapter {chapter_num}/{total_chapters}: {title}\nSummary: {summary}\n"
            f"{lang_instr}{style_block}{fiction_block}{style_guide_block}"
            f"{extra_instruction}\n"
            "Do NOT repeat the section heading in the body text. Write in full paragraphs."
        )

        parts: list[str] = []

        # 1. Hook + introduction (rotate hook type by chapter number)
        hook_types = {
            0: "a micro-anecdote (2-4 sentences placing a specific person in a concrete moment)",
            1: "a counterintuitive claim that challenges conventional wisdom",
            2: "a problem statement that makes the reader feel directly understood",
        }
        hook_instruction = hook_types[(chapter_num - 1) % 3]

        intro_target = max(300, chapter.get("estimated_word_count", 2000) * 0.15)
        intro_tokens = self.token_calibrator.calibrated_tokens("intro", int(intro_target))
        intro_model = manuscript_model or self.model_tracker.best_model("manuscript_intro", default=_default_model)
        _t0 = time.time()
        intro_prompt = (
            f"Write the opening for chapter '{title}'.\n"
            f"Hook type for this chapter: {hook_instruction}\n"
            "Include:\n"
            "- Hook paragraph using the specified hook type (NO heading, never start with 'In today's world' or 'As we explore')\n"
            "- Chapter promise: one sentence starting with 'By the end of this chapter, you'll...'\n"
            "- Introduction paragraph (what this chapter covers)\n"
            "Do NOT include the chapter title. Start directly with the hook."
        )
        intro = self.ai_client.generate_text(
            prompt=intro_prompt,
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
            if isinstance(sub, dict):
                sub_title = sub.get("title", str(sub))
                sub_summary = sub.get("summary", "")
            else:
                sub_title = str(sub)
                sub_summary = ""

            context = f"\nContext for this section: {sub_summary}" if sub_summary else ""

            terms_block = ""
            if style_ctx and style_ctx.established_terminology:
                terms = "; ".join(f"{k}: {v}" for k, v in list(style_ctx.established_terminology.items())[:5])
                terms_block = f"\nMaintain these established terms: {terms}"

            _t0 = time.time()
            section = self.ai_client.generate_text(
                prompt=(
                    f"Write the section '{sub_title}' for chapter '{title}'.\n"
                    f"{context}\n"
                    f"{terms_block}\n"
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
            # Strip any heading the AI added despite instructions, then prepend our own
            section_body = "\n".join(
                line for i, line in enumerate(section.strip().splitlines())
                if not (i == 0 and line.startswith("#"))
            )
            parts.append(f"\n\n### {sub_title}\n\n{section_body.strip()}")

        # 3. Summary + transition (structured enrichment when enabled)
        outro_target = max(150, chapter.get("estimated_word_count", 2000) * 0.10)
        outro_tokens = self.token_calibrator.calibrated_tokens("outro", int(outro_target))
        outro_model = manuscript_model or self.model_tracker.best_model("manuscript_outro", default=_default_model)

        if get_config().chapter_enrichment_enabled:
            enrichment_schema = {
                "chapter_summary_bullets": list,
                "callout_insight": str,
                "case_study": {"name": str, "conflict": str, "resolution": str},
                "action_steps": list,
                "bridge_sentence": str,
            }
            try:
                enrichment = self.ai_client.generate_structured(
                    prompt=(
                        f"Generate the closing elements for chapter '{title}'.\n"
                        f"Chapter context: {summary}\n"
                        "Provide:\n"
                        "- chapter_summary_bullets: list of 3-5 key takeaways (strings)\n"
                        "- callout_insight: one powerful key insight (1-2 sentences)\n"
                        "- case_study: a named composite person with conflict and resolution arc\n"
                        "- action_steps: list of 3 numbered actionable steps (imperative verbs)\n"
                        "- bridge_sentence: one sentence transitioning to the next chapter"
                    ),
                    system_prompt=base_system,
                    response_schema=enrichment_schema,
                    model=outro_model,
                    max_tokens=outro_tokens,
                    temperature=0.7,
                )

                if not isinstance(enrichment, dict):
                    raise ValueError("enrichment result is not a dict")

                # Render enrichment into markdown
                bullets = enrichment.get("chapter_summary_bullets", [])
                callout = enrichment.get("callout_insight", "")
                case_study = enrichment.get("case_study", {})
                action_steps = enrichment.get("action_steps", [])
                bridge = enrichment.get("bridge_sentence", "")

                enrichment_text = []
                if callout:
                    enrichment_text.append(f"\n\n> **Key Insight:** {callout}")
                if case_study and case_study.get("name"):
                    enrichment_text.append(
                        f"\n\n**Example: {case_study['name']}'s Story** — "
                        f"{case_study.get('conflict', '')} {case_study.get('resolution', '')}"
                    )
                if bullets:
                    enrichment_text.append("\n\n### Chapter Summary\n\n" + "\n".join(f"- {b}" for b in bullets))
                if action_steps:
                    steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(action_steps))
                    enrichment_text.append(f"\n\n### Action Steps\n\n{steps}")
                if bridge:
                    enrichment_text.append(f"\n\n{bridge}")

                parts.append("".join(enrichment_text))

            except Exception as e:
                # Fallback to plain outro on enrichment failure
                from src.logger import get_logger
                logger = get_logger(__name__)
                logger.warning("Chapter enrichment failed, using plain outro", chapter=title, error=str(e))
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
        else:
            # chapter_enrichment_enabled = False: use original outro
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
