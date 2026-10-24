"""Parsers that turn each dataset's labels into :class:`~darubini.types.Detection` lists."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

# Parses local dataset files only, never untrusted uploads.
from xml.etree import ElementTree as ET  # nosec B405

from darubini.types import BoundingBox, Detection, ObjectClass

#: Words that identify each class. Real labels are messy: the UDOM Tanzania set alone uses
#: "Plasmodium trophozoite", "Plasmodium trophozoites", "Plasimodium trophozoite" and "plasmodium".
PARASITE_WORDS = ("plasmodium", "plasimodium", "parasite", "trophozoite", "schizont", "ring")
WBC_WORDS = ("wbc", "white_blood_cell", "white blood cell", "leukocyte", "leucocyte")
#: Gametocytes are sexual forms. WHO density counts asexual parasites only, so they are excluded.
EXCLUDED_WORDS = ("gametocyte",)
#: Radius (px) used to box a point annotation. Tune per dataset magnification.
DEFAULT_POINT_RADIUS = 12.0


def normalise_label(label: str) -> ObjectClass | None:
    """Map a raw label to a class, or None if it is excluded or ambiguous.

    Matching is by keyword, so spelling variants and plurals are handled. A label that
    names both a WBC and a parasite (UDOM has one "WBCPlasmodium trophozoite") is
    ambiguous and returns None rather than guessing.
    """
    text = label.strip().lower()
    if not text or any(w in text for w in EXCLUDED_WORDS):
        return None
    is_parasite = any(w in text for w in PARASITE_WORDS)
    is_wbc = any(w in text for w in WBC_WORDS)
    if is_parasite and is_wbc:
        return None
    if is_wbc:
        return ObjectClass.WBC
    if is_parasite:
        return ObjectClass.PARASITE
    return None


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


def parse_coco(path: Path) -> dict[str, list[Detection]]:
    """Parse a COCO JSON file into detections keyed by image file name.

    COCO boxes are ``[x, y, width, height]``. Images with no usable boxes still get
    an empty list, so they count as fields with nothing in them.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {c["id"]: c["name"] for c in data.get("categories", [])}
    files = {img["id"]: img["file_name"] for img in data.get("images", [])}
    out: dict[str, list[Detection]] = {name: [] for name in files.values()}
    for ann in data.get("annotations", []):
        cls = normalise_label(str(names.get(ann.get("category_id"), "")))
        file_name = files.get(ann.get("image_id"))
        bbox = ann.get("bbox") or []
        if cls is None or file_name is None or len(bbox) != 4:
            continue
        x, y, w, h = (float(v) for v in bbox)
        if w <= 0 or h <= 0:
            continue
        out[file_name].append(
            Detection(cls=cls, box=BoundingBox(x, y, x + w, y + h), source="coco")
        )
    return out


def parse_tile_mapper(path: Path) -> dict[str, str]:
    """Map each tile to the original photo it was cut from (UDOM ``mapper.csv``).

    Rows look like ``IMG_2145,000001,000002,...``: an original photo followed by its
    tiles. Use the result to keep every tile of one photo on the same side of a split.
    """
    groups: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if not row or row[0].strip().lower() == "old_name":
                continue
            original = row[0].strip()
            for tile in row[1:]:
                if tile.strip():
                    groups[tile.strip()] = original
    return groups
