"""High-recall parasite candidates from local green-light absorption.

Giemsa-stained chromatin absorbs green light whatever the overall stain shade,
so a pixel's green value relative to its local background marks stained
material on pale UDOM smears and dark NIH smears alike. The detector keeps
small, strongly absorbing spots; most are platelets or debris, so its output
is meant for the parasite verifier, not for counting directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy import ndimage

from darubini.quality import field_of_view, to_gray
from darubini.types import BoundingBox, Detection, ObjectClass


@dataclass
class CandidateDetector:
    """Small spots that absorb green light more than their surroundings.

    Sizes are in working-size pixels (the long side scaled to ``working_side``).

    Attributes:
        min_absorption: keep pixels at least this much darker in green than the
            local background (0.2 means 20% darker).
        background_window: side of the median window that estimates the local
            background; must be well above a parasite's size.
        min_area: smallest spot kept.
        max_area: larger spots are WBC nuclei or clumps, not parasite candidates.

    """

    min_absorption: float = 0.2
    working_side: int = 1024
    background_window: int = 32
    min_area: int = 3
    max_area: int = 300
    name: str = "candidates"

    def absorption(self, image: NDArray[np.uint8]) -> tuple[NDArray[np.float32], float]:
        """Green absorption map at working size, and the scale back to image pixels."""
        h, w = image.shape[:2]
        k = min(1.0, self.working_side / max(h, w))
        if k < 1:
            size = (max(1, round(w * k)), max(1, round(h * k)))
            image = np.asarray(
                Image.fromarray(image[..., :3]).resize(size, Image.Resampling.LANCZOS)
            )
        green = image[..., 1].astype(np.float32)
        # The median of a quarter-size image is a fast, spot-free local background.
        step = 4
        coarse = ndimage.median_filter(
            green[::step, ::step], size=max(3, self.background_window // step)
        )
        background = ndimage.zoom(
            coarse, (green.shape[0] / coarse.shape[0], green.shape[1] / coarse.shape[1]), order=1
        )[: green.shape[0], : green.shape[1]]
        fov = field_of_view(to_gray(image))
        absorbed = np.where(fov, 1 - green / np.maximum(background, 1), 0)
        return absorbed.astype(np.float32), 1 / k

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Parasite candidates in one RGB field, in image coordinates."""
        absorbed, scale = self.absorption(image)
        mask = absorbed > self.min_absorption
        labels, n = ndimage.label(mask)
        if n == 0:
            return []
        areas = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))
        out = []
        for area, sl in zip(areas, ndimage.find_objects(labels), strict=True):
            if sl is None or not self.min_area <= area <= self.max_area:
                continue
            ys, xs = sl
            box = BoundingBox(xs.start * scale, ys.start * scale, xs.stop * scale, ys.stop * scale)
            out.append(Detection(ObjectClass.PARASITE, box, score=0.5, source=self.name))
        return out
