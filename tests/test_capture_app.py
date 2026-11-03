import io
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from darubini.api import app as app_module
from darubini.api.sessions import (
    CaptureSession,
    SessionStore,
    add_clip,
    add_field,
    next_action,
    running_facts,
    start_report,
)
from darubini.counting import evaluate_slide
from darubini.pipeline import Pipeline
from darubini.tracking import ShiftTracker
from darubini.types import FieldResult
from tests.conftest import make_field
from tests.test_agent import _call, _Fixed, _scripted

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Never call the real Meta API from these tests, whatever .env says."""
    from darubini.segmentation.baseline import BaselineSegmenter

    monkeypatch.setattr(app_module, "_shared_pipeline", lambda: Pipeline(BaselineSegmenter()))
    monkeypatch.setattr(app_module, "_client", lambda: None)
    monkeypatch.setattr(app_module, "_tracker", lambda: ShiftTracker(crop=128))


def _jpeg(seed=0) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(make_field(seed=seed)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_phone_page_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "Darubini" in r.text and "/v1/sessions" in r.text


def test_capture_flow_without_the_api():
    s = client.post("/v1/sessions").json()
    sid = s["session_id"]
    assert s["running"]["wbc_target"] == 200
    r = client.post(f"/v1/sessions/{sid}/fields", files={"file": ("f.jpg", _jpeg(), "image/jpeg")})
    body = r.json()
    assert r.status_code == 200
    assert body["field"]["field_id"] == "field-001"
    assert body["next"]["action"] in ("next", "retake", "finish")
    assert set(body["field"]["blocking_text"]) == {"en", "sw"}
    assert {"parasites", "wbcs", "status"} <= set(body["running"])
    assert client.get(f"/v1/sessions/{sid}").json()["session_id"] == sid
    job = client.post(f"/v1/sessions/{sid}/report?language=sw").json()
    assert job["state"] == "done" and "Sehemu" in job["result"]["report"]
    assert client.get(f"/v1/sessions/{sid}/report").json()["state"] == "done"


def test_capture_errors():
    assert client.get("/v1/sessions/nope").status_code == 404
    sid = client.post("/v1/sessions").json()["session_id"]
    bad = client.post(
        f"/v1/sessions/{sid}/fields", files={"file": ("x.jpg", b"nope", "image/jpeg")}
    )
    assert bad.status_code == 415
    clip = client.post(f"/v1/sessions/{sid}/clips", files={"file": ("x.mp4", b"nope", "video/mp4")})
    assert clip.status_code == 415


def test_clip_upload_counts_with_tracking():
    pytest.importorskip("av")
    from darubini import video

    frames = [make_field(seed=0, size=256)[:, i * 4 : i * 4 + 160] for i in range(12)]
    sid = client.post("/v1/sessions").json()["session_id"]
    r = client.post(
        f"/v1/sessions/{sid}/clips", files={"file": ("c.mp4", video.encode(frames), "video/mp4")}
    )
    assert r.status_code == 200, r.text
    clip = r.json()["clip"]
    assert clip["field_id"] == "clip-001" and clip["tracker"] == "shift"
    assert clip["naive_parasites"] >= clip["parasites"]


def test_webm_clip_from_a_browser_camera_is_counted():
    """The microscope camera records WebM (VP8/VP9) in the browser; the server must decode it."""
    av = pytest.importorskip("av")

    frames = [make_field(seed=0, size=256)[:, i * 4 : i * 4 + 160] for i in range(12)]
    buf = io.BytesIO()
    with av.open(buf, "w", format="webm") as out:
        s = out.add_stream("libvpx", rate=15)
        s.width, s.height, s.pix_fmt = 160, 256, "yuv420p"
        for f in frames:
            for p in s.encode(av.VideoFrame.from_ndarray(np.ascontiguousarray(f), format="rgb24")):
                out.mux(p)
        for p in s.encode(None):
            out.mux(p)
    sid = client.post("/v1/sessions").json()["session_id"]
    r = client.post(
        f"/v1/sessions/{sid}/clips", files={"file": ("pan.webm", buf.getvalue(), "video/webm")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["clip"]["frames"] == 12


def test_page_offers_the_microscope_camera():
    page = client.get("/").text
    for marker in (
        'id="camOpen"',
        'id="camView"',
        "getUserMedia",
        "MediaRecorder",
        'id="camSelect"',
    ):
        assert marker in page


def test_session_store_expiry_and_cap():
    store = SessionStore(max_sessions=2, ttl_s=60)
    a, b = store.create(), store.create()
    c = store.create()  # drops the oldest
    with pytest.raises(KeyError):
        store.get(a.session_id)
    assert store.get(c.session_id) is c
    b.created -= 120
    with pytest.raises(KeyError):
        store.get(b.session_id)
    c.created -= 120
    store.create()  # prunes expired sessions
    with pytest.raises(KeyError):
        store.get(c.session_id)


def test_next_action_and_target():
    pipeline = Pipeline(segmenter=_Fixed())
    empty = evaluate_slide([], pipeline.protocol)
    assert next_action(False, empty)["action"] == "retake"
    assert next_action(True, empty)["action"] == "next"
    few = FieldResult("f", [d for d in _Fixed().segment(None) if d.cls.value != "parasite"] * 11)
    facts = running_facts(evaluate_slide([few], pipeline.protocol), pipeline)
    assert facts["wbc_target"] == 500  # no parasites at 220 WBC: extend


def test_add_field_limits_and_finish():
    pipeline = Pipeline(segmenter=_Fixed())
    session = CaptureSession("s", time.time())
    for _ in range(10):
        out = add_field(session, pipeline, make_field(), max_fields=20)
    assert out["next"]["action"] == "finish"
    with pytest.raises(ValueError):
        add_field(session, pipeline, make_field(), max_fields=10)
    with pytest.raises(ValueError):
        add_clip(session, pipeline, [], ShiftTracker(), max_fields=20)


def test_report_job_runs_the_agent_with_live_steps():
    pipeline = Pipeline(segmenter=_Fixed())
    session = CaptureSession("s", time.time())
    for _ in range(10):
        add_field(session, pipeline, make_field(), max_fields=20)
    client_ = _scripted(
        [
            [_call("examine_next_fields", {"count": 10})],
            [_call("audit_parasites", {}, 1)],
            [_call("finish", {"narrative": "Done."}, 2)],
        ]
    )
    job = start_report(session, pipeline, "en", client_, "muse", runner=lambda work: work())
    assert job.state == "done", job.error
    assert [s["tool"] for s in job.steps] == ["examine_next_fields", "audit_parasites", "finish"]
    assert job.steps[0]["result"]["examined"] == 10
    assert job.result["finished_by_agent"] and job.result["audit"]["sampled"] == 20
    assert job.result["audit_text"].startswith("Second-reader audit")
    # a second start while running returns the same job
    session.job.state = "running"
    assert start_report(session, pipeline, "en", client_, "muse") is session.job


def test_report_job_failure_is_captured():
    class _Boom:
        def run(self, *a, **k):
            raise RuntimeError("boom")

    pipeline = Pipeline(segmenter=_Fixed())
    session = CaptureSession("s", time.time())
    add_field(session, pipeline, make_field(), max_fields=5)
    import darubini.api.sessions as sessions

    original = sessions.CountingAgent
    sessions.CountingAgent = lambda *a, **k: _Boom()
    try:
        job = start_report(session, pipeline, "en", _scripted([]), "muse", runner=lambda w: w())
    finally:
        sessions.CountingAgent = original
    assert job.state == "failed" and job.error == "boom"


def test_clip_helper_keeps_parasite_crops():
    pytest.importorskip("av")
    pipeline = Pipeline(segmenter=_Fixed())
    session = CaptureSession("s", time.time())
    frames = [np.asarray(make_field(seed=1))] * 3
    out = add_clip(
        session, pipeline, frames, ShiftTracker(crop=128), max_fields=5, keyframe_every=2
    )
    _, captured = session.fields[0]
    assert out["clip"]["frames"] == 3
    assert len(captured.crops) == captured.result.parasites
