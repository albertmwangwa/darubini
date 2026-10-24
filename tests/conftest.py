"""Shared fixtures: synthetic Giemsa-like thick-smear fields."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

BACKGROUND = (226, 204, 214)  # pale pink plasma
STAIN = (92, 52, 140)  # purple-blue chromatin


def make_field(
    n_parasites: int = 5,
    n_wbc: int = 2,
    size: int = 256,
    seed: int = 0,
    blur: bool = False,
) -> NDArray[np.uint8]:
    """Draw a field with small parasite dots and large WBC nuclei on a pink background."""
    rng = np.random.default_rng(seed)
    img = np.empty((size, size, 3), dtype=np.float64)
    img[:] = BACKGROUND
    yy, xx = np.mgrid[0:size, 0:size]

    def disk(cx: float, cy: float, r: float) -> None:
        img[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = STAIN

    # place objects on a coarse grid so they never touch
    cells = [(x, y) for y in range(24, size - 24, 48) for x in range(24, size - 24, 48)]
    order = rng.permutation(len(cells))
    for k in range(n_wbc):
        cx, cy = cells[order[k]]
        disk(cx, cy, 14)
    for k in range(n_wbc, n_wbc + n_parasites):
        cx, cy = cells[order[k]]
        disk(cx, cy, 3)

    img += rng.normal(0, 6, img.shape)  # sensor noise keeps the field "in focus"
    if blur:
        from scipy import ndimage

        img = ndimage.uniform_filter(img, size=(15, 15, 1))
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.fixture
def field() -> NDArray[np.uint8]:
    return make_field()
