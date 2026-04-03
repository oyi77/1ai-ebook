from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.ai_client import OmnirouteClient
from src.i18n.languages import language_instruction

if TYPE_CHECKING:
    from src.pipeline.pipeline_profile import PipelineProfile


class StrategyPlanner:
    def __init__(
        self,
        ai_client: OmnirouteClient | None = None,
        projects_dir: Path | str = "projects",
    ):
        self.ai_client = ai_client or OmnirouteClient()
        self.projects_dir = Path(projects_dir)

    def generate(self, project_brief: dict, profile: PipelineProfile | None = None) -> dict:
        product_mode = project_brief.get("product_mode", "lead_magnet")
        target_language = project_brief.get("target_language", "en")
        idea = project_brief.get("idea", "")

        system_prompt = self._build_system_prompt(product_mode, target_language)
        prompt = self._build_prompt(idea, target_language)

        response_schema = {
            "audience": str,
            "pain_points": list,
            "promise": str,
            "positioning": str,
            "tone": str,
            "goal": str,
        }

        if profile and getattr(profile, 'is_fiction', False):
            response_schema.update({
                "protagonist": str,
                "antagonist": str,
                "setting": str,
                "central_conflict": str,
                "narrative_arc": str,
                "genre": str,
            })

        strategy = self.ai_client.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            response_schema=response_schema,
        )

        self._save_strategy(project_brief["id"], strategy)
        return strategy

    def _build_system_prompt(self, product_mode: str, target_language: str = "en") -> str:
        mode_context = {
            "lead_magnet": "free content to build email list",
            "paid_ebook": "premium paid content",
            "bonus_content": "bonus material for existing customers",
            "authority": "thought leadership content",
            "novel": "fiction storytelling with characters and narrative arc",
        }
        return f"""You are an expert ebook strategist. Generate a strategy for an ebook that serves as {mode_context.get(product_mode, "content")}.

Return a JSON object with these fields:
- audience: Target audience description
- pain_points: List of key pain points the audience faces
- promise: The main promise/value proposition
- positioning: How the ebook positions itself in the market
- tone: Writing tone (e.g., conversational, authoritative, friendly)
- goal: The ebook's conversion goal

{language_instruction(target_language)}"""

    def _build_prompt(self, idea: str, target_language: str) -> str:
        return f"""Create a comprehensive strategy for an ebook with this idea: {idea}

Target language: {target_language}

Generate the strategy as JSON."""

    def _save_strategy(self, project_id: int, strategy: dict) -> None:
        project_dir = self.projects_dir / str(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        strategy_file = project_dir / "strategy.json"
        with open(strategy_file, "w") as f:
            json.dump(strategy, f, indent=2)
