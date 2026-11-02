"""Runtime settings, read from environment variables or a ``.env`` file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Every field maps to a ``DARUBINI_`` or ``META_`` variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Meta Model API: base URL https://api.meta.ai/v1 (see .env.example).
    meta_api_key: SecretStr | None = Field(default=None, alias="META_API_KEY")
    meta_api_base_url: str | None = Field(default=None, alias="META_API_BASE_URL")
    meta_segmentation_model: str = Field(default="sam-3.1", alias="META_SEGMENTATION_MODEL")
    meta_reasoning_model: str = Field(default="muse-spark-1.3", alias="META_REASONING_MODEL")
    meta_timeout_s: float = Field(default=60.0, alias="META_TIMEOUT_S")
    #: On-disk cache of segmentation replies; empty string disables it.
    meta_cache_dir: Path | None = Field(default=Path(".cache/meta"), alias="DARUBINI_CACHE_DIR")

    # Pipeline
    segmenter: str = Field(default="baseline", alias="DARUBINI_SEGMENTER")
    report_language: str = Field(default="en", alias="DARUBINI_REPORT_LANGUAGE")
    datasets_dir: Path = Field(default=Path("datasets"), alias="DARUBINI_DATASETS_DIR")
    verifier_path: Path = Field(
        default=Path("models/parasite_verifier.npz"), alias="DARUBINI_VERIFIER_PATH"
    )

    @field_validator("meta_cache_dir", mode="before")
    @classmethod
    def _empty_disables_cache(cls, value: object) -> object:
        return None if value in ("", None) else value

    @property
    def meta_enabled(self) -> bool:
        """True when both an API key and a base URL are configured."""
        return self.meta_api_key is not None and bool(self.meta_api_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
