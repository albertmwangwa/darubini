"""Metrics for comparing predicted detections and counts with expert labels."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from darubini.types import Detection, ObjectClass


@dataclass(frozen=True)
class DetectionScore:
    """Precision, recall and F1 for one class at an IoU threshold."""

    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        """TP / (TP + FP), or 0 when nothing was predicted."""
        d = self.true_positives + self.false_positives
        return self.true_positives / d if d else 0.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN), or 0 when nothing was labelled."""
        d = self.true_positives + self.false_negatives
        return self.true_positives / d if d else 0.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def match_detections(
    predicted: Sequence[Detection],
    truth: Sequence[Detection],
    cls: ObjectClass,
    iou_threshold: float = 0.3,
) -> DetectionScore:
    """Greedy one-to-one matching by IoU, highest-scoring predictions first.

    A low default IoU suits small parasites, where a few pixels of offset matter a lot.
    """
    preds = sorted((d for d in predicted if d.cls is cls), key=lambda d: d.score, reverse=True)
    gts = [d for d in truth if d.cls is cls]
    used = [False] * len(gts)
    tp = 0
    for p in preds:
        best, best_iou = -1, iou_threshold
        for i, g in enumerate(gts):
            if used[i]:
                continue
            iou = p.box.iou(g.box)
            if iou >= best_iou:
                best, best_iou = i, iou
        if best >= 0:
            used[best] = True
            tp += 1
    return DetectionScore(tp, len(preds) - tp, len(gts) - tp)


@dataclass(frozen=True)
class CountAgreement:
    """How closely predicted counts track expert counts."""

    n: int
    mae: float
    mean_bias: float
    pearson_r: float | None


def count_agreement(predicted: Sequence[float], truth: Sequence[float]) -> CountAgreement:
    """Mean absolute error, mean bias and Pearson r between paired counts."""
    if len(predicted) != len(truth):
        raise ValueError("predicted and truth must be the same length")
    n = len(truth)
    if n == 0:
        raise ValueError("need at least one pair")
    diffs = [p - t for p, t in zip(predicted, truth, strict=True)]
    mae = sum(abs(d) for d in diffs) / n
    bias = sum(diffs) / n
    r: float | None = None
    if n >= 2:
        mp, mt = sum(predicted) / n, sum(truth) / n
        cov = sum((p - mp) * (t - mt) for p, t in zip(predicted, truth, strict=True))
        sp = math.sqrt(sum((p - mp) ** 2 for p in predicted))
        st = math.sqrt(sum((t - mt) ** 2 for t in truth))
        r = cov / (sp * st) if sp and st else None
    return CountAgreement(n=n, mae=mae, mean_bias=bias, pearson_r=r)


@dataclass(frozen=True)
class SlideAccuracy:
    """Slide-level positive/negative agreement."""

    sensitivity: float
    specificity: float
    tp: int
    tn: int
    fp: int
    fn: int


def slide_accuracy(predicted: Sequence[bool], truth: Sequence[bool]) -> SlideAccuracy:
    """Sensitivity and specificity of positive/negative slide calls."""
    if len(predicted) != len(truth):
        raise ValueError("predicted and truth must be the same length")
    tp = sum(p and t for p, t in zip(predicted, truth, strict=True))
    tn = sum((not p) and (not t) for p, t in zip(predicted, truth, strict=True))
    fp = sum(p and not t for p, t in zip(predicted, truth, strict=True))
    fn = sum((not p) and t for p, t in zip(predicted, truth, strict=True))
    sens = tp / (tp + fn) if tp + fn else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    return SlideAccuracy(sens, spec, tp, tn, fp, fn)
