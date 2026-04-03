from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.ai_client import OmnirouteClient

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
        scores["structure"] = 0.0 if structure_issues else 1.0

        word_count_issues = self._check_word_count(manuscript, outline)
        issues.extend(word_count_issues)
        scores["word_count"] = 0.0 if word_count_issues else 1.0

        if strategy:
            consistency_score = self._check_consistency(manuscript, strategy)
            scores["consistency"] = consistency_score

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

            tolerance = 0.2
            if word_count < target * (1 - tolerance) or word_count > target * (
                1 + tolerance
            ):
                issues.append(
                    f"Chapter {i} word count ({word_count}) outside ±20% of target ({target})"
                )

        return issues

    def _check_consistency(self, manuscript: dict, strategy: dict) -> float:
        if self.quality_level != "thorough" or self.ai_client is None:
            return 0.9
        chapters = manuscript.get("chapters", [])
        if not chapters:
            return 0.9
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
            score = float(result.get("score", 0.9))
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.9

    def save_report(
        self, project_id: int, report: dict, projects_dir: Path | str = "projects"
    ) -> None:
        project_dir = Path(projects_dir) / str(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        with open(project_dir / "qa_report.json", "w") as f:
            json.dump(report, f, indent=2)
