from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.ai_client import OmnirouteClient
from src.config import get_config
from src.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from src.pipeline.pipeline_profile import PipelineProfile


class QAEngine:
    def __init__(self, ai_client: OmnirouteClient | None = None, quality_level: str = "fast"):
        self.ai_client = ai_client
        self.quality_level = quality_level

    def run(
        self,
        manuscript: dict,
        outline: dict,
        strategy: dict | None = None,
        profile: PipelineProfile | None = None,
    ) -> dict:
        issues = []
        scores = {}

        structure_issues = self._check_structure(manuscript, outline)
        issues.extend(structure_issues)

        heading_issues = self._check_duplicate_headings(manuscript)
        issues.extend(heading_issues)

        scores["structure"] = 0.0 if (structure_issues or heading_issues) else 1.0

        word_count_issues = self._check_word_count(manuscript, outline)
        issues.extend(word_count_issues)
        scores["word_count"] = 0.0 if word_count_issues else 1.0

        if strategy:
            consistency_score = self._check_consistency(manuscript, strategy)
            if consistency_score is not None:
                scores["consistency"] = consistency_score

        # Prose quality check (per-chapter, English only)
        language = strategy.get("language", "en") if strategy else "en"
        prose_scores = []
        for ch in manuscript.get("chapters", []):
            content = ch.get("content", "")
            if content:
                pq = self._check_prose_quality(content, language)
                if not pq.get("skipped"):
                    prose_scores.append(pq["prose_quality"])
                    if pq["prose_quality"] < 0.8:
                        issues.append(f"Chapter {ch.get('chapter','?')} prose quality {pq['prose_quality']:.2f} below threshold")

        if prose_scores:
            scores["prose_quality"] = round(sum(prose_scores) / len(prose_scores), 3)

        from src.pipeline.content_safety import ContentSafety
        safety = ContentSafety()
        # Build a text sample from chapter titles for a lightweight check
        chapter_titles = " ".join(
            ch.get("title", "") for ch in manuscript.get("chapters", [])
        )
        safety_result = safety.check_content(chapter_titles)
        if not safety_result["passed"]:
            issues.extend(safety_result["issues"])
        scores["safety"] = 0.0 if safety_result["issues"] else 1.0

        passed = len(issues) == 0 and all(s >= 0.8 for s in scores.values())

        return {
            "passed": passed,
            "issues": issues,
            "scores": scores,
        }

    def _check_structure(self, manuscript: dict, outline: dict) -> list[str]:
        issues = []
        manuscript_titles = {
            ch.get("title", "").lower() for ch in manuscript.get("chapters", [])
        }
        outline_titles = {
            ch.get("title", "").lower() for ch in outline.get("chapters", [])
        }

        missing = outline_titles - manuscript_titles
        if missing:
            issues.append(f"Missing chapters: {', '.join(missing)}")

        return issues

    def _check_duplicate_headings(self, manuscript: dict) -> list[str]:
        issues = []
        for ch in manuscript.get("chapters", []):
            content = ch.get("content", "")
            if not content:
                continue
            chapter_num = ch.get("chapter", "?")
            headings = [line.strip() for line in content.splitlines() if line.startswith("#")]
            if len(headings) != len(set(headings)):
                dupes = [h for h in set(headings) if headings.count(h) > 1]
                issues.append(f"Chapter {chapter_num} has duplicate headings: {', '.join(dupes[:3])}")
        return issues

    def _check_word_count(self, manuscript: dict, outline: dict) -> list[str]:
        issues = []

        for i, chapter in enumerate(manuscript.get("chapters", []), 1):
            word_count = chapter.get("word_count", 0)

            outline_ch = (
                outline.get("chapters", [])[i - 1]
                if i <= len(outline.get("chapters", []))
                else {}
            )
            target = outline_ch.get("estimated_word_count", 500)

            tolerance = get_config().qa_word_count_tolerance
            if word_count < target * (1 - tolerance) or word_count > target * (
                1 + tolerance
            ):
                issues.append(
                    f"Chapter {i} word count ({word_count}) outside ±20% of target ({target})"
                )

        return issues

    def _check_prose_quality(self, chapter_content: str, language: str = "en") -> dict:
        """Heuristic prose quality check. English-only; returns skipped for other languages."""
        if language != "en":
            return {"prose_quality": None, "skipped": True, "reason": f"language={language}"}

        import re
        import math

        # 1. Banned phrases check
        banned = [
            "delve", "it's worth noting", "in conclusion", "as we explore",
            "in today's fast-paced world", "it is important to note",
            "furthermore", "moreover", "additionally", "needless to say",
        ]
        text_lower = chapter_content.lower()
        found_banned = [p for p in banned if p in text_lower]
        banned_penalty = min(len(found_banned) * 0.1, 0.3)  # max 0.3 penalty

        # 2. Sentence length uniformity (stddev of word counts per sentence)
        sentences = re.split(r'[.!?]+', chapter_content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        if len(sentences) >= 3:
            lengths = [len(s.split()) for s in sentences]
            mean = sum(lengths) / len(lengths)
            variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
            stddev = math.sqrt(variance)
            # Good writing has stddev >= 5; below 3 is suspiciously uniform
            uniformity_penalty = max(0, (5 - stddev) * 0.05) if stddev < 5 else 0
        else:
            uniformity_penalty = 0

        # 3. Abstract opener check
        first_200 = chapter_content[:200].lower()
        abstract_openers = ["in today's world", "in today's fast", "as we explore", "it is important"]
        has_abstract_opener = any(op in first_200 for op in abstract_openers)
        opener_penalty = 0.15 if has_abstract_opener else 0

        # 4. Hedge word density
        hedge_words = ["may", "might", "could", "perhaps", "possibly", "seemingly", "arguably"]
        hedge_count = sum(text_lower.count(f" {h} ") for h in hedge_words)
        hedge_density = hedge_count / max(len(sentences), 1)
        hedge_penalty = 0.1 if hedge_density > 0.08 else 0

        # 5. Architecture check (action steps + chapter summary)
        has_action_steps = "### action steps" in text_lower or "## action steps" in text_lower
        has_summary = "### chapter summary" in text_lower or "## chapter summary" in text_lower or "## summary" in text_lower
        architecture_penalty = (0 if has_action_steps else 0.1) + (0 if has_summary else 0.1)

        score = max(0.0, 1.0 - banned_penalty - uniformity_penalty - opener_penalty - hedge_penalty - architecture_penalty)

        return {
            "prose_quality": round(score, 3),
            "skipped": False,
            "details": {
                "banned_phrases_found": found_banned,
                "sentence_stddev": round(stddev if len(sentences) >= 3 else 0, 2),
                "has_abstract_opener": has_abstract_opener,
                "hedge_density": round(hedge_density, 3),
                "has_action_steps": has_action_steps,
                "has_summary": has_summary,
            }
        }

    def _check_consistency(self, manuscript: dict, strategy: dict) -> float | None:
        if self.quality_level != "thorough" or self.ai_client is None:
            return None
        chapters = manuscript.get("chapters", [])
        if not chapters:
            return None
        sample_titles = [f"- {ch.get('title', f'Chapter {i+1}')}" for i, ch in enumerate(chapters)]
        tone = strategy.get("tone", "conversational")
        prompt = (
            f"Rate the consistency of this ebook's chapter structure on a scale of 0.0 to 1.0.\n\n"
            f"Target tone: {tone}\nChapters ({len(chapters)} total):\n"
            + "\n".join(sample_titles)
            + '\n\nReturn only a JSON object: {"score": <float 0.0-1.0>, "reason": "<brief reason>"}'
        )
        try:
            result = self.ai_client.generate_structured(
                prompt=prompt,
                system_prompt="You are a book editor evaluating manuscript consistency. Be precise and concise.",
                response_schema={"score": float, "reason": str},
            )
            score = float(result.get("score", 0.0))
            return max(0.0, min(1.0, score))
        except Exception as e:
            logger.warning("Consistency check failed", error=str(e))
            return None

    def save_report(
        self, project_id: int, report: dict, projects_dir: Path | str = "projects"
    ) -> None:
        project_dir = Path(projects_dir) / str(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        with open(project_dir / "qa_report.json", "w") as f:
            json.dump(report, f, indent=2)
