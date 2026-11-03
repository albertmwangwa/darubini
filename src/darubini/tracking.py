"""Count each parasite and white blood cell once across a panning eyepiece video.

A technician pans the slide while the phone records. Counting every frame would
count one parasite many times, so Darubini detects objects on keyframes and
follows each new one forward through the clip:

1. Run the field segmenter on a keyframe.
2. Drop detections that land on an object already being tracked.
3. Hand the remaining (new) boxes to a tracker, which follows them forward.

Each track is counted once. :class:`SamTracker` uses SAM 3.1 box prompts on the
video (up to 16 objects per request); :class:`ShiftTracker` is an offline
fallback that follows the global pan by phase correlation.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from darubini.meta.client import MetaModelClient
from darubini.segmentation.base import Segmenter
from darubini.types import BoundingBox, Detection, FieldResult, ObjectClass
from darubini.video import Frame, encode, resize_to

log = logging.getLogger(__name__)

#: SAM 3.1 accepts at most 16 prompted objects per video request.
SAM_MAX_OBJECTS = 16
#: SAM bills video per frame with a 50-frame minimum per request.
SAM_MIN_BILLED_FRAMES = 50
SAM_USD_PER_FRAME = 0.0002

BoxPath = dict[int, BoundingBox]


class Tracker(Protocol):
    """Follows boxes forward from one frame of a clip."""

    name: str

    def propagate(
        self, frames: Sequence[Frame], start: int, boxes: Sequence[BoundingBox]
    ) -> list[BoxPath]:
        """Return, for each box, its box on every later frame where it is still visible."""
        ...


@dataclass(frozen=True)
class Track:
    """One object followed through the clip."""

    track_id: int
    cls: ObjectClass
    score: float
    boxes: dict[int, BoundingBox]

    @property
    def first_frame(self) -> int:
        """Frame where the object was first detected."""
        return min(self.boxes)


@dataclass(frozen=True)
class ClipCount:
    """Unique objects in a clip, plus the naive per-keyframe total for comparison."""

    frames: int
    keyframes: tuple[int, ...]
    tracks: tuple[Track, ...]
    naive: dict[ObjectClass, int] = field(default_factory=dict)

    def unique(self, cls: ObjectClass) -> int:
        """Objects of ``cls`` counted once each."""
        return sum(1 for t in self.tracks if t.cls is cls)

    @property
    def parasites(self) -> int:
        """Unique parasites in the clip."""
        return self.unique(ObjectClass.PARASITE)

    @property
    def wbcs(self) -> int:
        """Unique white blood cells in the clip."""
        return self.unique(ObjectClass.WBC)

    def as_field_result(self, field_id: str) -> FieldResult:
        """One detection per track, so a clip feeds the counting rule like a field."""
        detections = [
            Detection(t.cls, t.boxes[t.first_frame], t.score, source="track") for t in self.tracks
        ]
        return FieldResult(field_id=field_id, detections=detections)


#: Pixels of slack when matching a detection to a tracked box. Parasite boxes can
#: be 5 px wide, so a few pixels of tracking drift would otherwise split a track.
MATCH_TOLERANCE_PX = 6.0


def same_object(a: BoundingBox, b: BoundingBox, tol: float = MATCH_TOLERANCE_PX) -> bool:
    """Return True when either box's centre lies inside the other, grown by ``tol`` px."""

    def inside(p: tuple[float, float], box: BoundingBox) -> bool:
        return (
            box.x_min - tol <= p[0] <= box.x_max + tol
            and box.y_min - tol <= p[1] <= box.y_max + tol
        )

    return inside(a.center, b) or inside(b.center, a)


def keyframe_indices(n_frames: int, every: int) -> tuple[int, ...]:
    """Every ``every``-th frame, always including the last one."""
    if n_frames <= 0:
        return ()
    if every <= 0:
        raise ValueError("keyframe interval must be positive")
    keys = list(range(0, n_frames, every))
    if keys[-1] != n_frames - 1:
        keys.append(n_frames - 1)
    return tuple(keys)


def count_clip(
    frames: Sequence[Frame],
    segmenter: Segmenter,
    tracker: Tracker,
    keyframe_every: int = 10,
    classes: Sequence[ObjectClass] = (ObjectClass.PARASITE, ObjectClass.WBC),
) -> ClipCount:
    """Detect on keyframes and track new objects forward, counting each once."""
    keys = keyframe_indices(len(frames), keyframe_every)
    tracks: list[Track] = []
    naive = {cls: 0 for cls in classes}
    for k in keys:
        detections = [d for d in segmenter.segment(np.asarray(frames[k])) if d.cls in classes]
        new: list[Detection] = []
        for d in detections:
            naive[d.cls] += 1
            seen = any(
                t.cls is d.cls and k in t.boxes and same_object(t.boxes[k], d.box) for t in tracks
            )
            if not seen:
                new.append(d)
        if not new:
            continue
        paths = tracker.propagate(frames, k, [d.box for d in new]) if k < len(frames) - 1 else []
        for i, d in enumerate(new):
            boxes = {k: d.box}
            if i < len(paths):
                boxes.update({f: b for f, b in paths[i].items() if f > k})
            tracks.append(Track(len(tracks), d.cls, d.score, boxes))
        log.info("keyframe %d: %d detections, %d new", k, len(detections), len(new))
    return ClipCount(len(frames), keys, tuple(tracks), naive)


# ---- trackers ----


def _box_or_none(x1: float, y1: float, x2: float, y2: float) -> BoundingBox | None:
    return BoundingBox(x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def box_token(box: BoundingBox, scale: float, w: int, h: int) -> str:
    """Box corners for a SAM prompt: whole pixels, inside the frame (SAM rejects x2 == w)."""
    x1 = min(max(0, math.floor(box.x_min * scale)), w - 2)
    y1 = min(max(0, math.floor(box.y_min * scale)), h - 2)
    x2 = max(min(w - 1, math.ceil(box.x_max * scale)), x1 + 1)
    y2 = max(min(h - 1, math.ceil(box.y_max * scale)), y1 + 1)
    return f"x1={x1};y1={y1};x2={x2};y2={y2}"


@dataclass
class SamTracker:
    """Follows boxes with SAM 3.1 video object prompts.

    Clips are downscaled to ``max_side`` before upload; boxes are mapped back.
    """

    client: MetaModelClient
    model: str
    max_side: int = 1280
    fps: int = 15
    name: str = "sam3-video"
    #: Video frames billed so far (cache misses only are actually charged).
    frames_sent: int = 0

    def propagate(
        self, frames: Sequence[Frame], start: int, boxes: Sequence[BoundingBox]
    ) -> list[BoxPath]:
        """Prompt each box on ``start`` and let SAM follow it forward."""
        if not boxes:
            return []
        clip = [resize_to(np.asarray(f), self.max_side) for f in frames[start:]]
        scale = clip[0].shape[1] / np.asarray(frames[start]).shape[1]
        mp4 = encode(clip, fps=self.fps)
        h, w = clip[0].shape[0] - clip[0].shape[0] % 2, clip[0].shape[1] - clip[0].shape[1] % 2
        paths: list[BoxPath] = []
        for lo in range(0, len(boxes), SAM_MAX_OBJECTS):
            batch = boxes[lo : lo + SAM_MAX_OBJECTS]
            prompt = "<0f>" + ",".join(
                f"{i}<|box;{box_token(b, scale, w, h)};w={w};h={h}|>" for i, b in enumerate(batch)
            )
            replies = self.client.segment_video(
                mp4, prompt, self.model, {"propagation_direction": "forward"}
            )
            self.frames_sent += max(len(clip), SAM_MIN_BILLED_FRAMES)
            batch_paths: list[BoxPath] = [{} for _ in batch]
            for r in replies:
                if not 0 <= r.object_id < len(batch):
                    continue
                box = _box_or_none(*(v / scale for v in r.box_xyxy))
                if box is not None:
                    batch_paths[r.object_id][start + r.frame] = box
            paths.extend(batch_paths)
        return paths


def _centre_grey(frame: Frame, crop: int) -> NDArray[np.float64]:
    g = np.empty(frame.shape[:2], dtype=np.float64)
    np.mean(frame, axis=2, dtype=np.float64, out=g)
    h, w = g.shape
    y0, x0 = max(0, (h - crop) // 2), max(0, (w - crop) // 2)
    return g[y0 : y0 + crop, x0 : x0 + crop]


def estimate_shift(a: Frame, b: Frame, crop: int = 512) -> tuple[float, float]:
    """Estimate how far content moved from frame ``a`` to frame ``b``, as (dx, dy) pixels.

    Phase correlation on a full-resolution central crop; good for the near-pure
    translation of panning a slide, up to about half the crop per call.
    """
    ga, gb = _centre_grey(a, crop), _centre_grey(b, crop)
    window = np.outer(np.hanning(ga.shape[0]), np.hanning(ga.shape[1]))
    fa = np.fft.fft2((ga - ga.mean()) * window)
    fb = np.fft.fft2((gb - gb.mean()) * window)
    cross = fb * np.conj(fa)
    corr = np.fft.ifft2(cross / (np.abs(cross) + 1e-9)).real
    py, px = np.unravel_index(int(np.argmax(corr)), corr.shape)
    ny, nx = corr.shape
    # Parabolic fit through the peak and its neighbours gives sub-pixel precision,
    # which matters because errors add up frame after frame.
    fy = py + _peak_offset(corr[(py - 1) % ny, px], corr[py, px], corr[(py + 1) % ny, px])
    fx = px + _peak_offset(corr[py, (px - 1) % nx], corr[py, px], corr[py, (px + 1) % nx])
    dy = fy - ny if fy > ny / 2 else fy
    dx = fx - nx if fx > nx / 2 else fx
    return float(dx), float(dy)


def _peak_offset(left: float, centre: float, right: float) -> float:
    denom = left - 2 * centre + right
    return 0.0 if denom == 0 else float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5))


@dataclass
class ShiftTracker:
    """Offline tracker: moves boxes with the estimated global pan between frames."""

    name: str = "shift"
    #: Side of the central crop used for registration.
    crop: int = 512

    def propagate(
        self, frames: Sequence[Frame], start: int, boxes: Sequence[BoundingBox]
    ) -> list[BoxPath]:
        """Shift every box by the accumulated pan until its centre leaves the frame."""
        paths: list[BoxPath] = [{} for _ in boxes]
        alive = list(range(len(boxes)))
        h, w = np.asarray(frames[start]).shape[:2]
        # Register each frame to a reference frame rather than to its neighbour, so
        # errors do not add up; move the reference once the pan nears the crop limit.
        ref, ref_ox, ref_oy = start, 0.0, 0.0
        for f in range(start + 1, len(frames)):
            dx, dy = estimate_shift(frames[ref], frames[f], self.crop)
            ox, oy = ref_ox + dx, ref_oy + dy
            if max(abs(dx), abs(dy)) > self.crop / 4:
                ref, ref_ox, ref_oy = f, ox, oy
            still = []
            for i in alive:
                b = boxes[i]
                cx, cy = b.center[0] + ox, b.center[1] + oy
                if not (0 <= cx < w and 0 <= cy < h):
                    continue
                moved = _box_or_none(b.x_min + ox, b.y_min + oy, b.x_max + ox, b.y_max + oy)
                if moved is not None:
                    paths[i][f] = moved
                    still.append(i)
            alive = still
        return paths


def sam_cost_usd(frames_sent: int) -> float:
    """US dollars for SAM video frames at list price."""
    return frames_sent * SAM_USD_PER_FRAME
