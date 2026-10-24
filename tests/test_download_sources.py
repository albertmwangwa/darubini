import hashlib
import json
import zipfile
from collections import namedtuple
from pathlib import Path

import httpx
import pytest

from darubini.cli import main
from darubini.data import download as dl
from darubini.data.registry import DatasetSpec

ROOT = Path(__file__).resolve().parents[1]


def _spec(**kw) -> DatasetSpec:
    base = dict(
        id="x",
        title="t",
        country="TZ",
        tier="core",
        kind="http",
        licence="CC0",
        page="https://example.test/p",
        role="r",
        url="https://d.test/x.zip",
        filename="x.zip",
    )
    base.update(kw)
    return DatasetSpec(**base)


def _zip(tmp_path: Path, name: str = "a.txt") -> bytes:
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(name, "hello")
    return z.read_bytes()


def test_zenodo_download(tmp_path):
    payload = _zip(tmp_path)
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    api = {
        "files": [
            {
                "key": "part1.zip",
                "size": len(payload),
                "checksum": f"md5:{md5}",
                "links": {"self": "https://zenodo.test/files/part1.zip/content"},
            },
            {
                "key": "readme.txt",
                "size": 2,
                "checksum": "sha256:abc",
                "links": {"self": "https://zenodo.test/files/readme.txt/content"},
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/records/"):
            return httpx.Response(200, json=api)
        if "part1" in request.url.path:
            return httpx.Response(200, content=payload)
        return httpx.Response(200, content=b"hi")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    spec = _spec(kind="zenodo", url=None, filename=None, zenodo_record="7484518")
    out = dl.download(spec, tmp_path / "raw", client=client)
    assert out is not None
    assert (out / "a.txt").read_text() == "hello"
    assert (out / "readme.txt").read_bytes() == b"hi"
    assert (out / ".complete").exists()


@pytest.mark.parametrize(
    "response", [httpx.Response(500), httpx.Response(200, json={"files": [{"key": "a"}]})]
)
def test_zenodo_errors(response):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(dl.DownloadError):
        dl.zenodo_files("1", client)


def test_licence_gate(tmp_path, monkeypatch):
    spec = _spec(requires_licence_acceptance=True)
    with pytest.raises(dl.LicenceNotAcceptedError):
        dl.download(spec, tmp_path)

    def fake_fetch(url, dest, client=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"data")
        return dest

    monkeypatch.setattr(dl, "fetch_http", fake_fetch)
    assert dl.download(spec, tmp_path, accept_licences=True) is not None


def test_kaggle_requires_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(dl.shutil, "which", lambda name: None)
    spec = _spec(kind="kaggle", url=None, filename=None, kaggle_slug="a/b", instructions="by hand")
    with pytest.raises(dl.DownloadError, match="Kaggle CLI"):
        dl.download(spec, tmp_path)


def test_kaggle_and_git_commands(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dl.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(dl, "_run", lambda argv: calls.append(argv))
    k = _spec(id="k", kind="kaggle", url=None, filename=None, kaggle_slug="a/b")
    g = _spec(id="g", kind="git", url="https://github.test/r.git", filename=None)
    (tmp_path / "g").mkdir()
    assert dl.download(k, tmp_path) is not None
    assert dl.download(g, tmp_path) is not None
    assert calls[0][:4] == ["/usr/bin/kaggle", "datasets", "download", "-d"]
    assert calls[1][:2] == ["/usr/bin/git", "clone"]


def test_git_requires_git(tmp_path, monkeypatch):
    monkeypatch.setattr(dl.shutil, "which", lambda name: None)
    with pytest.raises(dl.DownloadError, match="git"):
        dl.download(_spec(kind="git", filename=None), tmp_path)


def test_space_check(tmp_path, monkeypatch):
    specs = [
        _spec(size_bytes=10_000),
        _spec(id="m", kind="manual", url=None, filename=None, instructions="x", size_bytes=10**12),
    ]
    assert dl.space_needed(specs, tmp_path) == int(10_000 * dl.SPACE_FACTOR)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda p: usage(1, 1, 100))
    with pytest.raises(dl.DownloadError, match="disk space"):
        dl.check_space(specs, tmp_path)
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda p: usage(1, 1, 10**9))
    dl.check_space(specs, tmp_path)


def test_status(tmp_path):
    spec = _spec()
    assert dl.status(spec, tmp_path) == ("missing", 0)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "f.jpg").write_bytes(b"1")
    assert dl.status(spec, tmp_path) == ("partial", 1)
    (tmp_path / "x" / ".complete").touch()
    assert dl.status(spec, tmp_path) == ("ready", 1)
    manual = _spec(id="m", kind="manual", url=None, filename=None, instructions="x")
    assert dl.status(manual, tmp_path) == ("manual", 0)
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "f.jpg").write_bytes(b"1")
    assert dl.status(manual, tmp_path) == ("ready", 1)


def test_cli_verify(tmp_path, capsys):
    code = main(
        ["verify", "--manifest", str(ROOT / "datasets/manifest.yaml"), "--raw-dir", str(tmp_path)]
    )
    out = capsys.readouterr().out
    assert code == 1 and "udom-tz-thick" in out and "missing" in out


def test_cli_download_summary(tmp_path, capsys, monkeypatch):
    manifest = tmp_path / "m.yaml"
    manifest.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "id": "lic",
                        "title": "t",
                        "country": "TZ",
                        "tier": "core",
                        "kind": "http",
                        "licence": "x",
                        "page": "p",
                        "role": "r",
                        "url": "https://d.test/a.zip",
                        "filename": "a.zip",
                        "requires_licence_acceptance": True,
                    },
                    {
                        "id": "bad",
                        "title": "t",
                        "country": "TZ",
                        "tier": "core",
                        "kind": "http",
                        "licence": "x",
                        "page": "p",
                        "role": "r",
                        "url": "https://d.test/b.zip",
                        "filename": "b.zip",
                    },
                ]
            }
        )
    )

    def boom(url, dest, client=None):
        raise dl.DownloadError("network down")

    monkeypatch.setattr(dl, "fetch_http", boom)
    code = main(["download", "--manifest", str(manifest), "--raw-dir", str(tmp_path / "raw")])
    out = capsys.readouterr().out
    assert code == 1
    assert "licence not accepted" in out and "failed" in out


def test_cli_download_space_error(tmp_path, capsys, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda p: usage(1, 1, 0))
    code = main(
        ["download", "--manifest", str(ROOT / "datasets/manifest.yaml"), "--raw-dir", str(tmp_path)]
    )
    assert code == 2
    assert "disk space" in capsys.readouterr().out


def test_check_link(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.method == "HEAD" and "refuse" in str(request.url):
            return httpx.Response(405)
        if "gone" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert dl.check_link(_spec(url="https://d.test/ok.zip"), client) == (True, "HTTP 200")
    assert dl.check_link(_spec(url="https://d.test/refuse.zip"), client)[0] is True
    assert seen[-1][0] == "GET"
    assert dl.check_link(_spec(url="https://d.test/gone.zip"), client)[0] is False
    z = _spec(kind="zenodo", url=None, filename=None, zenodo_record="1")
    assert dl.check_link(z, client)[0] is True
    g = _spec(kind="git", url="https://github.test/r.git", filename=None)
    dl.check_link(g, client)
    assert seen[-1][1] == "https://github.test/r"
    m = _spec(kind="manual", url=None, filename=None, instructions="x")
    assert dl.check_link(m)[0] is True

    def broken(request):
        raise httpx.ConnectError("down")

    bad = httpx.Client(transport=httpx.MockTransport(broken))
    assert dl.check_link(_spec(), bad)[0] is False


def test_cli_links(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(dl, "check_link", lambda spec, client=None: (spec.id != "nlm-sudan", "x"))
    code = main(["links", "--manifest", str(ROOT / "datasets/manifest.yaml")])
    out = capsys.readouterr().out
    assert code == 1 and "BAD nlm-sudan" in out
