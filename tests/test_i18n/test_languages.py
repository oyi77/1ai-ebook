import pytest
from src.i18n.languages import SUPPORTED_LANGUAGES, language_instruction, is_rtl


def test_supported_languages_count():
    assert len(SUPPORTED_LANGUAGES) >= 16


def test_indonesian_included():
    assert "id" in SUPPORTED_LANGUAGES
    assert "Indonesian" in SUPPORTED_LANGUAGES["id"]["name"]


def test_rtl_languages():
    for code in ["ar", "he", "fa", "ur"]:
        assert is_rtl(code) is True, f"{code} should be RTL"


def test_non_rtl_languages():
    for code in ["en", "id", "es", "fr", "de"]:
        assert is_rtl(code) is False, f"{code} should not be RTL"


def test_language_instruction_english():
    instr = language_instruction("en")
    assert "English" in instr


def test_language_instruction_indonesian():
    instr = language_instruction("id")
    assert "Indonesian" in instr


def test_language_instruction_unknown():
    instr = language_instruction("xx")
    assert "xx" in instr


def test_is_rtl_unknown_code():
    assert is_rtl("xx") is False
