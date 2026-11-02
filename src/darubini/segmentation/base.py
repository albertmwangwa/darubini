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


SEGMENTERS = ("baseline", "sam3", "verified", "hybrid")


def get_segmenter(settings: Settings | None = None) -> Segmenter:
    """Build the segmenter named in settings.

    - ``baseline``: stain blobs, offline.
    - ``sam3``: SAM 3 text prompts for both classes.
    - ``verified``: parasite candidates kept by the verifier; stain-blob WBCs. Offline.
    - ``hybrid``: SAM 3 finds WBCs; the verifier keeps parasite candidates.
    """
    s = settings or get_settings()
    if s.segmenter not in SEGMENTERS:
        raise ValueError(f"unknown segmenter {s.segmenter!r}; use one of {', '.join(SEGMENTERS)}")
    from darubini.segmentation.baseline import BaselineSegmenter

    if s.segmenter == "baseline":
        return BaselineSegmenter()
    from darubini.segmentation.candidates import CandidateDetector

    if s.segmenter == "verified":
        from darubini.verifier import ParasiteVerifier, VerifiedSegmenter

        return VerifiedSegmenter(
            CandidateDetector(), ParasiteVerifier.load(s.verifier_path), wbc=BaselineSegmenter()
        )

    from darubini.meta.client import MetaModelClient
    from darubini.segmentation.sam import SamSegmenter

    client = MetaModelClient.from_settings(s)
    if s.segmenter == "sam3":
        return SamSegmenter.tuned(client, s.meta_segmentation_model)
    from darubini.segmentation.sam import TUNED_MIN_SCORES
    from darubini.types import ObjectClass
    from darubini.verifier import ParasiteVerifier, VerifiedSegmenter

    wbc = SamSegmenter(
        client,
        s.meta_segmentation_model,
        concepts={"cell": ObjectClass.WBC},
        class_min_score=TUNED_MIN_SCORES,
    )
    return VerifiedSegmenter(CandidateDetector(), ParasiteVerifier.load(s.verifier_path), wbc=wbc)
