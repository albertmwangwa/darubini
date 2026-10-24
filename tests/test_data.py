import hashlib
import zipfile
from pathlib import Path

import httpx
import pytest

from darubini.data import download as dl
from darubini.data.annotations import parse_nlm_thick, parse_voc
from darubini.data.registry import DatasetSpec, Manifest, load_manifest
from darubini.types import ObjectClass

ROOT = Path(__file__).resolve().parents[1]


def test_repo_manifest_is_valid():
    m = load_manifest(ROOT / "datasets" / "manifest.yaml")
    ids = [d.id for d in m.datasets]
    assert "udom-tz-thick" in ids
    assert all(d.tier == "core" for d in m.up_to_tier("core"))
    assert len(m.up_to_tier("large")) == len(ids)
    assert m.get("udom-tz-thick").country == "Tanzania"
    with pytest.raises(KeyError):
        m.get("missing")


def _spec(**kw) -> DatasetSpec:
    base = dict(
        id="x",
        title="t",
        country="TZ",
        tier="core",
        kind="http",
        licence="CC0",
        page="p",
        role="r",
        url="https://d.test/x.zip",
        filename="x.zip",
    )
    base.update(kw)
    return DatasetSpec(**base)


@pytest.mark.parametrize(
    "kw",
    [{"url": None}, {"filename": None}, {"kind": "manual"}, {"md5": "nothex"}, {"id": "Bad Id"}],
)
def test_spec_validation(kw):
    with pytest.raises(ValueError):
        _spec(**kw)


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError):
        Manifest(datasets=[_spec(), _spec()])


def _zip_bytes(tmp_path: Path, name: str = "a.txt") -> bytes:
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(name, "hello")
    return z.read_bytes()


def test_http_download_verifies_and_extracts(tmp_path, monkeypatch):
    payload = _zip_bytes(tmp_path)
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=payload))
    real_fetch = dl.fetch_http

    def fake_fetch(url, dest, client=None):
        return real_fetch(url, dest, client=httpx.Client(transport=transport))

    monkeypatch.setattr(dl, "fetch_http", fake_fetch)
    raw = tmp_path / "raw"
    out = dl.download(_spec(md5=md5), raw)
    assert out is not None and (out / "a.txt").read_text() == "hello"
    assert (out / ".complete").exists()
    assert dl.download(_spec(md5=md5), raw) == out  # idempotent


def test_checksum_mismatch(tmp_path, monkeypatch):
    payload = _zip_bytes(tmp_path)

    def fake_fetch(url, dest, client=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        return dest

    monkeypatch.setattr(dl, "fetch_http", fake_fetch)
    with pytest.raises(dl.DownloadError, match="checksum"):
        dl.download(_spec(md5="0" * 32), tmp_path / "raw")


def test_non_zip_is_moved(tmp_path, monkeypatch):
    def fake_fetch(url, dest, client=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"plain")
        return dest

    monkeypatch.setattr(dl, "fetch_http", fake_fetch)
    out = dl.download(_spec(filename="notes.txt"), tmp_path / "raw")
    assert out is not None and (out / "notes.txt").read_bytes() == b"plain"


def test_resume_uses_range_header(tmp_path):
    dest = tmp_path / "f.bin"
    dest.with_suffix(".bin.part").write_bytes(b"abc")
    seen = {}

    def handler(request):
        seen["range"] = request.headers.get("range")
        return httpx.Response(206, content=b"def")

    dl.fetch_http(
        "https://d.test/f", dest, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert seen["range"] == "bytes=3-"
    assert dest.read_bytes() == b"abcdef"


def test_http_error_wrapped(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(dl.DownloadError):
        dl.fetch_http("https://d.test/f", tmp_path / "f.bin", client=client)


def test_zip_slip_blocked(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(dl.DownloadError, match="unsafe"):
        dl.extract(bad, tmp_path / "out")


def test_manual_returns_none(tmp_path):
    spec = _spec(kind="manual", url=None, filename=None, instructions="do it by hand")
    assert dl.download(spec, tmp_path) is None


def test_parse_voc(tmp_path):
    xml = tmp_path / "a.xml"
    xml.write_text(
        "<annotation>"
        "<object><name>Plasmodium</name><bndbox><xmin>1</xmin><ymin>2</ymin><xmax>9</xmax><ymax>8</ymax></bndbox></object>"
        "<object><name>WBC</name><bndbox><xmin>10</xmin><ymin>10</ymin><xmax>40</xmax><ymax>40</ymax></bndbox></object>"
        "<object><name>platelet</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>2</xmax><ymax>2</ymax></bndbox></object>"
        "<object><name>WBC</name><bndbox><xmin>5</xmin><ymin>5</ymin><xmax>5</xmax><ymax>9</ymax></bndbox></object>"
        "</annotation>"
    )
    dets = parse_voc(xml)
    assert [d.cls for d in dets] == [ObjectClass.PARASITE, ObjectClass.WBC]


def test_parse_nlm_thick(tmp_path):
    gt = tmp_path / "img.txt"
    gt.write_text(
        "4032,3024,0\n"
        "1,Parasite,,Circle,2,100,100,110,100\n"
        "2,White_Blood_Cell,,Point,1,500,500\n"
        "3,Parasite,,Point,300,300\n"
        "4,Unknown,,Point,1,1,1\n"
        "5,Parasite,,Point,x\n"
    )
    dets = parse_nlm_thick(gt, point_radius=12)
    assert [d.cls for d in dets] == [ObjectClass.PARASITE, ObjectClass.WBC, ObjectClass.PARASITE]
    assert dets[0].box.width == pytest.approx(20)
    assert dets[1].box.center == (500, 500)
