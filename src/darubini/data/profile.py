"""Summarise what a downloaded dataset actually contains.

Dataset records do not always match the files (a "VOC" set may ship COCO JSON),
so before writing loaders we look: file types, folder layout, sample names, and
the top-level structure of any JSON annotation files.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
ANNOTATION_EXTS = {".xml", ".json", ".txt", ".csv"}
MAX_JSON_BYTES = 200 * 1024 * 1024
SKIP_NAMES = {".complete", ".gitkeep", "Thumbs.db", "desktop.ini"}
SKIP_DIRS = {".git", ".ipynb_checkpoints", "__MACOSX"}


@dataclass
class DatasetProfile:
    """What one dataset folder holds."""

    dataset_id: str
    files: int = 0
    bytes: int = 0
    by_ext: Counter[str] = field(default_factory=Counter)
    folders: Counter[str] = field(default_factory=Counter)
    samples: dict[str, list[str]] = field(default_factory=dict)
    json_summaries: dict[str, str] = field(default_factory=dict)

    @property
    def images(self) -> int:
        """Number of image files."""
        return sum(n for ext, n in self.by_ext.items() if ext in IMAGE_EXTS)

    @property
    def annotation_format(self) -> str:
        """Best guess at the label format, from file types and JSON structure."""
        if any("COCO" in s for s in self.json_summaries.values()):
            return "COCO JSON"
        if self.by_ext.get(".xml"):
            return "Pascal VOC XML (probably)"
        if self.by_ext.get(".txt"):
            return "text per image (YOLO or NLM style)"
        if self.by_ext.get(".csv"):
            return "CSV"
        return "none found (image-level labels from folder names?)"


def summarise_json(path: Path) -> str:
    """Describe a JSON file's top-level structure without printing its contents."""
    if path.stat().st_size > MAX_JSON_BYTES:
        return "too large to inspect"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return f"unreadable ({exc.__class__.__name__})"
    if isinstance(data, dict):
        keys = sorted(data)
        if {"images", "annotations"} <= set(keys):
            cats = [c.get("name") for c in data.get("categories", []) if isinstance(c, dict)]
            return (
                f"COCO: {len(data['images'])} images, {len(data['annotations'])} annotations, "
                f"categories {cats}"
            )
        return f"object with keys {keys[:12]}"
    if isinstance(data, list):
        return f"list of {len(data)} items"
    return type(data).__name__


def profile(dataset_id: str, root: Path, samples_per_ext: int = 3) -> DatasetProfile:
    """Walk one dataset folder and summarise it."""
    p = DatasetProfile(dataset_id)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        ext = path.suffix.lower() or "(none)"
        rel = path.relative_to(root)
        p.files += 1
        p.bytes += path.stat().st_size
        p.by_ext[ext] += 1
        p.folders[str(rel.parent)] += 1
        bucket = p.samples.setdefault(ext, [])
        if len(bucket) < samples_per_ext:
            bucket.append(str(rel))
        if ext == ".json" and len(p.json_summaries) < 10:
            p.json_summaries[str(rel)] = summarise_json(path)
    return p


def render(profiles: list[DatasetProfile]) -> str:
    """Render profiles as Markdown."""
    out = ["# Dataset profile", ""]
    out += [
        "| Dataset | Files | Size | Images | Label format |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for p in profiles:
        out.append(
            f"| `{p.dataset_id}` | {p.files:,} | {p.bytes / 1e9:.2f} GB | {p.images:,} "
            f"| {p.annotation_format} |"
        )
    for p in profiles:
        out += ["", f"## {p.dataset_id}", "", "File types:"]
        out += [f"- `{ext}`: {n:,}" for ext, n in p.by_ext.most_common()]
        out += ["", "Largest folders:"]
        out += [f"- `{d}`: {n:,} files" for d, n in p.folders.most_common(8)]
        out += ["", "Sample files:"]
        out += [f"- `{s}`" for names in p.samples.values() for s in names]
        if p.json_summaries:
            out += ["", "JSON files:"]
            out += [f"- `{k}`: {v}" for k, v in p.json_summaries.items()]
    return "\n".join(out) + "\n"
