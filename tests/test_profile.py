import json
from pathlib import Path

from darubini.cli import main
from darubini.data.profile import profile, render, summarise_json


def _make(root: Path) -> None:
    (root / "imgs").mkdir(parents=True)
    for i in range(4):
        (root / "imgs" / f"f{i}.jpg").write_bytes(b"x" * 10)
    coco = {
        "images": [{"id": 1}, {"id": 2}],
        "annotations": [{"id": 1}],
        "categories": [{"name": "plasmodium"}, {"name": "wbc"}],
    }
    (root / "imgs" / "_annotations.coco.json").write_text(json.dumps(coco))
    (root / ".complete").touch()


def test_profile_detects_coco(tmp_path):
    _make(tmp_path / "udom")
    p = profile("udom", tmp_path / "udom")
    assert p.files == 5 and p.images == 4
    assert p.annotation_format == "COCO JSON"
    md = render([p])
    assert "COCO: 2 images, 1 annotations" in md and "plasmodium" in md


def test_format_guesses(tmp_path):
    for ext, expected in [(".xml", "VOC"), (".txt", "text"), (".csv", "CSV"), (".jpg", "none")]:
        d = tmp_path / ext.strip(".")
        d.mkdir()
        (d / f"a{ext}").write_text("1")
        assert expected in profile("x", d).annotation_format


def test_summarise_json_variants(tmp_path):
    f = tmp_path / "a.json"
    f.write_text('{"b": 1, "a": 2}')
    assert summarise_json(f) == "object with keys ['a', 'b']"
    f.write_text("[1, 2]")
    assert summarise_json(f) == "list of 2 items"
    f.write_text("3")
    assert summarise_json(f) == "int"
    f.write_text("{bad")
    assert summarise_json(f).startswith("unreadable")


def test_cli_profile(tmp_path, capsys):
    raw = tmp_path / "raw"
    _make(raw / "udom-tz-thick")
    out = tmp_path / "profile.md"
    manifest = Path(__file__).resolve().parents[1] / "datasets" / "manifest.yaml"
    code = main(["profile", "--manifest", str(manifest), "--raw-dir", str(raw), "--out", str(out)])
    assert code == 0
    assert "udom-tz-thick" in out.read_text()
    assert "COCO JSON" in capsys.readouterr().out
