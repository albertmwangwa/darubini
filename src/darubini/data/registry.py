"""Load and validate ``datasets/manifest.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Tier = Literal["core", "extended", "large"]
Kind = Literal["http", "git", "manual"]
TIER_ORDER: dict[str, int] = {"core": 0, "extended": 1, "large": 2}


class DatasetSpec(BaseModel):
    """One dataset entry in the manifest."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    country: str
    tier: Tier
    kind: Kind
    licence: str
    page: str
    role: str
    smear: str | None = None
    stain: str | None = None
    annotations: str | None = None
    creators: str | None = None
    url: str | None = None
    filename: str | None = None
    md5: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    size_bytes: int | None = None
    instructions: str | None = None
    doi: str | None = None
    citation: str | None = None
    capture: str | None = None

    @model_validator(mode="after")
    def _check_kind_fields(self) -> DatasetSpec:
        if self.kind in ("http", "git") and not self.url:
            raise ValueError(f"{self.id}: kind={self.kind} needs a url")
        if self.kind == "http" and not self.filename:
            raise ValueError(f"{self.id}: kind=http needs a filename")
        if self.kind == "manual" and not self.instructions:
            raise ValueError(f"{self.id}: kind=manual needs instructions")
        return self


class Manifest(BaseModel):
    """All datasets known to Darubini."""

    datasets: list[DatasetSpec]

    @model_validator(mode="after")
    def _unique_ids(self) -> Manifest:
        ids = [d.id for d in self.datasets]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate dataset ids: {sorted(dupes)}")
        return self

    def get(self, dataset_id: str) -> DatasetSpec:
        """Look up one dataset by id."""
        for d in self.datasets:
            if d.id == dataset_id:
                return d
        raise KeyError(dataset_id)

    def up_to_tier(self, tier: Tier) -> list[DatasetSpec]:
        """Datasets at or below a tier (core < extended < large)."""
        limit = TIER_ORDER[tier]
        return [d for d in self.datasets if TIER_ORDER[d.tier] <= limit]


def load_manifest(path: Path) -> Manifest:
    """Parse and validate a manifest file."""
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Manifest.model_validate(raw)
