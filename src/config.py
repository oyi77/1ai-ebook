from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


@dataclass
class PipelineConfig:
    # AI routing
    default_model: str = "qwen2.5:7b"
    outline_model: str = "qwen2.5:7b"
    strategy_model: str = "qwen2.5:7b"
    cover_model: str = "qwen2.5:7b"
    qa_model: str = "qwen2.5:7b"

    # Token budgets per section type
    tokens_intro: int = 600
    tokens_subchapter: int = 1000
    tokens_outro: int = 300
    tokens_strategy: int = 1000
    tokens_outline: int = 2000

    # QA thresholds
    qa_word_count_tolerance: float = 0.20  # ±20%
    qa_min_chapter_words: int = 300
    qa_max_retry_attempts: int = 3

    # Export
    docx_author: str = "AI Ebook Generator"
    cover_width: int = 1200
    cover_height: int = 1600
    cover_title_font_size: int = 80
    cover_watermark_font_size: int = 40

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8765
    ui_port: int = 8501

    # Model performance tracking
    model_success_threshold: float = 0.8  # min success rate to keep using a model
    model_min_samples: int = 5  # samples before switching

    @classmethod
    def load(cls) -> "PipelineConfig":
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**valid)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))


_config: PipelineConfig | None = None


def get_config() -> PipelineConfig:
    global _config
    if _config is None:
        _config = PipelineConfig.load()
    return _config


def reload_config() -> PipelineConfig:
    global _config
    _config = PipelineConfig.load()
    return _config
