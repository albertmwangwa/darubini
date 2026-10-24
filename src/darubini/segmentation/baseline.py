"""Classical, offline baseline segmenter.

It finds dark, purple-stained blobs and splits them by size: large blobs are
WBC nuclei, small ones are parasite candidates. It needs no network and no
weights, so it powers tests, offline demos and the "before SAM 3" comparison
in the evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage

from darubini.quality import stain_mask
from darubini.types import BoundingBox, Detection, ObjectClass


@dataclass
class BaselineSegmenter:
    """Threshold + connected components + size rules.

    Attributes:
        min_parasite_area: smallest blob (px) kept as a parasite candidate.
        wbc_min_area: blobs at least this large (px) are treated as WBC.
        max_area: larger blobs are discarded as clumps or debris.

    """

    min_parasite_area: int = 12
    wbc_min_area: int = 400
    max_area: int = 20_000
    name: str = "baseline"

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Detect parasite candidates and WBC in one RGB field."""
        mask = ndimage.binary_opening(stain_mask(image), iterations=1)
        labels, n = ndimage.label(mask)
        if n == 0:
            return []
        areas = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))
        slices = ndimage.find_objects(labels)

        detections: list[Detection] = []
        for area, sl in zip(areas, slices, strict=True):
            if sl is None or area < self.min_parasite_area or area > self.max_area:
                continue
            ys, xs = sl
            box = BoundingBox(float(xs.start), float(ys.start), float(xs.stop), float(ys.stop))
            cls = ObjectClass.WBC if area >= self.wbc_min_area else ObjectClass.PARASITE
            detections.append(Detection(cls=cls, box=box, score=0.5, source=self.name))
        return detections
