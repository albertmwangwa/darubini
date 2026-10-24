import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from darubini.api.app import app
from darubini.cli import main
from tests.conftest import make_field

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def _png(seed: int = 0) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(make_field(seed=seed)).save(buf, format="PNG")
    return buf.getvalue()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_analyse_two_fields_kiswahili():
    files = [("files", (f"f{i}.png", _png(i), "image/png")) for i in range(2)]
    r = client.post("/v1/analyse?language=sw", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["fields"]) == 2
    assert body["fields"][0]["parasites"] == 5
    assert "Hali" in body["report"]


def test_analyse_rejects_non_image():
    r = client.post("/v1/analyse", files=[("files", ("a.txt", b"hello", "text/plain"))])
    assert r.status_code == 415


def test_analyse_rejects_bad_language():
    r = client.post("/v1/analyse?language=fr", files=[("files", ("a.png", _png(), "image/png"))])
    assert r.status_code == 422


def test_cli_datasets(capsys):
    assert main(["datasets", "--manifest", str(ROOT / "datasets/manifest.yaml")]) == 0
    assert "udom-tz-thick" in capsys.readouterr().out


def test_cli_analyse(tmp_path, capsys):
    paths = []
    for i in range(2):
        p = tmp_path / f"f{i}.png"
        Image.fromarray(make_field(seed=i)).save(p)
        paths.append(str(p))
    assert main(["analyse", *paths, "--language", "en"]) == 0
    assert "Parasites counted" in capsys.readouterr().out
    assert main(["analyse", *paths, "--json"]) == 0
    assert '"slide"' in capsys.readouterr().out


def test_cli_download_manual_only(tmp_path, capsys):
    manifest = tmp_path / "m.yaml"
    manifest.write_text(
        "datasets:\n  - {id: m, title: t, country: TZ, tier: core, kind: manual, licence: x,"
        " page: p, role: r, instructions: by hand}\n"
    )
    assert main(["download", "--manifest", str(manifest), "--raw-dir", str(tmp_path / "raw")]) == 0
    assert "manual step needed" in capsys.readouterr().out
