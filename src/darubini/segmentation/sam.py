"""SAM 3 segmenter using text concept prompts through the Meta Model API.

Parasites are small (about 40 px in a 4,032 px phone photo), so a field can be
cut into overlapping tiles, each sent at full resolution. Duplicates from the
overlaps are merged afterwards.
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from darubini.meta.client import MetaModelClient
from darubini.types import BoundingBox, Detection, ObjectClass

#: Text concepts sent to SAM 3, mapped to Darubini classes. Prompt wording is a
#: tunable: the evaluation compares variants (see docs/EVALUATION.md).
DEFAULT_CONCEPTS: dict[str, ObjectClass] = {
    "small dark purple dot": ObjectClass.PARASITE,
    "cell": ObjectClass.WBC,
}
#: Tuned settings from the NIH tuning-split sweeps (docs/calibration/sam_sweep_*.md):
#: parasites need 1,024 px tiles; WBCs are best found on the whole field.
TUNED_TILE_SIZE = 1024
TUNED_TILE_CLASSES = frozenset({ObjectClass.PARASITE})
TUNED_MIN_SCORES: dict[ObjectClass, float] = {ObjectClass.PARASITE: 0.1, ObjectClass.WBC: 0.7}


Tile = tuple[int, int, int, int]


def _starts(length: int, tile: int, overlap: int) -> list[int]:
    if length <= tile:
        return [0]
    step = max(1, tile - overlap)
    starts = list(range(0, length - tile, step))
    return [*starts, length - tile]


def tile_grid(width: int, height: int, tile: int, overlap: int) -> list[Tile]:
    """Overlapping ``(x0, y0, x1, y1)`` tiles that cover the whole image."""
    return [
        (x, y, min(x + tile, width), min(y + tile, height))
        for y in _starts(height, tile, overlap)
        for x in _starts(width, tile, overlap)
    ]


def _overlap(a: BoundingBox, b: BoundingBox) -> tuple[float, float]:
    """IoU and intersection over the smaller box."""
    iw = min(a.x_max, b.x_max) - max(a.x_min, b.x_min)
    ih = min(a.y_max, b.y_max) - max(a.y_min, b.y_min)
    if iw <= 0 or ih <= 0:
        return 0.0, 0.0
    inter = iw * ih
    return inter / (a.area + b.area - inter), inter / min(a.area, b.area)


def merge_duplicates(
    detections: list[Detection], iou: float = 0.5, containment: float = 0.7
) -> list[Detection]:
    """Greedy per-class suppression, highest score first.

    A box is dropped if it overlaps a kept box by ``iou``, or if most of it lies
    inside one (an object cut in half at a tile edge).
    """
    kept: list[Detection] = []
    for d in sorted(detections, key=lambda d: d.score, reverse=True):
        if not any(
            k.cls is d.cls and ((o := _overlap(k.box, d.box))[0] >= iou or o[1] >= containment)
            for k in kept
        ):
            kept.append(d)
    return kept


def drop_parasites_in_wbc(detections: list[Detection]) -> list[Detection]:
    """Drop parasite detections centred inside a white blood cell.

    A WBC nucleus looks like a large purple dot, so dot prompts also fire on it;
    in a thick film a parasite is not counted inside a WBC.
    """
    wbcs = [d.box for d in detections if d.cls is ObjectClass.WBC]

    def inside_wbc(d: Detection) -> bool:
        x, y = d.box.center
        return any(b.x_min <= x <= b.x_max and b.y_min <= y <= b.y_max for b in wbcs)

    return [d for d in detections if d.cls is not ObjectClass.PARASITE or not inside_wbc(d)]


def encode_jpeg(image: NDArray[np.uint8], quality: int = 92) -> bytes:
    """Encode an RGB array as JPEG bytes."""
    buf = io.BytesIO()
    Image.fromarray(image).convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


class SamSegmenter:
    """Concept-prompted segmentation with a score threshold per class.

    With ``tile_size`` set, the field is cut into overlapping tiles of that many
    pixels for concepts of the classes in ``tile_classes`` (all classes when None);
    other concepts run on the whole field. Requests run in parallel.
    """

    name = "sam3"

    def __init__(
        self,
        client: MetaModelClient,
        model: str,
        concepts: dict[str, ObjectClass] | None = None,
        min_score: float = 0.3,
        tile_size: int | None = None,
        tile_overlap: int = 128,
        max_workers: int = 8,
        tile_classes: frozenset[ObjectClass] | None = None,
        class_min_score: dict[ObjectClass, float] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.concepts = concepts or DEFAULT_CONCEPTS
        self.min_score = min_score
        self.tile_size = tile_size
        self.tile_overlap = tile_overlap
        self.max_workers = max_workers
        self.tile_classes = tile_classes
        self.class_min_score = class_min_score or {}

    @classmethod
    def tuned(cls, client: MetaModelClient, model: str) -> SamSegmenter:
        """Build with the prompts, tiling and thresholds chosen by the tuning sweeps."""
        return cls(
            client,
            model,
            tile_size=TUNED_TILE_SIZE,
            tile_classes=TUNED_TILE_CLASSES,
            class_min_score=TUNED_MIN_SCORES,
        )

    def tiles(self, image: NDArray[np.uint8]) -> list[Tile]:
        """Tiles this segmenter will send for ``image``."""
        h, w = image.shape[:2]
        if self.tile_size is None:
            return [(0, 0, w, h)]
        return tile_grid(w, h, self.tile_size, self.tile_overlap)

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Run SAM 3 on one field and convert instances to detections."""
        h, w = image.shape[:2]
        tiles = self.tiles(image)
        whole: Tile = (0, 0, w, h)
        jobs = [
            (t, concept)
            for concept, c in self.concepts.items()
            for t in (tiles if self.tile_classes is None or c in self.tile_classes else [whole])
        ]
        encoded = {t: encode_jpeg(image[t[1] : t[3], t[0] : t[2]]) for t, _ in jobs}

        def run(job: tuple[Tile, str]) -> list[Detection]:
            (tx, ty, _, _), concept = job
            results = self.client.segment_concepts(encoded[job[0]], [concept], model=self.model)
            out = []
            for r in results:
                cls = self.concepts.get(r.concept)
                if cls is None or r.score < self.class_min_score.get(cls, self.min_score):
                    continue
                x0, y0, x1, y1 = r.box_xyxy
                if x1 <= x0 or y1 <= y0:
                    continue
                box = BoundingBox(x0 + tx, y0 + ty, x1 + tx, y1 + ty)
                out.append(Detection(cls=cls, box=box, score=r.score, source=self.name))
            return out

        with ThreadPoolExecutor(max_workers=max(1, min(self.max_workers, len(jobs)))) as pool:
            detections = [d for found in pool.map(run, jobs) for d in found]
        if len({t for t, _ in jobs}) > 1:
            detections = merge_duplicates(detections)
        return drop_parasites_in_wbc(detections)
