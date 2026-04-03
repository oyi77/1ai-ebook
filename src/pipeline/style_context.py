from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class StyleContext:
    tone: str
    vocabulary_level: str = "general"  # "simple", "general", "technical"
    recurring_terms: list[str] = field(default_factory=list)
    characters: list[dict] = field(default_factory=list)  # populated for novel mode
    previous_chapter_ending: str = ""  # last 400 chars of previous chapter

    def to_prompt_block(self) -> str:
        lines = [
            f"Tone: {self.tone}",
            f"Vocabulary level: {self.vocabulary_level}",
        ]
        if self.recurring_terms:
            lines.append(f"Key terms to use consistently: {', '.join(self.recurring_terms)}")
        if self.characters:
            summaries = [
                f"{c['name']} ({c.get('role', 'character')}): {c.get('description', '')[:50]}"
                for c in self.characters
            ]
            lines.append(f"Characters: {'; '.join(summaries)}")
        if self.previous_chapter_ending:
            lines.append(f'Previous chapter ended: "{self.previous_chapter_ending}"')
        return "\n".join(lines)
