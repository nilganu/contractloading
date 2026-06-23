"""Application configuration loaded from environment + .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    openai_vision_model: str = Field(default="gpt-4o", alias="OPENAI_VISION_MODEL")
    # File-direct path (Responses API with input_file) — sends the whole
    # contract to the model in one shot, no rasterisation.
    openai_model_mini: str = Field(
        default="gpt-5.4-mini", alias="OPENAI_MODEL_MINI"
    )

    database_url: str = Field(default="sqlite:///./hotel.db", alias="DATABASE_URL")
    storage_dir: str = Field(default="./storage", alias="STORAGE_DIR")

    child_column_mode: str = Field(default="dynamic_review", alias="CHILD_COLUMN_MODE")
    preserve_child_positions: bool = Field(default=True, alias="PRESERVE_CHILD_POSITIONS")

    prompt_version: str = Field(default="v1", alias="PROMPT_VERSION")
    parser_version: str = Field(default="v1", alias="PARSER_VERSION")

    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="ALLOWED_ORIGINS",
    )

    @property
    def origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir).resolve()
        (p / "uploads").mkdir(parents=True, exist_ok=True)
        (p / "exports").mkdir(parents=True, exist_ok=True)
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
