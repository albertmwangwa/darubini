"""Shared data types used across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ObjectClass(str, Enum):
    """Objects Darubini detects in a thick smear field."""

    PARASITE = "parasite"
    WBC = "white_blood_cell"


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in pixel coordinates (x_min, y_min inclusive; x_max, y_max exclusive)."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError(f"Degenerate box: {self}")

    @property
    def width(self) -> float:
        """Box width in pixels."""
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        """Box height in pixels."""
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        """Box area in square pixels."""
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        """Box centre as (x, y)."""
        return ((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)

    def iou(self, other: BoundingBox) -> float:
        """Intersection over union with another box."""
        ix = max(0.0, min(self.x_max, other.x_max) - max(self.x_min, other.x_min))
        iy = max(0.0, min(self.y_max, other.y_max) - max(self.y_min, other.y_min))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Detection:
    """One detected object in a field image."""

    cls: ObjectClass
    box: BoundingBox
    score: float = 1.0
    source: str = "unknown"

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0, 1], got {self.score}")


@dataclass
class FieldResult:
    """Detections and quality findings for one microscope field."""

    field_id: str
    detections: list[Detection] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)

    @property
    def parasites(self) -> int:
        """Number of parasites detected in this field."""
        return sum(1 for d in self.detections if d.cls is ObjectClass.PARASITE)

    @property
    def wbcs(self) -> int:
        """Number of white blood cells detected in this field."""
        return sum(1 for d in self.detections if d.cls is ObjectClass.WBC)

    @property
    def usable(self) -> bool:
        """True when no blocking quality flag was raised."""
        return not any(flag.startswith("blocking:") for flag in self.quality_flags)
