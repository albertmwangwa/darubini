"""End-to-end analysis: quality check, segment, count, report."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from darubini.counting import WHO_DEFAULT, CountingProtocol, SlideCount, evaluate_slide
from darubini.quality import QualityThresholds, assess
from darubini.report import Report, render
from darubini.segmentation.base import Segmenter
from darubini.types import FieldResult


def load_image(path: Path) -> NDArray[np.uint8]:
    """Load an image file as an RGB uint8 array."""
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"), dtype=np.uint8)


@dataclass
class Pipeline:
    """Runs fields through quality checks and a segmenter, then counts the slide."""

    segmenter: Segmenter
    protocol: CountingProtocol = WHO_DEFAULT
    thresholds: QualityThresholds = field(default_factory=QualityThresholds)

    def analyse_field(self, image: NDArray[np.uint8], field_id: str) -> FieldResult:
        """Quality-check one field and, if usable, segment it."""
        quality = assess(image, self.thresholds)
        result = FieldResult(field_id=field_id, quality_flags=list(quality.flags))
        if quality.usable:
            result.detections = self.segmenter.segment(image)
        return result

    def analyse_slide(
        self, images: Iterable[tuple[str, NDArray[np.uint8]]], language: str = "en"
    ) -> tuple[list[FieldResult], SlideCount, Report]:
        """Analyse fields in order, stopping once the counting rule is satisfied."""
        fields: list[FieldResult] = []
        count = evaluate_slide(fields, self.protocol)
        for field_id, image in images:
            fields.append(self.analyse_field(image, field_id))
            count = evaluate_slide(fields, self.protocol)
            if count.is_positive is not None:
                break
        return fields, count, render(count, language)
