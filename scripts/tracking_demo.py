"""Render the SAM 3.1 tracking demo clip and check it against expert labels.

Pans across one NIH *tuning* field (never a test field), counts it with the hybrid
detector and SAM 3.1 video tracking, and writes:

- ``docs/demo/tracking_demo.mp4``: the clip with every track boxed and numbered,
  and the running count of unique objects;
- ``docs/demo/tracking_contact.png``: six frames from it;
- ``docs/demo/tracking_demo.json``: the counts and the check against the labels.

The labels give an automatic version of "duplicates checked by hand": a duplicate
is one labelled object matched by two or more tracks.

Usage: python scripts/tracking_demo.py [--tracker sam|shift] [--frames 90]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from darubini import video
from darubini.config import get_settings
from darubini.data.fields import LabelledField, nlm_thick_fields
from darubini.meta.client import MetaModelClient
from darubini.pipeline import load_image
from darubini.segmentation.base import get_segmenter
from darubini.tracking import SamTracker, ShiftTracker, Track, Tracker, count_clip, sam_cost_usd
from darubini.types import ObjectClass

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "datasets" / "raw" / "nih-thick-pf-150"
OUT = ROOT / "docs" / "demo"
FONT = ROOT / "android" / "app" / "src" / "main" / "res" / "font" / "plus_jakarta_sans.ttf"
SIZE, STEP = (1280, 720), 16
MATCH_PX = 25.0  # NIH labels are 41 px circles; a track matches a label whose centre is this close
COLOURS = {ObjectClass.PARASITE: (233, 30, 140), ObjectClass.WBC: (59, 130, 246)}
SEED = 0


def pan_origin(shape: tuple[int, ...], frames: int) -> tuple[int, int]:
    """Top-left corner of the first frame, as ``video.synthetic_pan`` places it."""
    w, h = SIZE
    return max(0, (shape[1] - w - STEP * (frames - 1)) // 2), max(0, (shape[0] - h) // 2)


def in_eyepiece(x: float, y: float) -> bool:
    """Is a point (frame coordinates) inside the eyepiece circle ``synthetic_pan`` leaves?"""
    w, h = SIZE
    return (x - w / 2) ** 2 + (y - h / 2) ** 2 <= (0.48 * min(w, h)) ** 2


def visible(cx: float, cy: float, x0: int, y0: int, frames: int) -> bool:
    """Is a point (image coordinates) inside the eyepiece circle in at least one frame?"""
    return any(in_eyepiece(cx - x0 - i * STEP, cy - y0) for i in range(frames))


def labels_in_view(
    f: LabelledField, shape: tuple[int, ...], frames: int
) -> list[tuple[ObjectClass, float, float]]:
    x0, y0 = pan_origin(shape, frames)
    return [(d.cls, *d.box.center) for d in f.truth if visible(*d.box.center, x0, y0, frames)]


def pick_field(frames: int) -> tuple[LabelledField, np.ndarray]:
    """First tuning field (seeded order) with a demo-friendly 8 to 25 parasites in view."""
    fields = nlm_thick_fields(RAW, "tune")
    random.Random(SEED).shuffle(fields)
    for f in fields:
        if sum(d.cls is ObjectClass.PARASITE for d in f.truth) < 8:
            continue
        image = load_image(f.image)
        n = sum(c is ObjectClass.PARASITE for c, *_ in labels_in_view(f, image.shape, frames))
        if 8 <= n <= 25:
            return f, image
    sys.exit("no suitable tuning field")


def check(tracks: tuple[Track, ...], labels: list, x0: int, y0: int) -> dict[str, dict[str, int]]:
    """Match each track (at its first frame, in image coordinates) to the nearest label."""
    out: dict[str, dict[str, int]] = {}
    for cls in (ObjectClass.PARASITE, ObjectClass.WBC):
        truth = np.array([(x, y) for c, x, y in labels if c is cls]).reshape(-1, 2)
        hits: dict[int, list[int]] = {}  # label -> first frame of each track matched to it
        unmatched = 0
        for t in (t for t in tracks if t.cls is cls):
            f = t.first_frame
            cx, cy = t.boxes[f].center
            p = np.array([cx + x0 + f * STEP, cy + y0])
            d = np.hypot(*(truth - p).T) if len(truth) else np.array([])
            if len(d) and d.min() <= MATCH_PX:
                hits.setdefault(int(d.argmin()), []).append(f)
            else:
                unmatched += 1
        duplicates = sum(len(v) - 1 for v in hits.values())
        # Tracks of one object that start on different keyframes are tracking failures; two
        # starting on the same keyframe are the detector boxing one object twice.
        across = sum(len(set(v)) - 1 for v in hits.values())
        out[cls.value] = {
            "labelled_in_view": len(truth),
            "tracks": sum(t.cls is cls for t in tracks),
            "matched_labels": len(hits),
            "duplicates_across_frames": across,
            "duplicates_within_a_frame": duplicates - across,
            "unmatched_tracks": unmatched,
            "missed_labels": len(truth) - len(hits),
        }
    return out


def render(
    frames: list[np.ndarray], tracks: tuple[Track, ...], naive: dict[ObjectClass, int]
) -> list[np.ndarray]:
    big = ImageFont.truetype(str(FONT), 30)
    small = ImageFont.truetype(str(FONT), 20)
    out = []
    for i, frame in enumerate(frames):
        im = Image.fromarray(frame)
        draw = ImageDraw.Draw(im)
        for t in tracks:
            box = t.boxes.get(i)
            if box is None or not in_eyepiece(*box.center):
                continue
            colour = COLOURS[t.cls]
            draw.rectangle((box.x_min, box.y_min, box.x_max, box.y_max), outline=colour, width=3)
            draw.text((box.x_min, box.y_min - 22), f"#{t.track_id}", fill=colour, font=small)
        seen = [t for t in tracks if t.first_frame <= i]
        p = sum(t.cls is ObjectClass.PARASITE for t in seen)
        w = sum(t.cls is ObjectClass.WBC for t in seen)
        draw.rounded_rectangle((20, 20, 470, 120), radius=16, fill=(21, 26, 23))
        draw.text((40, 30), f"Parasites  {p}", fill=COLOURS[ObjectClass.PARASITE], font=big)
        draw.text((40, 72), f"White cells  {w}", fill=(147, 197, 253), font=big)
        if i == len(frames) - 1:
            note = (
                f"Counted once each. Frame by frame: {naive.get(ObjectClass.PARASITE, 0)} parasites, "
                f"{naive.get(ObjectClass.WBC, 0)} white cells"
            )
            draw.rounded_rectangle((20, 650, 1260, 700), radius=14, fill=(33, 87, 50))
            draw.text((40, 660), note, fill=(255, 255, 255), font=small)
        out.append(np.asarray(im))
    # Hold the last frame for 2 s so the summary can be read.
    return out + [out[-1]] * 30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", choices=("sam", "shift"), default="sam")
    ap.add_argument("--frames", type=int, default=90)
    args = ap.parse_args()

    settings = get_settings().model_copy(update={"segmenter": "hybrid"})
    field, image = pick_field(args.frames)
    frames = video.synthetic_pan(
        image, size=SIZE, frames=args.frames, step=(STEP, 0), eyepiece=True
    )
    tracker: Tracker = (
        SamTracker(MetaModelClient.from_settings(settings), settings.meta_segmentation_model)
        if args.tracker == "sam"
        else ShiftTracker()
    )
    clip = count_clip(frames, get_segmenter(settings), tracker, keyframe_every=10)

    x0, y0 = pan_origin(image.shape, args.frames)
    facts: dict[str, object] = {
        "field": f"{field.patient}/{field.image.name}",
        "split": "tune",
        "frames": clip.frames,
        "keyframes": len(clip.keyframes),
        "tracker": tracker.name,
        "unique_parasites": clip.parasites,
        "unique_wbcs": clip.wbcs,
        "naive_parasites": clip.naive.get(ObjectClass.PARASITE, 0),
        "naive_wbcs": clip.naive.get(ObjectClass.WBC, 0),
        "against_labels": check(
            clip.tracks, labels_in_view(field, image.shape, args.frames), x0, y0
        ),
    }
    if isinstance(tracker, SamTracker):
        facts["sam_usd"] = round(sam_cost_usd(tracker.frames_sent), 3)

    OUT.mkdir(parents=True, exist_ok=True)
    rendered = render(frames, clip.tracks, clip.naive)
    (OUT / "tracking_demo.mp4").write_bytes(video.encode(rendered, crf=26))
    picks = [rendered[i] for i in np.linspace(0, len(frames) - 1, 6).astype(int)]
    thumbs = [Image.fromarray(p).resize((640, 360)) for p in picks]
    sheet = Image.new("RGB", (1280, 1080))
    for n, t in enumerate(thumbs):
        sheet.paste(t, ((n % 2) * 640, (n // 2) * 360))
    sheet.save(OUT / "tracking_contact.png", optimize=True)
    (OUT / "tracking_demo.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(facts, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
