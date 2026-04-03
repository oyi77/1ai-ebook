import pytest
from src.pipeline.style_context import StyleContext


def test_to_prompt_block_basic():
    ctx = StyleContext(tone="conversational")
    block = ctx.to_prompt_block()
    assert "Tone: conversational" in block
    assert "Vocabulary level: general" in block


def test_to_prompt_block_with_characters():
    ctx = StyleContext(
        tone="dramatic",
        characters=[{"name": "Alice", "role": "protagonist", "description": "A brave hero"}],
    )
    block = ctx.to_prompt_block()
    assert "Alice" in block
    assert "protagonist" in block


def test_to_prompt_block_with_ending():
    ctx = StyleContext(tone="formal", previous_chapter_ending="And so it began.")
    block = ctx.to_prompt_block()
    assert "And so it began." in block


def test_to_prompt_block_no_empty_sections():
    ctx = StyleContext(tone="casual")
    block = ctx.to_prompt_block()
    # No characters section when empty
    assert "Characters:" not in block
    assert "Key terms" not in block
