"""Fast, model-free image quality checks for a microscope field.

These run before any model call. A field that fails a *blocking* check is
excluded from counting and the user is asked to capture another field, which is
what a careful microscopist would do.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage


@dataclass(frozen=True)
class QualityThresholds:
    """Tunable limits. Defaults are starting points, to be calibrated on the datasets."""

    min_sharpness: float = 15.0
    min_brightness: float = 40.0
    max_brightness: float = 235.0
    min_stain_fraction: float = 0.002
    max_stain_fraction: float = 0.60


@dataclass(frozen=True)
class QualityReport:
    """Measured values and the flags they raise."""

    sharpness: float
    brightness: float
    stain_fraction: float
    flags: tuple[str, ...]

    @property
    def usable(self) -> bool:
        """True when no blocking flag was raised."""
        return not any(f.startswith("blocking:") for f in self.flags)


def to_gray(image: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Convert an RGB or grayscale uint8 image to float grayscale."""
    if image.ndim == 2:
        return image.astype(np.float64)
    if image.ndim == 3 and image.shape[2] >= 3:
        rgb = image[..., :3].astype(np.float64)
        return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    raise ValueError(f"unsupported image shape {image.shape}")


def stain_mask(image: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """Pixels that look like Giemsa-stained chromatin (dark, purple-blue).

    Chromatin is darker than the background and its blue channel exceeds green.
    """
    if image.ndim != 3:
        raise ValueError("stain_mask needs an RGB image")
    rgb = image[..., :3].astype(np.int16)
    gray = to_gray(image)
    background = float(np.median(gray))
    dark = gray < background * 0.75
    purple = (rgb[..., 2] - rgb[..., 1]) > 10
    return np.asarray(dark & purple, dtype=np.bool_)


def assess(image: NDArray[np.uint8], thresholds: QualityThresholds | None = None) -> QualityReport:
    """Measure focus, exposure and staining for one field."""
    t = thresholds or QualityThresholds()
    gray = to_gray(image)
    sharpness = float(ndimage.laplace(gray).var())
    brightness = float(gray.mean())
    stain = float(stain_mask(image).mean()) if image.ndim == 3 else 0.0

    flags: list[str] = []
    if sharpness < t.min_sharpness:
        flags.append("blocking: out of focus")
    if brightness < t.min_brightness:
        flags.append("blocking: underexposed")
    elif brightness > t.max_brightness:
        flags.append("blocking: overexposed")
    if stain < t.min_stain_fraction:
        flags.append("warning: very little stained material (pale stain or empty field)")
    elif stain > t.max_stain_fraction:
        flags.append("warning: heavy staining or thick area")
    return QualityReport(sharpness, brightness, stain, tuple(flags))
