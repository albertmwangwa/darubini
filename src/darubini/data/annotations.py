"""Parsers that turn each dataset's labels into :class:`~darubini.types.Detection` lists."""

from __future__ import annotations

import math
from pathlib import Path

# Parses local dataset files only, never untrusted uploads.
from xml.etree import ElementTree as ET  # nosec B405

from darubini.types import BoundingBox, Detection, ObjectClass

#: Label spellings seen across datasets, normalised to Darubini classes.
LABEL_MAP: dict[str, ObjectClass] = {
    "plasmodium": ObjectClass.PARASITE,
    "parasite": ObjectClass.PARASITE,
    "trophozoite": ObjectClass.PARASITE,
    "wbc": ObjectClass.WBC,
    "white_blood_cell": ObjectClass.WBC,
    "white blood cell": ObjectClass.WBC,
    "leukocyte": ObjectClass.WBC,
}

#: Radius (px) used to box a point annotation. Tune per dataset magnification.
DEFAULT_POINT_RADIUS = 12.0


def normalise_label(label: str) -> ObjectClass | None:
    """Map a raw label to a class, or None if it is not one we count."""
    return LABEL_MAP.get(label.strip().lower())


def parse_voc(path: Path) -> list[Detection]:
    """Parse a Pascal VOC XML file (used by the UDOM Tanzania dataset)."""
    root = ET.parse(path).getroot()  # noqa: S314  # nosec B314
    out: list[Detection] = []
    for obj in root.iter("object"):
        cls = normalise_label(obj.findtext("name", default=""))
        bb = obj.find("bndbox")
        if cls is None or bb is None:
            continue
        coords = [float(bb.findtext(k, default="nan")) for k in ("xmin", "ymin", "xmax", "ymax")]
        if any(math.isnan(c) for c in coords) or coords[2] <= coords[0] or coords[3] <= coords[1]:
            continue
        out.append(Detection(cls=cls, box=BoundingBox(*coords), source="voc"))
    return out


def parse_nlm_thick(path: Path, point_radius: float = DEFAULT_POINT_RADIUS) -> list[Detection]:
    """Parse an NLM thick-smear ground-truth text file.

    Each object line is comma-separated: the 2nd field is the label
    (``Parasite`` or ``White_Blood_Cell``), the 4th is the shape (``Circle`` or
    ``Point``), and numeric coordinates follow. A circle gives a centre and a
    point on its edge; a point gives a centre. Lines that do not match (such as
    the image-size header) are skipped.

    Verify this against the first downloaded files and adjust if the layout differs.
    """
    out: list[Detection] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        cls = normalise_label(parts[1])
        if cls is None:
            continue
        shape = parts[3].lower()
        nums: list[float] = []
        for p in parts[4:]:
            try:
                nums.append(float(p))
            except ValueError:
                continue
        if len(nums) % 2 == 1:
            nums = nums[1:]  # leading point-count field
        if len(nums) < 2:
            continue
        cx, cy = nums[0], nums[1]
        r = point_radius
        if shape == "circle" and len(nums) >= 4:
            r = max(math.hypot(nums[2] - cx, nums[3] - cy), 1.0)
        out.append(
            Detection(cls=cls, box=BoundingBox(cx - r, cy - r, cx + r, cy + r), source="nlm")
        )
    return out
