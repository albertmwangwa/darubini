from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from darubini.calibration import (
    BLUR_SIGMAS,
    DatasetSurvey,
    field_images,
    render,
    suggest_min_sharpness,
    survey,
)
from darubini.cli import main
from darubini.quality import FOCUS_WORKING_SIDE, QualityThresholds, focus_gray, sharpness
from tests.conftest import make_field

ROOT = Path(__file__).resolve().parents[1]


def _write_fields(root: Path, n: int = 4) -> None:
    (root / "slide1").mkdir(parents=True)
    (root / "Thin_Infected").mkdir()
    (root / "slide1" / "crops").mkdir()
    for i in range(n):
        Image.fromarray(make_field(seed=i)).save(root / "slide1" / f"f{i}.png")
    Image.fromarray(make_field()).save(root / "Thin_Infected" / "t.png")
    Image.fromarray(make_field()).save(root / "slide1" / "crops" / "c.png")
    (root / "slide1" / "f0.xml").write_text("<annotation/>")


def test_focus_is_measured_at_working_size():
    big = np.zeros((FOCUS_WORKING_SIDE * 2, FOCUS_WORKING_SIDE, 3), dtype=np.uint8)
    assert focus_gray(big).shape == (FOCUS_WORKING_SIDE, FOCUS_WORKING_SIDE // 2)
    small = make_field(n_parasites=1, size=128)
    assert focus_gray(small).shape == (128, 128)
    assert sharpness(make_field()) > sharpness(make_field(blur=True))


def test_field_images_skips_thin_and_crops(tmp_path):
    _write_fields(tmp_path)
    names = [p.name for p in field_images(tmp_path)]
    assert names == ["f0.png", "f1.png", "f2.png", "f3.png"]


def test_survey_measures_fields_and_blur(tmp_path):
    _write_fields(tmp_path)
    s = survey("toy", tmp_path, sample=3, thresholds=QualityThresholds())
    assert s.n == 3
    assert s.reject_rate() == 0.0
    for sigma in BLUR_SIGMAS:
        assert len(s.blurred_sharpness[sigma]) == 3
        assert max(s.blurred_sharpness[sigma]) < min(s.sharpness)
    assert s.blur_catch_rate(BLUR_SIGMAS[-1], min_sharpness=1e9) == 1.0
    assert s.blur_catch_rate(99.0, min_sharpness=1e9) == 0.0
    text = render([s], QualityThresholds())
    assert "| toy | 3 | 0.0% |" in text


def test_suggest_min_sharpness_uses_lowest_dataset():
    a = DatasetSurvey("a", sharpness=[float(v) for v in range(10, 110)])
    b = DatasetSurvey("b", sharpness=[3.7] + [50.0] * 99)
    assert suggest_min_sharpness([a, b], max_reject=0.01) == 3.5
    assert DatasetSurvey("e").reject_rate() == 0.0
    with pytest.raises(ValueError):
        suggest_min_sharpness([DatasetSurvey("e")])


def test_cli_calibrate(tmp_path, capsys):
    raw = tmp_path / "raw"
    _write_fields(raw / "udom-tz-thick")
    out = tmp_path / "q.md"
    args = ["calibrate", "--manifest", str(ROOT / "datasets/manifest.yaml"), "--raw-dir", str(raw)]
    assert main([*args, "--sample", "2", "--min-sharpness", "1", "--out", str(out)]) == 0
    assert "Suggested min_sharpness" in capsys.readouterr().out
    assert "udom-tz-thick" in out.read_text(encoding="utf-8")
    assert main([*args, "--only", "nm-aist-tz", "--out", str(out)]) == 2
