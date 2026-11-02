"""Fast, model-free image quality checks for a microscope field.

These run before any model call. A field that fails a *blocking* check is
excluded from counting and the user is asked to capture another field, which is
what a careful microscopist would do.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy import ndimage

#: Focus is measured after downscaling the long side to this many pixels, so a
#: 4K phone photo and a 750 px crop of the same field score alike.
FOCUS_WORKING_SIDE = 1024
#: Gray level below which a pixel is outside the eyepiece's field of view. Phone
#: photos through an eyepiece show a bright disc on black; only the disc is measured.
FIELD_OF_VIEW_MIN_GRAY = 25.0
#: Focus ignores pixels this close (working-size pixels) to the field-of-view rim,
#: whose bright halo would otherwise make any field look sharp.
FIELD_OF_VIEW_MARGIN = 30.0


@dataclass(frozen=True)
class QualityThresholds:
    """Tunable limits.

    ``min_sharpness`` comes from ``darubini calibrate`` (docs/calibration/quality.md):
    a floor that expert-annotated fields from every dataset clear, so it blocks only
    clearly defocused fields. Sharp fields differ more between cameras than sharp and
    blurred fields do within one camera, so no single threshold can be tight.
    """

    min_sharpness: float = 1.5
    min_brightness: float = 40.0
    max_brightness: float = 235.0
    min_stain_fraction: float = 0.002
    max_stain_fraction: float = 0.60
    min_field_of_view: float = 0.5


@dataclass(frozen=True)
class QualityReport:
    """Measured values and the flags they raise."""

    sharpness: float
    brightness: float
    stain_fraction: float
    flags: tuple[str, ...]
    #: Share of the image inside the illuminated field of view.
    field_of_view: float = 1.0

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


def focus_gray(image: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Grayscale image at the focus working size (downscaled only, never enlarged)."""
    h, w = image.shape[:2]
    scale = FOCUS_WORKING_SIDE / max(h, w)
    if scale >= 1:
        return to_gray(image)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    small = Image.fromarray(image).resize(size, Image.Resampling.LANCZOS)
    return to_gray(np.asarray(small, dtype=np.uint8))


def field_of_view(gray: NDArray[np.float64]) -> NDArray[np.bool_]:
    """Pixels inside the illuminated field of view (not the black eyepiece surround)."""
    return np.asarray(gray > FIELD_OF_VIEW_MIN_GRAY, dtype=np.bool_)


def focus_score(gray: NDArray[np.float64]) -> float:
    """Variance of the Laplacian inside the field of view, away from its sharp rim."""
    lap = ndimage.laplace(gray)
    fov = field_of_view(gray)
    inside = fov if fov.all() else ndimage.distance_transform_edt(fov) > FIELD_OF_VIEW_MARGIN
    if inside.sum() < 100:
        return float(lap.var())
    return float(lap[inside].var())


def sharpness(image: NDArray[np.uint8]) -> float:
    """Focus score at the focus working size; higher is sharper."""
    return focus_score(focus_gray(image))


def stain_mask(image: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """Pixels that look like Giemsa-stained chromatin (dark, purple-blue).

    Chromatin is darker than the background and its blue channel exceeds green.
    """
    if image.ndim != 3:
        raise ValueError("stain_mask needs an RGB image")
    rgb = image[..., :3].astype(np.int16)
    gray = to_gray(image)
    fov = field_of_view(gray)
    background = float(np.median(gray[fov] if fov.any() else gray))
    dark = gray < background * 0.75
    purple = (rgb[..., 2] - rgb[..., 1]) > 10
    return np.asarray(dark & purple, dtype=np.bool_)


def assess(image: NDArray[np.uint8], thresholds: QualityThresholds | None = None) -> QualityReport:
    """Measure focus, exposure and staining for one field."""
    t = thresholds or QualityThresholds()
    gray = to_gray(image)
    fov = field_of_view(gray)
    fov_fraction = float(fov.mean())
    focus = sharpness(image)
    brightness = float(gray[fov].mean()) if fov.any() else float(gray.mean())
    stain = 0.0
    if image.ndim == 3:
        stained = stain_mask(image)
        stain = float(stained[fov].mean()) if fov.any() else float(stained.mean())

    flags: list[str] = []
    if focus < t.min_sharpness:
        flags.append("blocking: out of focus")
    if brightness < t.min_brightness:
        flags.append("blocking: underexposed")
    elif brightness > t.max_brightness:
        flags.append("blocking: overexposed")
    if stain < t.min_stain_fraction:
        flags.append("warning: very little stained material (pale stain or empty field)")
    elif stain > t.max_stain_fraction:
        flags.append("warning: heavy staining or thick area")
    if fov_fraction < t.min_field_of_view:
        flags.append(f"warning: field of view covers only {fov_fraction:.0%} of the image")
    return QualityReport(focus, brightness, stain, tuple(flags), fov_fraction)


#: What each blocking problem tells the technician, in the app's languages.
BLOCKING_TEXT = {
    "out of focus": {"en": "out of focus", "sw": "picha haijalenga vizuri (focus)"},
    "underexposed": {"en": "too dark", "sw": "mwanga hautoshi"},
    "overexposed": {"en": "too bright", "sw": "mwanga mwingi kupita kiasi"},
}


def blocking_text(flags: Sequence[str], language: str = "en") -> list[str]:
    """Translate a field's blocking flags for the retake prompt in ``en`` or ``sw``.

    Flags the table does not know (an agent exclusion, say) are shown as they are.
    """
    out = []
    for flag in flags:
        if not flag.startswith("blocking:"):
            continue
        key = flag.removeprefix("blocking:").strip()
        out.append(BLOCKING_TEXT.get(key, {}).get(language, key))
    return out
