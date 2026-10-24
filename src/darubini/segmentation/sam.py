"""SAM 3 segmenter using text concept prompts through the Meta Model API."""

from __future__ import annotations

import io

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from darubini.meta.client import MetaModelClient
from darubini.types import BoundingBox, Detection, ObjectClass

#: Text concepts sent to SAM 3, mapped to Darubini classes. Prompt wording is a
#: tunable: the evaluation compares variants (see docs/EVALUATION.md).
DEFAULT_CONCEPTS: dict[str, ObjectClass] = {
    "malaria parasite": ObjectClass.PARASITE,
    "white blood cell nucleus": ObjectClass.WBC,
}


def encode_jpeg(image: NDArray[np.uint8], quality: int = 92) -> bytes:
    """Encode an RGB array as JPEG bytes."""
    buf = io.BytesIO()
    Image.fromarray(image).convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class SamSegmenter:
    """Concept-prompted segmentation with a score threshold per class."""

    name = "sam3"

    def __init__(
        self,
        client: MetaModelClient,
        model: str,
        concepts: dict[str, ObjectClass] | None = None,
        min_score: float = 0.3,
    ) -> None:
        self.client = client
        self.model = model
        self.concepts = concepts or DEFAULT_CONCEPTS
        self.min_score = min_score

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Run SAM 3 on one field and convert instances to detections."""
        results = self.client.segment_concepts(
            encode_jpeg(image), list(self.concepts), model=self.model
        )
        detections: list[Detection] = []
        for r in results:
            cls = self.concepts.get(r.concept)
            if cls is None or r.score < self.min_score:
                continue
            x0, y0, x1, y1 = r.box_xyxy
            if x1 <= x0 or y1 <= y0:
                continue
            detections.append(
                Detection(cls=cls, box=BoundingBox(x0, y0, x1, y1), score=r.score, source=self.name)
            )
        return detections
