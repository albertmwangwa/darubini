import pytest

from darubini.counting import CountStatus, evaluate_slide
from darubini.pipeline import Pipeline, load_image
from darubini.report import render
from darubini.segmentation.baseline import BaselineSegmenter
from darubini.types import BoundingBox, Detection, FieldResult, ObjectClass
from tests.conftest import make_field


def _count(parasites: int, wbcs: int):
    box = BoundingBox(0, 0, 1, 1)
    dets = [Detection(ObjectClass.PARASITE, box)] * parasites + [
        Detection(ObjectClass.WBC, box)
    ] * wbcs
    return evaluate_slide([FieldResult("f", dets)])


@pytest.mark.parametrize(("lang", "word"), [("en", "Estimated density"), ("sw", "msongamano")])
def test_render_languages(lang, word):
    r = render(_count(20, 200), lang)
    assert word in r.text
    assert "800" in r.text  # 20 * 8000 / 200
    assert r.facts["status"] == "complete"


def test_render_without_density():
    r = render(evaluate_slide([]), "en")
    assert "not yet available" in r.text


def test_render_rejects_language():
    with pytest.raises(ValueError):
        render(_count(1, 1), "fr")


def test_pipeline_stops_when_rule_met():
    seg = BaselineSegmenter()
    pipe = Pipeline(segmenter=seg)
    fields = [(f"f{i}", make_field(n_parasites=6, n_wbc=3, seed=i)) for i in range(200)]
    results, count, report = pipe.analyse_slide(iter(fields), language="sw")
    assert count.status is CountStatus.COMPLETE
    assert len(results) < 200  # stopped early
    assert report.language == "sw"


def test_pipeline_skips_segmentation_on_blurred_field():
    pipe = Pipeline(segmenter=BaselineSegmenter())
    res = pipe.analyse_field(make_field(blur=True), "blurry")
    assert not res.usable
    assert res.detections == []


def test_load_image(tmp_path):
    from PIL import Image

    p = tmp_path / "f.png"
    Image.fromarray(make_field()).save(p)
    assert load_image(p).shape == (256, 256, 3)
