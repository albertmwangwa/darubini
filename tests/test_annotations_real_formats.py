"""Parsers against the label formats found in the real downloaded datasets."""

import json

import pytest

from darubini.data.annotations import (
    normalise_label,
    parse_coco,
    parse_nlm_thick,
    parse_tile_mapper,
    parse_voc,
)
from darubini.data.profile import profile
from darubini.types import ObjectClass

P, W = ObjectClass.PARASITE, ObjectClass.WBC

# The seven category names in UDOM's output.json, verbatim.
UDOM_CATEGORIES = [
    ("Plasimodium trophozoite", P),
    ("Plasmodium gametocyte", None),  # sexual form: excluded from asexual density
    ("Plasmodium trophozoite", P),
    ("Plasmodium trophozoites", P),
    ("WBC", W),
    ("WBCPlasmodium trophozoite", None),  # ambiguous: names both classes
    ("plasmodium", P),
]


@pytest.mark.parametrize(("label", "expected"), UDOM_CATEGORIES)
def test_udom_category_names(label, expected):
    assert normalise_label(label) is expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Parasite", P),
        ("White_Blood_Cell", W),
        ("leucocyte", W),
        ("schizont", P),
        ("platelet", None),
        ("", None),
        ("  ", None),
    ],
)
def test_other_labels(label, expected):
    assert normalise_label(label) is expected


def test_parse_voc_udom_shape(tmp_path):
    # Shape of UDOM 000001.xml: 750x750 tile, plural label, objects run together.
    xml = tmp_path / "000001.xml"
    xml.write_text(
        "<annotation><filename>000001</filename><size><width>750</width><height>750</height></size>"
        "<object><name>Plasmodium trophozoites</name><bndbox><xmin>697</xmin><ymin>586</ymin>"
        "<xmax>727</xmax><ymax>619</ymax></bndbox></object>    <object><name>WBC</name><bndbox>"
        "<xmin>36</xmin><ymin>533</ymin><xmax>76</xmax><ymax>580</ymax></bndbox></object>"
        "</annotation>"
    )
    dets = parse_voc(xml)
    assert [d.cls for d in dets] == [P, W]
    assert dets[0].box.width == 30


def test_parse_coco(tmp_path):
    data = {
        "images": [{"id": 1, "file_name": "000001.jpg"}, {"id": 2, "file_name": "000002.jpg"}],
        "categories": [
            {"id": 2, "name": "Plasmodium trophozoite"},
            {"id": 4, "name": "WBC"},
            {"id": 5, "name": "WBCPlasmodium trophozoite"},
        ],
        "annotations": [
            {"image_id": 1, "category_id": 2, "bbox": [670, 57, 35, 31]},
            {"image_id": 1, "category_id": 4, "bbox": [10, 10, 40, 40]},
            {"image_id": 1, "category_id": 5, "bbox": [1, 1, 5, 5]},
            {"image_id": 1, "category_id": 2, "bbox": [1, 1, 0, 5]},
            {"image_id": 1, "category_id": 2, "bbox": [1, 2]},
            {"image_id": 99, "category_id": 2, "bbox": [1, 1, 5, 5]},
        ],
    }
    f = tmp_path / "output.json"
    f.write_text(json.dumps(data))
    out = parse_coco(f)
    assert set(out) == {"000001.jpg", "000002.jpg"}
    assert [d.cls for d in out["000001.jpg"]] == [P, W]
    box = out["000001.jpg"][0].box
    assert (box.x_min, box.y_min, box.x_max, box.y_max) == (670, 57, 705, 88)
    assert out["000002.jpg"] == []


def test_parse_tile_mapper(tmp_path):
    f = tmp_path / "mapper.csv"
    f.write_text("old_name,new_names\nIMG_2145,000001,000002,000003\nIMG_2146,000011,\n\n")
    groups = parse_tile_mapper(f)
    assert groups == {
        "000001": "IMG_2145",
        "000002": "IMG_2145",
        "000003": "IMG_2145",
        "000011": "IMG_2146",
    }


def test_parse_nlm_real_lines(tmp_path):
    # Verbatim shape of NLM GT_updated files: header, Circle rows with a comment, Point rows.
    f = tmp_path / "gt.txt"
    f.write_text(
        "25,4032,3024\n"
        "0-1,Parasite,No_Comment,Circle,2,2146.1,1191.3,2146.1,1210.15\n"
        "0-10,Parasite,schizont,Circle,2,1955.55,2456.8,1958,2488.8\n"
        "0-11,White_Blood_Cell,No_Comment,Point,1,2158.95,338.65\n"
    )
    dets = parse_nlm_thick(f, point_radius=30)
    assert [d.cls for d in dets] == [P, P, W]
    assert dets[0].box.width == pytest.approx(2 * 18.85)
    assert dets[2].box.center == pytest.approx((2158.95, 338.65))


def test_profile_skips_git_and_thumbs(tmp_path):
    root = tmp_path / "mp-idb"
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "objects" / "pack.idx").write_text("x")
    (root / "img").mkdir()
    (root / "img" / "a.jpg").write_text("x")
    (root / "img" / "Thumbs.db").write_text("x")
    p = profile("mp-idb", root)
    assert p.files == 1 and p.images == 1
