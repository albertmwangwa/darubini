"""Read and write short MP4 clips of a panning microscope field (PyAV, which bundles ffmpeg)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

Frame = NDArray[np.uint8]


def _av() -> Any:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError("video support needs PyAV: pip install av") from exc
    return av


def decode(
    source: bytes | Path, max_frames: int | None = None, max_side: int | None = None
) -> list[Frame]:
    """Decode a video into RGB frames.

    Args:
        source: video bytes or a file path (MP4, MOV, WebM; anything ffmpeg reads).
        max_frames: keep at most this many frames, sampled evenly across the clip.
        max_side: downscale frames so their long side is at most this.

    """
    av = _av()
    stream = io.BytesIO(source) if isinstance(source, bytes) else str(source)
    with av.open(stream) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    if max_frames is not None and len(frames) > max_frames:
        keep = np.linspace(0, len(frames) - 1, max_frames).round().astype(int)
        frames = [frames[i] for i in keep]
    if max_side is not None:
        frames = [resize_to(f, max_side) for f in frames]
    return frames


def resize_to(frame: Frame, max_side: int) -> Frame:
    """Downscale a frame so its long side is at most ``max_side`` (never upscales)."""
    h, w = frame.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return frame
    size = (max(2, round(w * scale)), max(2, round(h * scale)))
    return np.asarray(Image.fromarray(frame).resize(size, Image.Resampling.BILINEAR))


def encode(frames: list[Frame], fps: int = 15, crf: int = 20) -> bytes:
    """Encode RGB frames as an H.264 MP4, the format SAM 3.1 accepts.

    H.264 needs even dimensions, so a frame with an odd side loses its last row or
    column.
    """
    if not frames:
        raise ValueError("no frames to encode")
    av = _av()
    h, w = frames[0].shape[:2]
    h, w = h - h % 2, w - w % 2
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        stream.options = {"crf": str(crf)}
        for frame in frames:
            vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(frame[:h, :w]), format="rgb24")
            for packet in stream.encode(vf):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return buf.getvalue()


def synthetic_pan(
    image: Frame,
    size: tuple[int, int] = (1280, 720),
    frames: int = 60,
    step: tuple[int, int] = (16, 0),
    eyepiece: bool = False,
) -> list[Frame]:
    """Cut a panning clip out of one large field image, for demos and tests.

    Args:
        image: a field larger than ``size``.
        size: (width, height) of each frame.
        frames: number of frames.
        step: (dx, dy) pixels the window moves per frame.
        eyepiece: black out everything outside a fixed central circle, as a phone
            held to the eyepiece sees it.

    """
    w, h = size
    dx, dy = step
    x0 = max(0, (image.shape[1] - w - dx * (frames - 1)) // 2)
    y0 = max(0, (image.shape[0] - h - dy * (frames - 1)) // 2)
    if x0 + w + dx * (frames - 1) > image.shape[1] or y0 + h + dy * (frames - 1) > image.shape[0]:
        raise ValueError("image is too small for that pan")
    clip = [
        image[y0 + i * dy : y0 + i * dy + h, x0 + i * dx : x0 + i * dx + w] for i in range(frames)
    ]
    if not eyepiece:
        return clip
    yy, xx = np.mgrid[:h, :w]
    outside = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 > (0.48 * min(w, h)) ** 2
    masked = []
    for frame in clip:
        frame = frame.copy()
        frame[outside] = 0
        masked.append(frame)
    return masked
