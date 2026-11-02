from pathlib import Path

import numpy as np
from PIL import Image

from darubini.cli import main
from darubini.config import Settings
from darubini.data.fields import _unit_hash, held_out_split, split_table, udom_fields
from tests.conftest import make_field

VOC = """<annotation><object><name>Plasmodium trophozoite</name><bndbox>
<xmin>20</xmin><ymin>20</ymin><xmax>30</xmax><ymax>30</ymax></bndbox></object></annotation>"""


def _udom(root: Path, photos: int, tiles_per_photo: int = 2) -> None:
    tiles = root / "COCO_mkapa_train"
    tiles.mkdir(parents=True)
    rows = ["old_name,new_names"]
    n = 0
    for p in range(photos):
        names = []
        for _ in range(tiles_per_photo):
            n += 1
            name = f"{n:06d}"
            Image.fromarray(make_field(seed=n)).save(tiles / f"{name}.jpg")
            (tiles / f"{name}.xml").write_text(VOC)
            names.append(name)
        rows.append(",".join([f"IMG_{p}", *names]))
    (tiles / "mapper.csv").write_text("\n".join(rows) + "\n")
    (tiles / "orphan.xml").write_text(VOC)  # no image: skipped


def test_udom_split_keeps_photos_together(tmp_path):
    _udom(tmp_path, photos=40)
    every = udom_fields(tmp_path)
    assert len(every) == 80
    dev, test = udom_fields(tmp_path, "dev"), udom_fields(tmp_path, "test")
    assert len(dev) + len(test) == 80 and dev and test
    assert not {f.patient for f in dev} & {f.patient for f in test}
    assert all(held_out_split(f.patient) in ("adapt", "check") for f in dev)
    adapt, check = udom_fields(tmp_path, "adapt"), udom_fields(tmp_path, "check")
    assert len(adapt) + len(check) == len(dev)
    assert not {f.patient for f in adapt} & {f.patient for f in check}
    assert every[0].truth[0].cls.value == "parasite"


def test_held_out_split_is_70_30_and_nests_inside_the_old_test_set():
    groups = [f"IMG_{i}" for i in range(4000)]
    parts = [held_out_split(g) for g in groups]
    assert 0.27 < parts.count("test") / len(groups) < 0.33
    # Raising the train share from 15% moved photos out of test only: nothing that was
    # ever on the training side became test, and old dev photos keep their half.
    for g, part in zip(groups, parts, strict=True):
        old_test = _unit_hash(g) >= 0.15
        if part == "test":
            assert old_test
        if not old_test:
            assert part in ("adapt", "check")


def test_split_table_and_cli(tmp_path, capsys):
    _udom(tmp_path / "raw" / "udom-tz-thick", photos=12)
    rows = split_table(udom_fields(tmp_path / "raw" / "udom-tz-thick"), held_out_split)
    assert len(rows) == 12 and all(n == 2 for _, _, n in rows)
    out = tmp_path / "splits"
    assert main(["splits", "--raw-dir", str(tmp_path / "raw"), "--out", str(out)]) == 0
    lines = (out / "udom-tz-thick.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "group,split,fields" and len(lines) == 13
    assert "skip nih-thick-pf-150" in capsys.readouterr().out
    assert main(["splits", "--raw-dir", str(tmp_path / "none"), "--out", str(out)]) == 2


def test_cli_evaluate_guards_and_runs(tmp_path, capsys, monkeypatch):
    raw = tmp_path / "raw"
    _udom(raw / "udom-tz-thick", photos=40)
    out = tmp_path / "e.md"
    base = ["evaluate", "--raw-dir", str(raw), "--out", str(out)]
    assert main([*base, "--split", "test"]) == 2
    assert "--final-test" in capsys.readouterr().out
    assert main([*base, "--split", "val"]) == 2
    assert main([*base, "--dataset", "missing"]) == 2
    assert main([*base, "--segmenters", "hybrid", "--max-cost", "0"]) == 2
    assert main([*base, "--split", "dev", "--segmenters", "baseline", "--fields", "3"]) == 0
    text = out.read_text(encoding="utf-8")
    assert "# Evaluation: udom-tz-thick, dev split" in text and "| baseline |" in text
    missing = Settings(_env_file=None, DARUBINI_VERIFIER_PATH=str(tmp_path / "none.npz"))
    monkeypatch.setattr("darubini.cli.get_settings", lambda: missing)
    assert main([*base, "--segmenters", "verified", "--fields", "1"]) == 2  # no model file
    final = ["--split", "test", "--final-test", "--fields", "1", "--segmenters", "baseline"]
    assert main([*base, *final]) == 0


def test_cli_evaluate_nlm_splits(tmp_path):
    raw = tmp_path / "raw"
    (raw / "nlm").mkdir(parents=True)
    base = ["evaluate", "--raw-dir", str(raw), "--dataset", "nlm"]
    assert main([*base, "--split", "check"]) == 2
    assert main([*base, "--split", "val"]) == 2  # no labelled fields


def test_candidate_detector_finds_dots_on_pale_and_dark_fields():
    from darubini.segmentation.candidates import CandidateDetector
    from darubini.types import ObjectClass

    for scale in (1, 3):  # 256 px and a 768 px upscaled copy
        field = make_field(n_parasites=5, n_wbc=2)
        img = np.asarray(Image.fromarray(field).resize((256 * scale, 256 * scale)))
        found = CandidateDetector(working_side=512).segment(img)
        assert found and all(d.cls is ObjectClass.PARASITE for d in found)
        # WBC nuclei (radius 14) are too large to be parasite candidates.
        assert all(d.box.width < 20 * scale for d in found)
    assert CandidateDetector().segment(np.full((64, 64, 3), 200, dtype=np.uint8)) == []
