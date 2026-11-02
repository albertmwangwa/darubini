"""Score whole segmenters against expert labels, per class, field by field."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from darubini.data.fields import LabelledField
from darubini.evaluation import DetectionScore, match_centres
from darubini.pipeline import load_image
from darubini.segmentation.base import Segmenter
from darubini.types import ObjectClass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassScore:
    """Detection and count agreement for one segmenter and class over a set of fields."""

    name: str
    cls: ObjectClass
    precision: float
    recall: float
    f1: float
    count_mae: float
    count_bias: float
    labelled: int


def compare_on_fields(
    fields: Sequence[LabelledField],
    segmenters: dict[str, Segmenter],
    classes: Sequence[ObjectClass] = (ObjectClass.PARASITE, ObjectClass.WBC),
) -> list[ClassScore]:
    """Run every segmenter on every field once and score each class by centre matching."""
    keys = [(n, c) for n in segmenters for c in classes]
    totals = {k: [0, 0, 0] for k in keys}
    errors: dict[tuple[str, ObjectClass], list[int]] = {k: [] for k in keys}
    labelled = dict.fromkeys(classes, 0)
    for i, f in enumerate(fields, 1):
        image = load_image(f.image)
        truth = {c: [d for d in f.truth if d.cls is c] for c in classes}
        for c in classes:
            labelled[c] += len(truth[c])
        for name, seg in segmenters.items():
            found = seg.segment(image)
            for c in classes:
                preds = [d for d in found if d.cls is c]
                s = match_centres(preds, truth[c], c)
                t = totals[(name, c)]
                t[0] += s.true_positives
                t[1] += s.false_positives
                t[2] += s.false_negatives
                errors[(name, c)].append(len(preds) - len(truth[c]))
        if i % 10 == 0 or i == len(fields):
            log.info("evaluated %d/%d fields", i, len(fields))
    out = []
    for name, c in keys:
        s = DetectionScore(*totals[(name, c)])
        e = np.asarray(errors[(name, c)], dtype=np.float64)
        mae = float(np.abs(e).mean()) if len(e) else 0.0
        bias = float(e.mean()) if len(e) else 0.0
        out.append(ClassScore(name, c, s.precision, s.recall, s.f1, mae, bias, labelled[c]))
    return out


def render_comparison(scores: list[ClassScore], header: str) -> str:
    """Markdown tables of :func:`compare_on_fields` results, one per class."""
    lines = [header]
    for c in dict.fromkeys(s.cls for s in scores):
        rows = [s for s in scores if s.cls is c]
        lines += [
            "",
            f"## {c.value.replace('_', ' ').capitalize()} ({rows[0].labelled} labelled)",
            "",
            "| Segmenter | Precision | Recall | F1 | Count MAE | Count bias |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for s in rows:
            lines.append(
                f"| {s.name} | {s.precision:.2f} | {s.recall:.2f} | {s.f1:.2f} | "
                f"{s.count_mae:.1f} | {s.count_bias:+.1f} |"
            )
    return "\n".join(lines) + "\n"
