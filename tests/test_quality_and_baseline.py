import numpy as np
import pytest

from darubini.quality import QualityThresholds, assess, stain_mask, to_gray
from darubini.segmentation.baseline import BaselineSegmenter
from darubini.types import ObjectClass
from tests.conftest import make_field


def test_good_field_is_usable(field):
    report = assess(field)
    assert report.usable, report.flags
    assert 0 < report.stain_fraction < 0.6


def test_blurred_field_is_blocked():
    report = assess(make_field(blur=True))
    assert "blocking: out of focus" in report.flags
    assert not report.usable


def test_exposure_flags():
    dark = np.full((64, 64, 3), 10, dtype=np.uint8)
    bright = np.full((64, 64, 3), 250, dtype=np.uint8)
    loose = QualityThresholds(min_sharpness=0)
    assert "blocking: underexposed" in assess(dark, loose).flags
    assert "blocking: overexposed" in assess(bright, loose).flags


def test_heavy_stain_warning():
    img = make_field(n_parasites=0, n_wbc=0)
    img[:, :100] = (60, 30, 120)  # ~40% of the field, below the median
    flags = assess(img, QualityThresholds(min_sharpness=0, max_stain_fraction=0.3)).flags
    assert any("heavy staining" in f for f in flags)


def test_gray_and_mask_shapes(field):
    assert to_gray(field).shape == field.shape[:2]
    assert to_gray(field[..., 0]).shape == field.shape[:2]
    with pytest.raises(ValueError):
        to_gray(np.zeros((2, 2, 2), dtype=np.uint8))
    with pytest.raises(ValueError):
        stain_mask(field[..., 0])


@pytest.mark.parametrize(("parasites", "wbcs"), [(5, 2), (0, 3), (8, 0)])
def test_baseline_counts_synthetic_objects(parasites, wbcs):
    dets = BaselineSegmenter().segment(make_field(n_parasites=parasites, n_wbc=wbcs, seed=3))
    assert sum(d.cls is ObjectClass.PARASITE for d in dets) == parasites
    assert sum(d.cls is ObjectClass.WBC for d in dets) == wbcs


def test_baseline_empty_field():
    blank = np.full((64, 64, 3), 220, dtype=np.uint8)
    assert BaselineSegmenter().segment(blank) == []
