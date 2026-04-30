"""Centralized settings loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

WhisperDevice = Literal["auto", "cuda", "cpu"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    youtube_data_api_key: str = Field(default="", alias="YOUTUBE_DATA_API_KEY")
    youtube_oauth_client_id: str = Field(default="", alias="YOUTUBE_OAUTH_CLIENT_ID")
    youtube_oauth_client_secret: str = Field(default="", alias="YOUTUBE_OAUTH_CLIENT_SECRET")
    youtube_oauth_token_path: Path = Field(
        default=Path("~/.config/jason/yt_token.json").expanduser(),
        alias="YOUTUBE_OAUTH_TOKEN_PATH",
    )

    own_channel_id: str = Field(default="", alias="OWN_CHANNEL_ID")

    tmdb_api_key: str = Field(default="", alias="TMDB_API_KEY")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    whisper_model: str = Field(default="large-v3", alias="WHISPER_MODEL")
    whisper_device: WhisperDevice = Field(default="auto", alias="WHISPER_DEVICE")

    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    duckdb_path: Path = Field(default=Path("./data/warehouse.duckdb"), alias="DUCKDB_PATH")

    log_level: LogLevel = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
