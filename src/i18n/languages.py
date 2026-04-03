from __future__ import annotations

SUPPORTED_LANGUAGES: dict[str, dict] = {
    "en": {"name": "English", "rtl": False, "font_hint": "Calibri"},
    "id": {"name": "Indonesian (Bahasa Indonesia)", "rtl": False, "font_hint": "Calibri"},
    "ar": {"name": "Arabic", "rtl": True, "font_hint": "Arial"},
    "zh": {"name": "Chinese (Simplified)", "rtl": False, "font_hint": "SimSun"},
    "ja": {"name": "Japanese", "rtl": False, "font_hint": "MS Mincho"},
    "ko": {"name": "Korean", "rtl": False, "font_hint": "Malgun Gothic"},
    "hi": {"name": "Hindi", "rtl": False, "font_hint": "Mangal"},
    "he": {"name": "Hebrew", "rtl": True, "font_hint": "Arial"},
    "fa": {"name": "Persian (Farsi)", "rtl": True, "font_hint": "Arial"},
    "ur": {"name": "Urdu", "rtl": True, "font_hint": "Arial"},
    "es": {"name": "Spanish", "rtl": False, "font_hint": "Calibri"},
    "fr": {"name": "French", "rtl": False, "font_hint": "Calibri"},
    "de": {"name": "German", "rtl": False, "font_hint": "Calibri"},
    "pt": {"name": "Portuguese", "rtl": False, "font_hint": "Calibri"},
    "ru": {"name": "Russian", "rtl": False, "font_hint": "Times New Roman"},
    "tr": {"name": "Turkish", "rtl": False, "font_hint": "Calibri"},
}


def language_instruction(lang_code: str) -> str:
    """Return a system prompt instruction for the given language code."""
    meta = SUPPORTED_LANGUAGES.get(lang_code)
    if meta:
        name = meta["name"]
        return f"Write entirely in {name}. Use natural {name} grammar, idioms, and cultural context appropriate for the target audience."
    return f"Write entirely in the language with code '{lang_code}'."


def is_rtl(lang_code: str) -> bool:
    """Return True if the language is right-to-left."""
    return SUPPORTED_LANGUAGES.get(lang_code, {}).get("rtl", False)
