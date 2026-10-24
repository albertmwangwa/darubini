import pytest

from darubini.evaluation import count_agreement, match_detections, slide_accuracy
from darubini.types import BoundingBox, Detection, ObjectClass

P = ObjectClass.PARASITE


def _d(x: float, score: float = 1.0) -> Detection:
    return Detection(P, BoundingBox(x, 0, x + 10, 10), score=score)


def test_match_detections():
    truth = [_d(0), _d(100)]
    pred = [_d(1, 0.9), _d(2, 0.8), _d(300, 0.7)]
    s = match_detections(pred, truth, P)
    assert (s.true_positives, s.false_positives, s.false_negatives) == (1, 2, 1)
    assert s.precision == pytest.approx(1 / 3)
    assert s.recall == 0.5
    assert s.f1 == pytest.approx(0.4)


def test_empty_scores_are_zero():
    s = match_detections([], [], P)
    assert (s.precision, s.recall, s.f1) == (0.0, 0.0, 0.0)


def test_count_agreement():
    a = count_agreement([10, 20, 30], [12, 18, 30])
    assert a.mae == pytest.approx(4 / 3)
    assert a.mean_bias == 0
    assert a.pearson_r is not None and a.pearson_r > 0.95
    assert count_agreement([5], [5]).pearson_r is None
    assert count_agreement([5, 5], [1, 2]).pearson_r is None
    with pytest.raises(ValueError):
        count_agreement([1], [1, 2])
    with pytest.raises(ValueError):
        count_agreement([], [])


def test_slide_accuracy():
    s = slide_accuracy([True, True, False, False], [True, False, False, True])
    assert (s.tp, s.fp, s.tn, s.fn) == (1, 1, 1, 1)
    assert s.sensitivity == 0.5 and s.specificity == 0.5
    assert slide_accuracy([], []).sensitivity == 0.0
    with pytest.raises(ValueError):
        slide_accuracy([True], [])
