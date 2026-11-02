"""Labelled fields and patient-level splits for evaluation.

Fields from one patient are never split across tuning and testing, so tuning
cannot learn a patient's stain or smear and then be scored on it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from darubini.data.annotations import parse_nlm_thick, parse_tile_mapper, parse_voc
from darubini.types import Detection

Split = Literal["tune", "val", "test"]
#: Held-out sets (UDOM) are split by photo into a training part (``dev``) and a
#: frozen test set, scored once at the end. ``dev`` is halved by photo: ``adapt``
#: trains domain adaptation, ``check`` measures it.
HeldOutSplit = Literal["dev", "adapt", "check", "test"]
#: Share of photos in ``dev``. Raised from 0.15 to 0.70 on 2 Nov 2026, when the lab
#: session was cancelled and the Tanzanian data had to serve for training too. The
#: test set had never been scored, and the hash rule nests: the new test photos are
#: a subset of the old ones, and every old dev photo keeps its adapt/check half.
HELD_OUT_TRAIN_FRACTION = 0.70
#: Share of patients in each split (see docs/EVALUATION.md).
SPLIT_FRACTIONS: tuple[tuple[Split, float], ...] = (("tune", 0.70), ("val", 0.15), ("test", 0.15))


@dataclass(frozen=True)
class LabelledField:
    """One field image with its expert labels."""

    image: Path
    patient: str
    truth: tuple[Detection, ...]


def _unit_hash(key: str) -> float:
    """Map ``key`` to a number in [0, 1], stable across machines and runs."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def patient_split(patient: str) -> Split:
    """Deterministic split for a patient id, stable across machines and runs."""
    u = _unit_hash(patient)
    edge = 0.0
    for name, fraction in SPLIT_FRACTIONS:
        edge += fraction
        if u < edge:
            return name
    return SPLIT_FRACTIONS[-1][0]


def nlm_thick_fields(root: Path, split: Split | None = None) -> list[LabelledField]:
    """Fields of an NLM thick-smear dataset (``<patient>/<image>.jpg`` + ``GT*/<patient>/*.txt``).

    Images without a ground-truth file are skipped.
    """
    gt_dirs = [d for d in sorted(root.iterdir()) if d.is_dir() and d.name.lower().startswith("gt")]
    out = []
    for patient_dir in sorted(root.iterdir()):
        if not patient_dir.is_dir() or patient_dir in gt_dirs:
            continue
        patient = patient_dir.name
        if split is not None and patient_split(patient) != split:
            continue
        for image in sorted(patient_dir.glob("*.jpg")):
            gt = next(
                (p for d in gt_dirs if (p := d / patient / f"{image.stem}.txt").is_file()), None
            )
            if gt is not None:
                out.append(LabelledField(image, patient, tuple(parse_nlm_thick(gt))))
    return out


def held_out_split(group: str) -> HeldOutSplit:
    """``adapt``/``check`` half of the dev slice, or ``test``, for a held-out photo or patient."""
    if _unit_hash(group) >= HELD_OUT_TRAIN_FRACTION:
        return "test"
    return "adapt" if _unit_hash(f"adapt:{group}") < 0.5 else "check"


def udom_fields(root: Path, split: HeldOutSplit | None = None) -> list[LabelledField]:
    """UDOM tiles with VOC labels, grouped by original photo via ``mapper.csv``.

    The photo plays the patient's role, so every tile of a photo lands in one split.
    """
    mappers = sorted(root.rglob("mapper.csv"))
    photos = parse_tile_mapper(mappers[0]) if mappers else {}
    out = []
    for xml in sorted(root.rglob("*.xml")):
        image = xml.with_suffix(".jpg")
        if not image.is_file():
            continue
        photo = photos.get(xml.stem, xml.stem)
        part = held_out_split(photo)
        if split is not None and part != split and not (split == "dev" and part != "test"):
            continue
        out.append(LabelledField(image, photo, tuple(parse_voc(xml))))
    return out


def split_table(
    fields: list[LabelledField], split_of: Callable[[str], str]
) -> list[tuple[str, str, int]]:
    """One row per patient or photo: its id, its split and how many fields it has."""
    counts: dict[str, int] = {}
    for f in fields:
        counts[f.patient] = counts.get(f.patient, 0) + 1
    return [(group, split_of(group), n) for group, n in sorted(counts.items())]
