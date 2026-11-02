import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr

from darubini.cli import main
from darubini.config import Settings
from darubini.data.fields import nlm_thick_fields, patient_split
from darubini.evaluation import match_centres, match_detections
from darubini.meta.client import MetaModelClient
from darubini.sweep import (
    Variant,
    VariantRun,
    matcher_for,
    render,
    requests_for,
    run_sweep,
    score_run,
)
from darubini.types import BoundingBox, Detection, ObjectClass
from tests.conftest import make_field

P, W = ObjectClass.PARASITE, ObjectClass.WBC


def _nlm(root: Path, patients: list[str]) -> None:
    """A tiny NLM-layout dataset: one 256 px field per patient, one parasite each."""
    for pid in patients:
        (root / pid).mkdir(parents=True)
        (root / "GT_updated" / pid).mkdir(parents=True)
        Image.fromarray(make_field()).save(root / pid / "a.jpg")
        Image.fromarray(make_field()).save(root / pid / "unlabelled.jpg")
        (root / "GT_updated" / pid / "a.txt").write_text(
            "2,256,256\n0-1,Parasite,No,Circle,2,20,20,20,25\n0-2,White_Blood_Cell,No,Point,1,100,100\n"
        )


def _det(x0, x1, score, cls=P):
    return Detection(cls=cls, box=BoundingBox(x0, 0, x1, 10), score=score, source="t")


def test_patient_split_is_stable_and_balanced():
    splits = [patient_split(f"TF{i}") for i in range(2000)]
    assert patient_split("TF1") == patient_split("TF1")
    assert 0.65 < splits.count("tune") / 2000 < 0.75
    assert {"tune", "val", "test"} == set(splits)


def test_nlm_fields_need_labels_and_respect_split(tmp_path):
    _nlm(tmp_path, ["p1", "p2", "p3", "p4", "p5", "p6"])
    every = nlm_thick_fields(tmp_path)
    assert [f.image.name for f in every] == ["a.jpg"] * 6
    assert {d.cls for d in every[0].truth} == {P, W}
    tune = nlm_thick_fields(tmp_path, "tune")
    assert all(patient_split(f.patient) == "tune" for f in tune)


def test_score_run_picks_best_threshold():
    truth = [_det(0, 10, 1.0), _det(20, 30, 1.0)]
    preds = [_det(0, 10, 0.9), _det(20, 30, 0.6), _det(50, 60, 0.15)]
    run = VariantRun(Variant("dot", P), predicted=[preds], truth=[truth])
    best = score_run(run, match_detections)
    assert best.threshold == 0.2
    assert best.score.f1 == 1.0
    assert best.count_mae == 0.0
    assert matcher_for(centres=True) is match_centres
    assert matcher_for(centres=False) is match_detections
    text = render([best], "toy", "tune", 1, 3)
    assert '| "dot" @ full | 0.2 | 1.00 | 1.00 | 1.00 |' in text
    assert "White blood cell" not in text


def _sam_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    concept = body["input"][0]["content"][0]["text"]
    box = "15;y1=15;x2=25;y2=25" if concept == "dot" else "80;y1=80;x2=120;y2=120"
    text = f"<0f>0<|box;x1={box};w=1;h=1;c=0.9|>"
    part = {"type": "output_text", "text": text}
    return httpx.Response(200, json={"output": [{"type": "message", "content": [part]}]})


def test_run_sweep_end_to_end(tmp_path):
    _nlm(tmp_path, ["p1", "p2"])
    fields = nlm_thick_fields(tmp_path)
    variants = [Variant("dot", P), Variant("cell", W), Variant("dot", P, tile_size=128)]
    assert requests_for(fields, variants, overlap=32) == 2 * (1 + 1 + 9)
    client = MetaModelClient("https://x.test", "k", transport=httpx.MockTransport(_sam_handler))
    runs = run_sweep(fields, variants, client, "m", tile_overlap=32)
    scores = {r.variant: score_run(r, matcher_for(centres=True)) for r in runs}
    assert scores[variants[0]].score.f1 == 1.0
    assert scores[variants[1]].score.f1 == 1.0
    assert scores[variants[2]].score.false_positives > 0  # every tile reports a dot


def test_cli_sweep_guards(tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw"
    _nlm(raw / "toy", ["p1", "p2", "p3", "p4", "p5", "p6"])
    base = ["sweep", "--raw-dir", str(raw), "--dataset", "toy", "--out", str(tmp_path / "s.md")]
    assert main([*base, "--dataset", "missing"]) == 2
    assert main([*base, "--max-cost", "0"]) == 2
    assert "above --max-cost" in capsys.readouterr().out
    unconfigured = Settings(_env_file=None)
    monkeypatch.setattr("darubini.cli.get_settings", lambda: unconfigured)
    assert main(base) == 2
    assert "not configured" in capsys.readouterr().out


def test_cli_sweep_runs(tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw"
    _nlm(raw / "toy", ["p1", "p2", "p3", "p4", "p5", "p6"])
    settings = Settings(
        _env_file=None, META_API_KEY=SecretStr("k"), META_API_BASE_URL="https://x.test"
    )
    monkeypatch.setattr("darubini.cli.get_settings", lambda: settings)
    real = MetaModelClient.from_settings

    def fake(s: Settings) -> MetaModelClient:
        client = real(s)
        client._http = httpx.Client(
            base_url="https://x.test", transport=httpx.MockTransport(_sam_handler)
        )
        return client

    monkeypatch.setattr(MetaModelClient, "from_settings", staticmethod(fake))
    out = tmp_path / "s.md"
    args = ["sweep", "--raw-dir", str(raw), "--dataset", "toy", "--out", str(out)]
    assert main([*args, "--parasite-prompts", "dot", "--wbc-prompts", "cell"]) == 0
    assert '"dot" @ full' in out.read_text(encoding="utf-8")
    assert main([*args, "--parasite-prompts", "dot", "--exclude-in-wbc", "cell"]) == 0
    assert 'found by "cell" @ full were dropped' in out.read_text(encoding="utf-8")


def test_cli_sweep_no_fields(tmp_path):
    (tmp_path / "raw" / "toy").mkdir(parents=True)
    with pytest.raises(SystemExit):
        main(["sweep", "--split", "test"])  # the test split is never offered
    assert main(["sweep", "--raw-dir", str(tmp_path / "raw"), "--dataset", "toy"]) == 2
