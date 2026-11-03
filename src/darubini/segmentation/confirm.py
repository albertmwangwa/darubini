"""Two-stage parasite detection: SAM 3.1 box prompts confirm detector candidates.

Stage one proposes parasite candidates (green-absorption spots) and the verifier
scores them. Stage two sends each surviving candidate to SAM 3.1 as a box prompt,
16 per request, on the 1,024 px tile that contains it; SAM returns a confidence for
each object it segments. A candidate is kept when both stages accept it.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from darubini.meta.client import MAX_PROMPTED_OBJECTS, MetaModelClient
from darubini.segmentation.base import Segmenter
from darubini.segmentation.sam import Tile, drop_parasites_in_wbc, encode_jpeg, tile_grid
from darubini.types import BoundingBox, Detection, ObjectClass
from darubini.verifier import ParasiteVerifier, candidate_features

#: Tile side for confirmation requests; parasites are about 10 to 20 px across.
CONFIRM_TILE = 1024
#: Pixels added around each candidate box, so SAM sees the object's edge.
BOX_PAD = 2
#: Chosen on 20 NIH validation fields (docs/calibration/two_stage.md). SAM segments
#: nearly every candidate, so this filter adds little after the verifier.
CONFIRM_MIN_CONFIDENCE = 0.70


@dataclass
class BoxConfirmer:
    """Asks SAM 3.1 how confidently it segments the object inside each box."""

    client: MetaModelClient
    model: str
    tile: int = CONFIRM_TILE
    max_workers: int = 8

    def confidences(self, image: NDArray[np.uint8], boxes: list[BoundingBox]) -> list[float]:
        """SAM's confidence per box, 0.0 when SAM segments nothing there."""
        h, w = image.shape[:2]
        tiles = tile_grid(w, h, self.tile, 0)
        groups: dict[int, list[int]] = defaultdict(list)
        for i, box in enumerate(boxes):
            cx, cy = box.center
            n = next(
                n for n, (x0, y0, x1, y1) in enumerate(tiles) if x0 <= cx < x1 and y0 <= cy < y1
            )
            groups[n].append(i)
        jobs = [
            (tiles[t], idx[k : k + MAX_PROMPTED_OBJECTS])
            for t, idx in groups.items()
            for k in range(0, len(idx), MAX_PROMPTED_OBJECTS)
        ]
        scores = [0.0] * len(boxes)

        def run(job: tuple[Tile, list[int]]) -> None:
            (x0, y0, x1, y1), idx = job
            prompts = [
                (
                    int(boxes[i].x_min) - x0 - BOX_PAD,
                    int(boxes[i].y_min) - y0 - BOX_PAD,
                    int(boxes[i].x_max) - x0 + BOX_PAD,
                    int(boxes[i].y_max) - y0 + BOX_PAD,
                )
                for i in idx
            ]
            found = self.client.segment_objects(
                encode_jpeg(image[y0:y1, x0:x1]), prompts, (x1 - x0, y1 - y0), self.model
            )
            for k, i in enumerate(idx):
                if k in found:
                    scores[i] = found[k].score

        if jobs:
            with ThreadPoolExecutor(max_workers=max(1, min(self.max_workers, len(jobs)))) as pool:
                list(pool.map(run, jobs))
        return scores


class ConfirmedSegmenter:
    """Parasite candidates kept by the verifier *and* confirmed by SAM 3.1 box prompts.

    Only candidates the verifier accepts are sent to SAM, which keeps the cost to a
    few requests per field.
    """

    name = "confirmed"

    def __init__(
        self,
        candidates: Segmenter,
        verifier: ParasiteVerifier,
        confirmer: BoxConfirmer,
        wbc: Segmenter,
        min_confidence: float,
        verifier_threshold: float | None = None,
    ) -> None:
        self.candidates = candidates
        self.verifier = verifier
        self.confirmer = confirmer
        self.wbc = wbc
        self.min_confidence = min_confidence
        self.verifier_threshold = (
            verifier.threshold if verifier_threshold is None else verifier_threshold
        )

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Find WBCs, then parasites that pass the verifier and SAM confirmation."""
        wbcs = [d for d in self.wbc.segment(image) if d.cls is ObjectClass.WBC]
        parasites = [d for d in self.candidates.segment(image) if d.cls is ObjectClass.PARASITE]
        cands = [
            d for d in drop_parasites_in_wbc([*wbcs, *parasites]) if d.cls is ObjectClass.PARASITE
        ]
        proba = self.verifier.predict_proba(candidate_features(image, cands))
        passed = [
            (d, float(p)) for d, p in zip(cands, proba, strict=True) if p >= self.verifier_threshold
        ]
        conf = self.confirmer.confidences(image, [d.box for d, _ in passed])
        kept = [
            Detection(cls=d.cls, box=d.box, score=p, source=self.name)
            for (d, p), c in zip(passed, conf, strict=True)
            if c >= self.min_confidence
        ]
        return [*wbcs, *kept]
