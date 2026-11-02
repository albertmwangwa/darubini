"""Parasite verifier: keeps true parasites among cheap, high-recall candidates.

Stain-blob candidates find about 90% of labelled parasites, but most candidates
are platelets, stain debris or background specks. A small neural network scores
each candidate from a crop around it. Crops are sized relative to the candidate
and colours are divided by the field's background colour, so the features do
not depend on camera resolution or stain shade.

The network is plain NumPy and saved as ``.npz`` (no pickle), so loading a
model file cannot run code.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from darubini.data.fields import LabelledField
from darubini.pipeline import load_image
from darubini.quality import field_of_view, stain_mask, to_gray
from darubini.segmentation.base import Segmenter
from darubini.segmentation.sam import drop_parasites_in_wbc
from darubini.types import Detection, ObjectClass

log = logging.getLogger(__name__)

CROP_PIXELS = 16
#: Crop side as a multiple of the candidate's longer side.
CROP_SCALE = 3.0
MIN_CROP_SIDE = 12
N_FEATURES = CROP_PIXELS * CROP_PIXELS * 3 + 8

F32 = NDArray[np.float32]


def background_colour(image: NDArray[np.uint8]) -> NDArray[np.float32]:
    """Median RGB of the field of view, the reference for colour normalisation."""
    fov = field_of_view(to_gray(image))
    pixels = image[fov] if fov.any() else image.reshape(-1, image.shape[-1])
    return np.asarray(np.maximum(np.median(pixels[:, :3], axis=0), 1.0), dtype=np.float32)


def candidate_features(image: NDArray[np.uint8], candidates: Sequence[Detection]) -> F32:
    """One feature row per candidate: a normalised colour crop plus blob statistics."""
    if not candidates:
        return np.zeros((0, N_FEATURES), dtype=np.float32)
    h, w = image.shape[:2]
    bg = background_colour(image)
    stained = stain_mask(image)
    halves = [
        max(MIN_CROP_SIDE, CROP_SCALE * max(d.box.width, d.box.height)) / 2 for d in candidates
    ]
    # Pad with the background colour so crops at the edge stay centred on their candidate.
    pad = int(np.ceil(max(halves))) + 1
    padded = np.empty((h + 2 * pad, w + 2 * pad, 3), dtype=np.uint8)
    padded[:] = np.clip(bg, 0, 255).astype(np.uint8)
    padded[pad : pad + h, pad : pad + w] = image[..., :3]
    pil = Image.fromarray(padded)
    rows = []
    for d, half in zip(candidates, halves, strict=True):
        b = d.box
        cx, cy = b.center[0] + pad, b.center[1] + pad
        crop = pil.resize(
            (CROP_PIXELS, CROP_PIXELS),
            Image.Resampling.BILINEAR,
            box=(cx - half, cy - half, cx + half, cy + half),
        )
        pixels = np.asarray(crop, dtype=np.float32) / bg
        x0, y0 = max(0, int(b.x_min)), max(0, int(b.y_min))
        x1, y1 = min(w, max(x0 + 1, int(b.x_max))), min(h, max(y0 + 1, int(b.y_max)))
        inner = image[y0:y1, x0:x1, :3].reshape(-1, 3).astype(np.float32) / bg
        stats = [
            float(inner.mean()),
            float(np.min(inner)),
            float((inner[:, 2] - inner[:, 1]).mean()),
            float((inner[:, 0] - inner[:, 1]).mean()),
            float(stained[y0:y1, x0:x1].mean()),
            float(np.log(max(b.width, 1.0) / max(b.height, 1.0))),
            *blob_shape(inner[:, 1].reshape(y1 - y0, x1 - x0)),
        ]
        rows.append(np.concatenate([pixels.ravel(), np.asarray(stats, dtype=np.float32)]))
    return np.stack(rows).astype(np.float32)


def blob_shape(green: F32) -> tuple[float, float]:
    """Orientation-free shape of the dark blob in a candidate box.

    Args:
        green: green channel over background, for the pixels of the box.

    Returns:
        (log elongation, fill): elongation is the ratio of the blob's principal
        axes from second moments, so a diagonal rod scores high even when its box
        is square; fill is the blob's share of the box. Parasite chromatin is a
        round dot; bacteria and stain precipitate are often rods.

    """
    if green.size < 2:
        return 0.0, 1.0
    cut = (float(np.min(green)) + float(np.median(green))) / 2
    ys, xs = np.nonzero(green <= cut)
    if len(xs) < 3:
        return 0.0, len(xs) / green.size
    cov = np.cov(np.stack([xs, ys]).astype(np.float64))
    low, high = np.linalg.eigvalsh(cov)
    elongation = float(np.sqrt((high + 0.25) / (max(low, 0.0) + 0.25)))
    return float(np.log(elongation)), len(xs) / green.size


def label_candidates(candidates: Sequence[Detection], truth: Sequence[Detection]) -> F32:
    """1 for candidates matching a labelled parasite (either centre inside the other)."""
    gts = [g.box for g in truth if g.cls is ObjectClass.PARASITE]

    def hit(d: Detection) -> bool:
        px, py = d.box.center
        for g in gts:
            gx, gy = g.center
            if (g.x_min <= px <= g.x_max and g.y_min <= py <= g.y_max) or (
                d.box.x_min <= gx <= d.box.x_max and d.box.y_min <= gy <= d.box.y_max
            ):
                return True
        return False

    return np.asarray([1.0 if hit(d) else 0.0 for d in candidates], dtype=np.float32)


@dataclass
class TrainingSet:
    """Features and labels, with the patient of each row for grouped splits."""

    x: F32
    y: F32
    patients: list[str] = field(default_factory=list)

    def __add__(self, other: TrainingSet) -> TrainingSet:
        return TrainingSet(
            np.concatenate([self.x, other.x]),
            np.concatenate([self.y, other.y]),
            [*self.patients, *other.patients],
        )

    def repeat(self, times: int) -> TrainingSet:
        """Repeat every row ``times`` over, to weight a smaller domain up."""
        return TrainingSet(
            np.tile(self.x, (times, 1)), np.tile(self.y, times), self.patients * times
        )


def build_training_set(fields: Sequence[LabelledField], candidates: Segmenter) -> TrainingSet:
    """Run the candidate generator on labelled fields and label each candidate."""
    xs, ys, patients = [], [], []
    for i, f in enumerate(fields, 1):
        image = load_image(f.image)
        cands = [d for d in candidates.segment(image) if d.cls is ObjectClass.PARASITE]
        xs.append(candidate_features(image, cands))
        ys.append(label_candidates(cands, f.truth))
        patients += [f.patient] * len(cands)
        if i % 25 == 0 or i == len(fields):
            log.info("features: %d/%d fields, %d candidates", i, len(fields), len(patients))
    x = np.concatenate(xs) if xs else np.zeros((0, N_FEATURES), dtype=np.float32)
    y = np.concatenate(ys) if ys else np.zeros(0, dtype=np.float32)
    return TrainingSet(x, y, patients)


def _sigmoid(z: F32) -> F32:
    return np.asarray(1.0 / (1.0 + np.exp(-np.clip(z, -30, 30))), dtype=np.float32)


@dataclass
class ParasiteVerifier:
    """One-hidden-layer network on standardised candidate features."""

    mean: F32
    scale: F32
    w1: F32
    b1: F32
    w2: F32
    b2: F32
    threshold: float = 0.5

    def predict_proba(self, x: F32) -> F32:
        """Probability that each candidate row is a parasite."""
        if len(x) == 0:
            return np.zeros(0, dtype=np.float32)
        h = np.maximum((x - self.mean) / self.scale @ self.w1 + self.b1, 0)
        return _sigmoid((h @ self.w2 + self.b2).ravel())

    def save(self, path: Path) -> None:
        """Write weights to an ``.npz`` file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            path,
            mean=self.mean,
            scale=self.scale,
            w1=self.w1,
            b1=self.b1,
            w2=self.w2,
            b2=self.b2,
            threshold=np.float32(self.threshold),
            n_features=np.int32(N_FEATURES),
        )

    @classmethod
    def load(cls, path: Path) -> ParasiteVerifier:
        """Read weights saved by :meth:`save`; refuses files from other feature layouts."""
        with np.load(path, allow_pickle=False) as d:
            if int(d["n_features"]) != N_FEATURES:
                raise ValueError(f"{path} was trained on a different feature layout")
            return cls(
                mean=d["mean"],
                scale=d["scale"],
                w1=d["w1"],
                b1=d["b1"],
                w2=d["w2"],
                b2=d["b2"],
                threshold=float(d["threshold"]),
            )

    @classmethod
    def fit(
        cls,
        train: TrainingSet,
        valid: TrainingSet,
        hidden: int = 64,
        epochs: int = 40,
        batch: int = 256,
        lr: float = 1e-3,
        weight_decay: float = 1e-4,
        patience: int = 5,
        seed: int = 0,
    ) -> ParasiteVerifier:
        """Train with Adam on class-weighted cross-entropy, early-stopped on ``valid``.

        The decision threshold is then set to the best F1 on ``valid``.
        """
        rng = np.random.default_rng(seed)
        mean = train.x.mean(axis=0).astype(np.float32)
        scale = (train.x.std(axis=0) + 1e-6).astype(np.float32)
        xt, xv = (train.x - mean) / scale, (valid.x - mean) / scale
        n_in = train.x.shape[1]
        params = {
            "w1": (rng.normal(0, np.sqrt(2 / n_in), (n_in, hidden))).astype(np.float32),
            "b1": np.zeros(hidden, dtype=np.float32),
            "w2": (rng.normal(0, np.sqrt(1 / hidden), (hidden, 1))).astype(np.float32),
            "b2": np.zeros(1, dtype=np.float32),
        }
        m = {k: np.zeros_like(v) for k, v in params.items()}
        v = {k: np.zeros_like(p) for k, p in params.items()}
        pos = float(train.y.mean()) if len(train.y) else 0.5
        pos_weight = (1 - pos) / max(pos, 1e-6)

        def loss(x: F32, y: F32) -> float:
            h = np.maximum(x @ params["w1"] + params["b1"], 0)
            p = _sigmoid((h @ params["w2"] + params["b2"]).ravel())
            eps = 1e-7
            terms = pos_weight * y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)
            return float(-terms.mean())

        best = (np.inf, {k: p.copy() for k, p in params.items()})
        stale, step = 0, 0
        for epoch in range(epochs):
            order = rng.permutation(len(xt))
            for start in range(0, len(order), batch):
                idx = order[start : start + batch]
                x, y = xt[idx], train.y[idx]
                h_pre = x @ params["w1"] + params["b1"]
                h = np.maximum(h_pre, 0)
                p = _sigmoid((h @ params["w2"] + params["b2"]).ravel())
                weight = np.where(y > 0.5, pos_weight, 1.0).astype(np.float32)
                dz = ((p - y) * weight / len(idx)).reshape(-1, 1).astype(np.float32)
                dh = (dz @ params["w2"].T) * (h_pre > 0)
                grads = {
                    "w2": h.T @ dz + weight_decay * params["w2"],
                    "b2": dz.sum(axis=0),
                    "w1": x.T @ dh + weight_decay * params["w1"],
                    "b1": dh.sum(axis=0),
                }
                step += 1
                for k, g in grads.items():
                    m[k] = 0.9 * m[k] + 0.1 * g
                    v[k] = 0.999 * v[k] + 0.001 * g * g
                    m_hat = m[k] / (1 - 0.9**step)
                    v_hat = v[k] / (1 - 0.999**step)
                    params[k] = (params[k] - lr * m_hat / (np.sqrt(v_hat) + 1e-8)).astype(
                        np.float32
                    )
            val_loss = loss(xv, valid.y)
            log.info("epoch %d: validation loss %.4f", epoch + 1, val_loss)
            if val_loss < best[0] - 1e-4:
                best, stale = (val_loss, {k: p.copy() for k, p in params.items()}), 0
            else:
                stale += 1
                if stale >= patience:
                    break
        model = cls(mean, scale, **best[1])
        model.threshold = best_f1_threshold(model.predict_proba(valid.x), valid.y)
        return model


def best_f1_threshold(proba: F32, y: F32) -> float:
    """Threshold on ``proba`` with the best F1 against ``y`` (0.5 if undefined)."""
    best_t, best_f1 = 0.5, -1.0
    for t in np.arange(0.05, 0.96, 0.05):
        pred = proba >= t
        tp = float((pred & (y > 0.5)).sum())
        fp = float((pred & (y < 0.5)).sum())
        fn = float((~pred & (y > 0.5)).sum())
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        if f1 > best_f1:
            best_t, best_f1 = float(round(t, 2)), f1
    return best_t


class VerifiedSegmenter:
    """Parasites from candidates kept by the verifier; WBCs from a WBC segmenter.

    Parasite candidates centred inside a WBC are dropped first.
    """

    name = "verified"

    def __init__(
        self, candidates: Segmenter, verifier: ParasiteVerifier, wbc: Segmenter | None = None
    ) -> None:
        self.candidates = candidates
        self.verifier = verifier
        self.wbc = wbc

    def segment(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Find WBCs, then keep the parasite candidates the verifier accepts."""
        found = self.candidates.segment(image)
        wbcs = (
            [d for d in self.wbc.segment(image) if d.cls is ObjectClass.WBC]
            if self.wbc is not None
            else [d for d in found if d.cls is ObjectClass.WBC]
        )
        # Only the chosen WBC source suppresses parasites, not the candidates' own blobs.
        parasites = [d for d in found if d.cls is ObjectClass.PARASITE]
        cands = [
            d for d in drop_parasites_in_wbc([*wbcs, *parasites]) if d.cls is ObjectClass.PARASITE
        ]
        proba = self.verifier.predict_proba(candidate_features(image, cands))
        kept = [
            Detection(cls=d.cls, box=d.box, score=float(p), source=self.name)
            for d, p in zip(cands, proba, strict=True)
            if p >= self.verifier.threshold
        ]
        return [*wbcs, *kept]
