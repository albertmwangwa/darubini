from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import SecretStr

from darubini.benchmark import compare_on_fields, render_comparison
from darubini.cli import main
from darubini.config import Settings
from darubini.data.fields import patient_split
from darubini.segmentation.base import get_segmenter
from darubini.segmentation.baseline import BaselineSegmenter
from darubini.types import BoundingBox, Detection, ObjectClass
from darubini.verifier import (
    N_FEATURES,
    ParasiteVerifier,
    TrainingSet,
    VerifiedSegmenter,
    best_f1_threshold,
    build_training_set,
    candidate_features,
    label_candidates,
)
from tests.conftest import make_field

P, W = ObjectClass.PARASITE, ObjectClass.WBC


def _det(x0, y0, x1, y1, cls=P, score=1.0):
    return Detection(cls=cls, box=BoundingBox(x0, y0, x1, y1), score=score)


def _separable(n: int, seed: int) -> TrainingSet:
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.3).astype(np.float32)
    x = rng.normal(0, 1, (n, N_FEATURES)).astype(np.float32)
    x[:, :50] += y[:, None]  # signal spread over many features, as in a crop
    return TrainingSet(x, y, ["p"] * n)


def test_features_have_fixed_width_and_handle_edges():
    image = make_field()
    cands = [_det(0, 0, 6, 6), _det(120, 120, 128, 130), _det(250, 250, 256, 256)]
    x = candidate_features(image, cands)
    assert x.shape == (3, N_FEATURES)
    assert np.isfinite(x).all()
    assert candidate_features(image, []).shape == (0, N_FEATURES)


def test_label_candidates_by_centres():
    truth = [_det(10, 10, 50, 50), _det(0, 0, 4, 4, cls=W)]
    cands = [_det(25, 25, 31, 31), _det(100, 100, 110, 110), _det(0, 0, 3, 3)]
    assert label_candidates(cands, truth).tolist() == [1.0, 0.0, 0.0]


def test_fit_learns_save_load_round_trip(tmp_path):
    model = ParasiteVerifier.fit(_separable(2000, 0), _separable(500, 1), epochs=15)
    test = _separable(500, 2)
    pred = model.predict_proba(test.x) >= model.threshold
    assert (pred == (test.y > 0.5)).mean() > 0.9
    path = tmp_path / "v.npz"
    model.save(path)
    again = ParasiteVerifier.load(path)
    assert again.threshold == pytest.approx(model.threshold)
    np.testing.assert_allclose(again.predict_proba(test.x), model.predict_proba(test.x))
    assert model.predict_proba(np.zeros((0, N_FEATURES), dtype=np.float32)).shape == (0,)


def test_load_refuses_other_feature_layouts(tmp_path):
    path = tmp_path / "old.npz"
    np.savez(path, n_features=np.int32(N_FEATURES + 1))
    with pytest.raises(ValueError, match="feature layout"):
        ParasiteVerifier.load(path)


def test_best_f1_threshold():
    proba = np.asarray([0.9, 0.8, 0.3, 0.2], dtype=np.float32)
    y = np.asarray([1, 1, 0, 0], dtype=np.float32)
    assert 0.3 < best_f1_threshold(proba, y) <= 0.8
    assert best_f1_threshold(proba, np.zeros(4, dtype=np.float32)) == 0.05


class _Fixed:
    name = "fixed"

    def __init__(self, dets):
        self.dets = dets

    def segment(self, image):
        return list(self.dets)


class _Always:
    """A verifier stub that accepts every candidate with probability 0.8."""

    threshold = 0.5

    def predict_proba(self, x):
        return np.full(len(x), 0.8, dtype=np.float32)


def test_verified_segmenter_drops_parasites_in_wbc():
    wbc = _det(0, 0, 50, 50, cls=W)
    inside, outside = _det(20, 20, 26, 26), _det(80, 80, 86, 86)
    image = make_field()
    own = VerifiedSegmenter(_Fixed([wbc, inside, outside]), _Always()).segment(image)
    assert [d.box for d in own] == [wbc.box, outside.box]
    assert own[1].score == pytest.approx(0.8)
    # With a separate WBC source, the candidates' own WBCs are ignored.
    other = VerifiedSegmenter(_Fixed([wbc, inside, outside]), _Always(), wbc=_Fixed([]))
    assert [d.box for d in other.segment(image)] == [inside.box, outside.box]


def _nlm(root: Path, n_patients: int) -> None:
    for i in range(n_patients):
        pid = f"TF{i}"
        (root / pid).mkdir(parents=True)
        (root / "GT" / pid).mkdir(parents=True)
        Image.fromarray(make_field(seed=i)).save(root / pid / "a.jpg")
        (root / "GT" / pid / "a.txt").write_text(
            "1,256,256\n0-1,Parasite,No,Circle,2,40,40,40,46\n"
        )


def test_build_training_set_and_compare(tmp_path):
    _nlm(tmp_path, 2)
    from darubini.data.fields import nlm_thick_fields

    fields = nlm_thick_fields(tmp_path)
    ts = build_training_set(fields, BaselineSegmenter())
    assert ts.x.shape[0] == len(ts.y) == len(ts.patients) > 0
    scores = compare_on_fields(fields, {"base": BaselineSegmenter()})
    assert [(s.name, s.cls) for s in scores] == [("base", P), ("base", W)]
    assert scores[0].labelled == 2
    text = render_comparison(scores, "# t")
    assert "## Parasite (2 labelled)" in text and "| base |" in text
    empty = build_training_set([], BaselineSegmenter())
    assert empty.x.shape == (0, N_FEATURES)


def test_cli_train_verifier(tmp_path, capsys):
    raw = tmp_path / "raw"
    _nlm(raw / "toy", 40)
    assert {patient_split(f"TF{i}") for i in range(40)} >= {"tune", "val"}
    out, report = tmp_path / "v.npz", tmp_path / "v.md"
    args = ["train-verifier", "--raw-dir", str(raw), "--dataset", "toy"]
    assert (
        main(
            [
                *args,
                "--fields",
                "6",
                "--eval-fields",
                "2",
                "--out",
                str(out),
                "--report",
                str(report),
            ]
        )
        == 0
    )
    assert out.is_file()
    assert "Candidates + verifier" in report.read_text(encoding="utf-8")
    assert main([*args, "--dataset", "missing"]) == 2
    (raw / "bare").mkdir()
    assert main([*args, "--dataset", "bare"]) == 2


def test_factory_builds_verified_and_hybrid(tmp_path):
    path = tmp_path / "v.npz"
    ParasiteVerifier.fit(_separable(200, 0), _separable(50, 1), epochs=1).save(path)
    offline = get_segmenter(
        Settings(_env_file=None, DARUBINI_SEGMENTER="verified", DARUBINI_VERIFIER_PATH=str(path))
    )
    assert isinstance(offline, VerifiedSegmenter)
    assert isinstance(offline.wbc, BaselineSegmenter)
    hybrid = get_segmenter(
        Settings(
            _env_file=None,
            DARUBINI_SEGMENTER="hybrid",
            DARUBINI_VERIFIER_PATH=str(path),
            META_API_KEY=SecretStr("k"),
            META_API_BASE_URL="https://x.test",
        )
    )
    assert isinstance(hybrid, VerifiedSegmenter) and hybrid.wbc is not None
    hybrid.wbc.client.close()  # type: ignore[attr-defined]


def test_training_sets_concatenate_and_repeat():
    a, b = _separable(4, 0), _separable(2, 1)
    both = a + b.repeat(3)
    assert both.x.shape == (10, N_FEATURES)
    assert len(both.y) == len(both.patients) == 10


def test_cli_train_verifier_adapts_to_udom(tmp_path):
    from tests.test_benchmark import _udom

    raw = tmp_path / "raw"
    _nlm(raw / "toy", 40)
    _udom(raw / "udom", photos=60)
    report = tmp_path / "v.md"
    args = ["train-verifier", "--raw-dir", str(raw), "--dataset", "toy", "--adapt-dataset", "udom"]
    assert (
        main(
            [
                *args,
                "--fields",
                "4",
                "--eval-fields",
                "2",
                "--out",
                str(tmp_path / "v.npz"),
                "--report",
                str(report),
            ]
        )
        == 0
    )
    text = report.read_text(encoding="utf-8")
    assert "`adapt` half of the `udom` dev slice" in text and "dev check half" in text


def test_blob_shape_separates_rods_from_dots():
    from darubini.verifier import blob_shape

    rod = np.ones((9, 9), dtype=np.float32)
    rod[np.arange(9), np.arange(9)] = 0.3  # diagonal: square box, elongated blob
    dot = np.ones((9, 9), dtype=np.float32)
    dot[3:6, 3:6] = 0.3
    assert blob_shape(rod)[0] > 1.5
    assert blob_shape(dot)[0] == pytest.approx(0.0)
    assert blob_shape(np.ones((1, 1), dtype=np.float32)) == (0.0, 1.0)
    assert blob_shape(np.ones((3, 3), dtype=np.float32))[0] == 0.0
