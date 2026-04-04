from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import PipelineConfig


@dataclass
class StyleGuide:
    voice_anchor: str = ""
    pov: str = "second-person"
    banned_phrases: list = field(default_factory=lambda: [
        "delve", "it's worth noting", "in conclusion", "as we explore",
        "in today's fast-paced world", "it is important to note",
        "furthermore", "moreover", "additionally", "it is worth noting",
        "let us explore", "needless to say", "as mentioned earlier",
    ])
    sentence_length_range: tuple = field(default_factory=lambda: (12, 18))
    tone_adjectives: list = field(default_factory=list)
    gold_standard_paragraph: str = ""

    def to_system_prompt_block(self, tier: str = "medium") -> str:
        """Return a formatted style constraint block for injection into system prompts.

        tier: 'small' = minimal (banned phrases + tone only)
               'medium' = standard
               'large' = full including gold standard paragraph
        """
        lines = ["## Style Guide (MUST FOLLOW)"]

        # Always include banned phrases
        lines.append(f"BANNED phrases (never use): {', '.join(self.banned_phrases[:8])}")

        # Always include POV
        lines.append(f"POV: {self.pov} ('you', not 'one' or 'the reader')")

        if tier in ("medium", "large"):
            if self.tone_adjectives:
                lines.append(f"Tone: {', '.join(self.tone_adjectives)}")
            if self.voice_anchor:
                lines.append(f"Reader profile: {self.voice_anchor}")
            lines.append(f"Sentence length: avg {self.sentence_length_range[0]}–{self.sentence_length_range[1]} words; vary rhythm (short punchy sentences after long ones)")

        if tier == "large" and self.gold_standard_paragraph:
            lines.append(f"\nVoice reference paragraph:\n{self.gold_standard_paragraph}")

        lines.append("NEVER start chapters with 'In today's world', 'As we explore', or 'It is important to note'.")
        return "\n".join(lines)

    def detect_violations(self, text: str) -> list[str]:
        """Return list of banned phrases found in text."""
        text_lower = text.lower()
        return [p for p in self.banned_phrases if p.lower() in text_lower]
