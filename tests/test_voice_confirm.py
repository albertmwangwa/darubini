import io
import json
import wave

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from darubini.api import app as app_module
from darubini.api.sessions import CaptureSession, add_voice, start_report
from darubini.meta.client import MetaApiError
from darubini.pipeline import Pipeline
from darubini.segmentation.baseline import BaselineSegmenter
from darubini.segmentation.candidates import CandidateDetector
from darubini.segmentation.confirm import BoxConfirmer, ConfirmedSegmenter
from darubini.types import BoundingBox, Detection, ObjectClass
from darubini.verifier import ParasiteVerifier as ParasiteVerifierType
from darubini.voice import KEYWORDS, SAMPLE_RATE, parse_command, to_wav
from tests.test_meta import _box, _client, _sam


def _wav(rate: int = 44_100, channels: int = 2, seconds: float = 0.5) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(tone, channels).tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------- commands


@pytest.mark.parametrize(
    ("transcript", "action"),
    [
        ("Next field.", "next"),
        ("next field,", "next"),
        ("Finish the slide.", "finish"),
        ("retake that field.", "retake"),
        ("Sehemu inayofuata", "next"),
        ("Maliza", "finish"),
        ("Piga tena", "retake"),
        ("Go to the next field, not done yet", "next"),
        ("hello there", "none"),
        ("note", "none"),
        ("", "none"),
    ],
)
def test_parse_command(transcript, action):
    assert parse_command(transcript).action == action


def test_notes_keep_the_spoken_text():
    c = parse_command("note, the stain looks pale and thick.")
    assert (c.action, c.note) == ("note", "the stain looks pale and thick.")
    assert parse_command("Kumbuka: damu ni nzito").note == "damu ni nzito"
    assert "sehemu inayofuata" in KEYWORDS and "note" in KEYWORDS


# ---------------------------------------------------------------- audio


def test_to_wav_resamples_to_16k_mono():
    out = to_wav(_wav(44_100, 2, 0.5))
    with wave.open(io.BytesIO(out)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SAMPLE_RATE, 1, 2)
        assert abs(w.getnframes() - SAMPLE_RATE // 2) < 400


@pytest.mark.parametrize("data", [b"not audio at all", _wav(16_000, 1, 0.0)])
def test_to_wav_rejects_bad_input(data):
    with pytest.raises(ValueError):
        to_wav(data)


def test_to_wav_rejects_long_recordings(monkeypatch):
    import darubini.voice as voice

    monkeypatch.setattr(voice, "MAX_SECONDS", 0.1)
    with pytest.raises(ValueError, match="longer"):
        to_wav(_wav(16_000, 1, 0.5))


# ---------------------------------------------------------------- client


def test_transcribe_sends_multipart_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"sessionId": "s", "transcript": "next field"})

    c = _client(handler)
    assert c.transcribe(b"RIFF....", "muse-voice-transcribe-1.0", keywords=["next"]) == "next field"
    assert seen["path"].endswith("/asr/transcribe")
    body = seen["body"].decode("latin-1")
    assert '"audioEncoding": "WAV"' in body and '"keywords": ["next"]' in body
    assert 'name="audio"' in body and "audio/wav" in body


def test_transcribe_language_bias_and_bad_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'"languageBias": ["Swahili"]' in request.content
        return httpx.Response(200, json={"sessionId": "s"})

    with pytest.raises(MetaApiError, match="no transcript"):
        _client(handler).transcribe(b"x", "m", language_bias=["Swahili"])


# ---------------------------------------------------------------- sessions and API


def test_add_voice_keeps_notes_and_report_carries_them():
    s = CaptureSession("s", 0.0)
    assert add_voice(s, parse_command("next field"))["voice_notes"] == []
    out = add_voice(s, parse_command("note: pale stain"))
    assert out["action"] == "note" and out["voice_notes"] == ["pale stain"]
    job = start_report(s, Pipeline(BaselineSegmenter()), "en", None, "m")
    assert job.result is not None and job.result["voice_notes"] == ["pale stain"]


class _Voice:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, wav: bytes, model: str, keywords=None, language_bias=None) -> str:
        assert wav[:4] == b"RIFF" and keywords
        return self.text


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(app_module, "_shared_pipeline", lambda: Pipeline(BaselineSegmenter()))
    return TestClient(app_module.app)


def test_voice_endpoint(api, monkeypatch):
    monkeypatch.setattr(app_module, "_client", lambda: _Voice("Note, thick smear"))
    sid = api.post("/v1/sessions").json()["session_id"]
    r = api.post(f"/v1/sessions/{sid}/voice", files={"file": ("v.wav", _wav(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["action"] == "note" and r.json()["voice_notes"] == ["thick smear"]
    bad = api.post(f"/v1/sessions/{sid}/voice", files={"file": ("v.wav", b"junk", "audio/wav")})
    assert bad.status_code == 415


def test_voice_endpoint_errors(api, monkeypatch):
    monkeypatch.setattr(app_module, "_client", lambda: None)
    sid = api.post("/v1/sessions").json()["session_id"]
    files = {"file": ("v.wav", _wav(), "audio/wav")}
    assert api.post(f"/v1/sessions/{sid}/voice", files=files).status_code == 503

    class _Down:
        def transcribe(self, *a, **k):
            raise MetaApiError("down")

    monkeypatch.setattr(app_module, "_client", lambda: _Down())
    assert api.post(f"/v1/sessions/{sid}/voice", files=files).status_code == 502
    monkeypatch.setattr(app_module, "MAX_AUDIO_BYTES", 10)
    assert api.post(f"/v1/sessions/{sid}/voice", files=files).status_code == 413


# ---------------------------------------------------------------- two-stage confirmation


def test_segment_objects_builds_box_prompts_and_maps_ids():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["text"] = json.loads(request.content)["input"][0]["content"][0]["text"]
        return httpx.Response(200, json=_sam("<0f>" + _box(1, 10, 10, 20, 20, 0.8)))

    out = _client(handler).segment_objects(b"jpg", [(-3, 0, 5, 5), (10, 10, 70, 20)], (64, 64), "m")
    assert set(out) == {1} and out[1].score == pytest.approx(0.8) and out[1].object_id == 1
    # Corners are clamped into the image; SAM rejects negatives and x2 == w.
    assert seen["text"].startswith("<0f>0<|box;x1=0;y1=0;x2=5;y2=5;w=64;h=64|>,1<|box;x1=10")
    assert "x2=63" in seen["text"]


def test_segment_objects_limits_batch_size():
    c = _client(lambda r: httpx.Response(200, json=_sam("")))
    with pytest.raises(ValueError):
        c.segment_objects(b"j", [], (64, 64), "m")
    with pytest.raises(ValueError):
        c.segment_objects(b"j", [(0, 0, 1, 1)] * 17, (64, 64), "m")


class _Objects:
    """Confirms every box whose index is even, with confidence 0.9."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def segment_objects(self, jpeg, boxes, size, model):
        from darubini.meta.client import SegmentResult

        self.calls.append(len(boxes))
        return {
            i: SegmentResult("object", (0, 0, 1, 1), 0.9, object_id=i)
            for i in range(len(boxes))
            if i % 2 == 0
        }


def test_box_confirmer_batches_by_tile():
    client = _Objects()
    boxes = [BoundingBox(5 + i, 5, 9 + i, 9) for i in range(20)] + [BoundingBox(1100, 5, 1104, 9)]
    conf = BoxConfirmer(client, "m").confidences(np.zeros((64, 1200, 3), np.uint8), boxes)  # type: ignore[arg-type]
    assert sorted(client.calls) == [1, 4, 16]
    assert conf[0] == 0.9 and conf[1] == 0.0 and conf[20] == 0.9
    assert BoxConfirmer(client, "m").confidences(np.zeros((8, 8, 3), np.uint8), []) == []  # type: ignore[arg-type]


def test_confirmed_segmenter_keeps_both_stages(field):
    class _Verifier:
        threshold = 0.5

        def predict_proba(self, x):
            return np.linspace(0.0, 1.0, len(x))

    class _Confirm:
        def confidences(self, image, boxes):
            return [0.9 if i % 2 else 0.1 for i in range(len(boxes))]

    seg = ConfirmedSegmenter(
        CandidateDetector(),
        _Verifier(),  # type: ignore[arg-type]
        _Confirm(),  # type: ignore[arg-type]
        BaselineSegmenter(),
        min_confidence=0.5,
    )
    out = seg.segment(field)
    parasites = [d for d in out if d.cls is ObjectClass.PARASITE]
    wbcs = [d for d in out if d.cls is ObjectClass.WBC]
    candidates = [d for d in CandidateDetector().segment(field) if d.cls is ObjectClass.PARASITE]
    assert parasites and len(parasites) < len(candidates)
    assert all(d.score >= 0.5 and d.source == "confirmed" for d in parasites)
    assert wbcs == [d for d in BaselineSegmenter().segment(field) if d.cls is ObjectClass.WBC]


# ---------------------------------------------------------------- narratives (Muse Spark / Open)


def test_narrate_guards_numbers_and_needs_config(monkeypatch):
    from pydantic import SecretStr

    import darubini.cli as cli
    from darubini.config import Settings
    from darubini.counting import evaluate_slide
    from darubini.meta.reviewer import MuseReviewer
    from darubini.report import render
    from darubini.types import FieldResult

    box = BoundingBox(0, 0, 4, 4)
    dets = [Detection(ObjectClass.PARASITE, box)] * 12 + [Detection(ObjectClass.WBC, box)] * 200
    count = evaluate_slide([FieldResult("f1", dets)])
    facts = render(count, "en").facts
    settings = Settings(OPEN_WEIGHTS_BASE_URL=None)  # type: ignore[call-arg]
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli._narrate(count, facts, "en", "none") is None
    assert cli._narrate(count, facts, "en", "open") is None  # no host configured

    settings = Settings(  # type: ignore[call-arg]
        OPEN_WEIGHTS_BASE_URL="http://localhost:8001/v1", OPEN_WEIGHTS_API_KEY=SecretStr("k")
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        MuseReviewer, "draft_report", lambda self, c, lang: "12 parasites in 200 WBC."
    )
    assert cli._narrate(count, facts, "en", "open") == "12 parasites in 200 WBC."
    monkeypatch.setattr(MuseReviewer, "draft_report", lambda self, c, lang: "About 999 parasites.")
    assert cli._narrate(count, facts, "en", "open") is None

    def boom(self, c, lang):
        raise MetaApiError("down")

    monkeypatch.setattr(MuseReviewer, "draft_report", boom)
    assert cli._narrate(count, facts, "en", "open") is None


def test_factory_builds_the_confirmed_segmenter(monkeypatch):
    from pydantic import SecretStr

    from darubini.config import Settings
    from darubini.segmentation.base import get_segmenter
    from darubini.segmentation.confirm import CONFIRM_MIN_CONFIDENCE

    class _Verifier:
        threshold = 0.75

    monkeypatch.setattr(ParasiteVerifierType, "load", classmethod(lambda cls, path: _Verifier()))
    s = Settings(  # type: ignore[call-arg]
        DARUBINI_SEGMENTER="confirmed",
        META_API_KEY=SecretStr("k"),
        META_API_BASE_URL="https://x.test",
    )
    seg = get_segmenter(s)
    assert isinstance(seg, ConfirmedSegmenter)
    assert seg.min_confidence == CONFIRM_MIN_CONFIDENCE and seg.verifier_threshold == 0.75
