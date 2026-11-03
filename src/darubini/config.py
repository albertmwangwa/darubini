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
    meta_voice_model: str = Field(default="muse-voice-transcribe-1.0", alias="META_VOICE_MODEL")
    meta_timeout_s: float = Field(default=60.0, alias="META_TIMEOUT_S")
    # Muse Spark Open (open weights) on any OpenAI-compatible host, e.g. Baseten
    # https://inference.baseten.co/v1, Fireworks, Together, or a local vLLM server.
    open_weights_base_url: str | None = Field(default=None, alias="OPEN_WEIGHTS_BASE_URL")
    open_weights_api_key: SecretStr | None = Field(default=None, alias="OPEN_WEIGHTS_API_KEY")
    open_weights_model: str = Field(
        default="meta-models/muse-spark-open", alias="OPEN_WEIGHTS_MODEL"
    )
    #: On-disk cache of segmentation replies; empty string disables it.
    meta_cache_dir: Path | None = Field(default=Path(".cache/meta"), alias="DARUBINI_CACHE_DIR")

    # Pipeline
    #: "verified" is the best detector that needs no API key; set "hybrid" with a key.
    segmenter: str = Field(default="verified", alias="DARUBINI_SEGMENTER")
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

    @property
    def open_weights_enabled(self) -> bool:
        """True when an OpenAI-compatible host for Muse Spark Open is configured."""
        return bool(self.open_weights_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
