"""Runtime settings, read from environment variables or a ``.env`` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Every field maps to a ``DARUBINI_`` or ``META_`` variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Meta Model API. The base URL and model ids are confirmed at hackathon kickoff;
    # nothing here is hard-coded to an endpoint we have not verified.
    meta_api_key: SecretStr | None = Field(default=None, alias="META_API_KEY")
    meta_api_base_url: str | None = Field(default=None, alias="META_API_BASE_URL")
    meta_segmentation_model: str = Field(default="sam-3", alias="META_SEGMENTATION_MODEL")
    meta_reasoning_model: str = Field(default="muse-spark", alias="META_REASONING_MODEL")
    meta_timeout_s: float = Field(default=60.0, alias="META_TIMEOUT_S")

    # Pipeline
    segmenter: str = Field(default="baseline", alias="DARUBINI_SEGMENTER")
    report_language: str = Field(default="en", alias="DARUBINI_REPORT_LANGUAGE")
    datasets_dir: Path = Field(default=Path("datasets"), alias="DARUBINI_DATASETS_DIR")

    @property
    def meta_enabled(self) -> bool:
        """True when both an API key and a base URL are configured."""
        return self.meta_api_key is not None and bool(self.meta_api_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
