"""Segmenter interface and factory."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from darubini.config import Settings, get_settings
from darubini.types import Detection


@runtime_checkable
class Segmenter(Protocol):
    """Anything that can find parasites and WBC in a field image."""

    name: str

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Return detections for one RGB field image."""
        ...


def get_segmenter(settings: Settings | None = None) -> Segmenter:
    """Build the segmenter named in settings (``baseline`` or ``sam3``)."""
    s = settings or get_settings()
    if s.segmenter == "baseline":
        from darubini.segmentation.baseline import BaselineSegmenter

        return BaselineSegmenter()
    if s.segmenter == "sam3":
        from darubini.meta.client import MetaModelClient
        from darubini.segmentation.sam import SamSegmenter

        return SamSegmenter(MetaModelClient.from_settings(s), model=s.meta_segmentation_model)
    raise ValueError(f"unknown segmenter {s.segmenter!r}; use 'baseline' or 'sam3'")
