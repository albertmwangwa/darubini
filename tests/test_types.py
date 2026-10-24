import pytest

from darubini.types import BoundingBox, Detection, FieldResult, ObjectClass


def test_box_geometry():
    b = BoundingBox(0, 0, 10, 20)
    assert (b.width, b.height, b.area, b.center) == (10, 20, 200, (5, 10))


def test_iou():
    a = BoundingBox(0, 0, 10, 10)
    assert a.iou(a) == 1.0
    assert a.iou(BoundingBox(5, 0, 15, 10)) == pytest.approx(50 / 150)
    assert a.iou(BoundingBox(20, 20, 30, 30)) == 0.0


def test_degenerate_box_rejected():
    with pytest.raises(ValueError):
        BoundingBox(5, 5, 5, 10)


def test_score_range():
    with pytest.raises(ValueError):
        Detection(ObjectClass.WBC, BoundingBox(0, 0, 1, 1), score=1.5)


def test_field_counts_and_usable():
    box = BoundingBox(0, 0, 1, 1)
    f = FieldResult(
        "a",
        [Detection(ObjectClass.PARASITE, box), Detection(ObjectClass.WBC, box)],
        ["warning: pale"],
    )
    assert (f.parasites, f.wbcs, f.usable) == (1, 1, True)
    f.quality_flags.append("blocking: overexposed")
    assert f.usable is False
