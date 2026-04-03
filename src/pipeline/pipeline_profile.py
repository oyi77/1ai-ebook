from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineProfile:
    product_mode: str
    strategy_extra_fields: dict[str, Any] = field(default_factory=dict)
    chapter_structure: str = "hook->intro->body->summary->transition"
    qa_rules: list[str] = field(default_factory=list)
    is_fiction: bool = False
    genre: str | None = None


PROFILES: dict[str, PipelineProfile] = {
    "lead_magnet": PipelineProfile(product_mode="lead_magnet"),
    "paid_ebook": PipelineProfile(product_mode="paid_ebook"),
    "bonus_content": PipelineProfile(product_mode="bonus_content"),
    "authority": PipelineProfile(product_mode="authority"),
}

PROFILES["novel"] = PipelineProfile(
    product_mode="novel",
    strategy_extra_fields={
        "protagonist": str,
        "antagonist": str,
        "setting": str,
        "central_conflict": str,
        "narrative_arc": str,
        "genre": str,
    },
    chapter_structure="scene→conflict→resolution→cliffhanger",
    qa_rules=["character_name_consistency"],
    is_fiction=True,
)


def get_profile(product_mode: str) -> PipelineProfile:
    """Return the profile for the given product_mode, or a default profile for unknown modes."""
    return PROFILES.get(product_mode, PipelineProfile(product_mode=product_mode))
