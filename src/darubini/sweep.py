"""Prompt and tiling sweep for SAM 3 on labelled fields.

Each variant pairs one text concept (scored against one class) with a tile size.
SAM runs once per variant with no score cutoff; the confidence threshold is then
swept offline, so tuning it costs no extra API calls. Run only on tuning splits.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from darubini.data.fields import LabelledField
from darubini.evaluation import DetectionScore, match_centres, match_detections
from darubini.meta.client import MetaModelClient
from darubini.pipeline import load_image
from darubini.segmentation.sam import SamSegmenter, drop_parasites_in_wbc, tile_grid
from darubini.types import Detection, ObjectClass

log = logging.getLogger(__name__)

#: SAM 3.1 list price per image (US$2.50 per 1,000).
USD_PER_REQUEST = 0.0025
SCORE_THRESHOLDS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)

Matcher = Callable[[Sequence[Detection], Sequence[Detection], ObjectClass], DetectionScore]


@dataclass(frozen=True)
class Variant:
    """One concept prompt, the class it should find, and a tile size (None: whole field)."""

    concept: str
    cls: ObjectClass
    tile_size: int | None = None

    @property
    def label(self) -> str:
        """Short name for tables."""
        return f'"{self.concept}" @ {self.tile_size or "full"}'


@dataclass
class VariantRun:
    """Raw detections for one variant on every field, plus the matching labels."""

    variant: Variant
    predicted: list[list[Detection]] = field(default_factory=list)
    truth: list[list[Detection]] = field(default_factory=list)


@dataclass(frozen=True)
class VariantScore:
    """Best-threshold score for one variant."""

    variant: Variant
    threshold: float
    score: DetectionScore
    count_mae: float
    mean_truth: float


def requests_for(fields: Sequence[LabelledField], variants: Sequence[Variant], overlap: int) -> int:
    """Upper bound on SAM requests (before the cache) for a sweep."""
    total = 0
    for f in fields:
        with Image.open(f.image) as im:
            w, h = im.size
        for v in variants:
            total += 1 if v.tile_size is None else len(tile_grid(w, h, v.tile_size, overlap))
    return total


def run_sweep(
    fields: Sequence[LabelledField],
    variants: Sequence[Variant],
    client: MetaModelClient,
    model: str,
    tile_overlap: int = 128,
    workers: int = 4,
    wbc_filter: Variant | None = None,
    wbc_min_score: float = 0.5,
) -> list[VariantRun]:
    """Run every variant on every field, one field in memory at a time.

    With ``wbc_filter`` (a whole-field WBC prompt), parasite detections centred
    inside a WBC it finds are dropped, as the full pipeline does.
    """
    runs = [VariantRun(v) for v in variants]
    start = time.monotonic()
    for i, f in enumerate(fields, 1):
        image = load_image(f.image)

        def segment(v: Variant, image: NDArray[np.uint8] = image) -> list[Detection]:
            seg = SamSegmenter(
                client,
                model,
                concepts={v.concept: v.cls},
                min_score=0.0,
                tile_size=v.tile_size,
                tile_overlap=tile_overlap,
                max_workers=4,
            )
            return seg.segment(image)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            found = list(pool.map(segment, variants))
        if wbc_filter is not None:
            wbcs = [d for d in segment(wbc_filter) if d.score >= wbc_min_score]
            found = [
                [d for d in drop_parasites_in_wbc([*wbcs, *dets]) if d.cls is v.cls]
                if v.cls is ObjectClass.PARASITE
                else dets
                for v, dets in zip(variants, found, strict=True)
            ]
        for run, dets in zip(runs, found, strict=True):
            run.predicted.append(dets)
            run.truth.append([d for d in f.truth if d.cls is run.variant.cls])
        log.info(
            "field %d/%d %s: %d requests sent so far, %.0fs",
            i,
            len(fields),
            f.image.name,
            client.billed_requests,
            time.monotonic() - start,
        )
    return runs


def score_run(run: VariantRun, matcher: Matcher) -> VariantScore:
    """Score a run at every threshold and keep the one with the best F1."""
    best: VariantScore | None = None
    truth_counts = [len(t) for t in run.truth]
    for thr in SCORE_THRESHOLDS:
        tp = fp = fn = 0
        errors = []
        for preds, truth in zip(run.predicted, run.truth, strict=True):
            kept = [d for d in preds if d.score >= thr]
            s = matcher(kept, truth, run.variant.cls)
            tp, fp, fn = tp + s.true_positives, fp + s.false_positives, fn + s.false_negatives
            errors.append(abs(len(kept) - len(truth)))
        score = DetectionScore(tp, fp, fn)
        n = max(len(errors), 1)
        candidate = VariantScore(run.variant, thr, score, sum(errors) / n, sum(truth_counts) / n)
        if best is None or candidate.score.f1 > best.score.f1:
            best = candidate
    if best is None:
        raise ValueError("SCORE_THRESHOLDS is empty")
    return best


def matcher_for(centres: bool) -> Matcher:
    """Centre matching (default for NLM labels), or IoU >= 0.3 matching."""
    return match_centres if centres else match_detections


def render(
    scores: list[VariantScore],
    dataset: str,
    split: str,
    n_fields: int,
    requests: int,
    wbc_filter: Variant | None = None,
) -> str:
    """Markdown table of variant scores, best F1 first within each class."""
    lines = [
        "# SAM 3 prompt and tiling sweep",
        "",
        f"Generated by `darubini sweep` on {n_fields} fields from the `{split}` split of "
        f"`{dataset}` ({requests} SAM requests sent, about "
        f"US${requests * USD_PER_REQUEST:.2f}). Each row uses the confidence threshold "
        "with the best F1. A detection matches a label when either box's centre lies "
        "inside the other (see `evaluation.match_centres`).",
    ]
    if wbc_filter is not None:
        lines += [
            "",
            f"Parasite detections centred inside a white blood cell found by {wbc_filter.label} "
            "were dropped before scoring.",
        ]
    for cls in ObjectClass:
        rows = sorted((s for s in scores if s.variant.cls is cls), key=lambda s: -s.score.f1)
        if not rows:
            continue
        lines += [
            "",
            f"## {cls.value.replace('_', ' ').capitalize()}",
            "",
            "| Prompt @ tile | Threshold | Precision | Recall | F1 | Count MAE | Mean labelled |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for s in rows:
            lines.append(
                f"| {s.variant.label} | {s.threshold:.1f} | {s.score.precision:.2f} | "
                f"{s.score.recall:.2f} | {s.score.f1:.2f} | {s.count_mae:.1f} | "
                f"{s.mean_truth:.1f} |"
            )
    return "\n".join(lines) + "\n"
