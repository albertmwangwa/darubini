import pytest

from darubini.counting import (
    WHO_DEFAULT,
    CountingProtocol,
    CountStatus,
    evaluate_slide,
    parasite_density,
)
from darubini.types import BoundingBox, Detection, FieldResult, ObjectClass


def _field(i: int, parasites: int, wbcs: int, blocked: bool = False) -> FieldResult:
    box = BoundingBox(0, 0, 4, 4)
    dets = [Detection(ObjectClass.PARASITE, box)] * parasites + [
        Detection(ObjectClass.WBC, box)
    ] * wbcs
    flags = ["blocking: out of focus"] if blocked else []
    return FieldResult(field_id=f"f{i}", detections=dets, quality_flags=flags)


def test_density_uses_assumed_wbc():
    assert parasite_density(50, 200) == 2000.0
    assert parasite_density(50, 200, CountingProtocol(assumed_wbc_per_ul=6000)) == 1500.0


@pytest.mark.parametrize(("p", "w"), [(-1, 10), (1, -1), (5, 0)])
def test_density_rejects_bad_counts(p, w):
    with pytest.raises(ValueError):
        parasite_density(p, w)


def test_stops_at_200_wbc_with_enough_parasites():
    fields = [_field(i, 5, 50) for i in range(4)]  # 20 parasites, 200 WBC
    c = evaluate_slide(fields)
    assert c.status is CountStatus.COMPLETE
    assert c.density_per_ul == 20 * 8000 / 200
    assert c.is_positive is True


def test_few_parasites_extends_to_500_wbc():
    fields = [_field(i, 1, 50) for i in range(4)]  # 4 parasites at 200 WBC
    c = evaluate_slide(fields)
    assert c.status is CountStatus.CONTINUE
    assert "500" in c.reason
    assert c.is_positive is None
    fields += [_field(i, 0, 50) for i in range(4, 10)]  # now 500 WBC
    assert evaluate_slide(fields).status is CountStatus.COMPLETE


def test_negative_after_enough_clean_fields():
    fields = [_field(i, 0, 3) for i in range(WHO_DEFAULT.fields_before_negative)]
    c = evaluate_slide(fields)
    assert c.status is CountStatus.NEGATIVE
    assert c.is_positive is False
    assert c.density_per_ul == 0.0


def test_blocked_fields_are_ignored():
    fields = [_field(0, 30, 300, blocked=True), _field(1, 1, 10)]
    c = evaluate_slide(fields)
    assert c.fields_examined == 2
    assert c.usable_fields == 1
    assert c.parasites == 1


def test_empty_slide_continues():
    c = evaluate_slide([])
    assert c.status is CountStatus.CONTINUE
    assert c.density_per_ul is None


def test_continue_reason_before_first_target():
    c = evaluate_slide([_field(0, 2, 20)])
    assert c.status is CountStatus.CONTINUE
    assert "200" in c.reason


@pytest.mark.parametrize(
    "kwargs",
    [
        {"assumed_wbc_per_ul": 0},
        {"first_wbc_target": 600},
        {"first_wbc_target": 0},
        {"fields_before_negative": 0},
    ],
)
def test_protocol_validation(kwargs):
    with pytest.raises(ValueError):
        CountingProtocol(**kwargs)
