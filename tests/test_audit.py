import httpx
import numpy as np
import pytest

from darubini.agent import CountingAgent, SlideSession
from darubini.audit import (
    AuditResult,
    MuseAuditor,
    crop_detection,
    montage,
    parse_confirmed,
    render_audit,
)
from darubini.meta.client import MetaApiError, MetaModelClient
from darubini.pipeline import Pipeline
from darubini.types import BoundingBox, Detection, ObjectClass
from tests.conftest import make_field
from tests.test_agent import _call, _Fixed, _scripted


def _chat_client(text, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return MetaModelClient("https://api.example.test", "k", transport=httpx.MockTransport(handler))


def test_crop_and_montage():
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    crop = crop_detection(image, Detection(ObjectClass.PARASITE, BoundingBox(0, 0, 4, 4)))
    assert crop.shape == (48, 48, 3)  # 24 px each side, padded at the corner
    jpeg = montage([crop] * 7)
    assert jpeg[:2] == b"\xff\xd8"


def test_parse_confirmed_variants():
    assert parse_confirmed('{"parasites": [1, 3, 99]}', 5) == {1, 3}
    assert parse_confirmed('```json\n{"parasites": [2]}\n```', 5) == {2}
    assert parse_confirmed("parasites: tiles 4 and 5", 5) == {4, 5}
    per_tile = (
        '{"tiles": [{"n": 1, "parasite": true}, {"n": 2, "parasite": false}, '
        '{"n": 7, "parasite": true}]}'
    )
    assert parse_confirmed(per_tile, 5) == {1}


def test_audit_result_properties_and_text():
    r = AuditResult(sampled=20, confirmed=4, parasites_counted=500)
    assert r.confirmed_share == 0.2 and r.audited_parasites == 100 and r.flagged
    assert r.facts()["confirmed_percent"] == 20
    assert "Warning" in render_audit(r, "en")
    assert "Tahadhari" in render_audit(r, "sw")
    ok = AuditResult(20, 18, 300)
    assert not ok.flagged and "Warning" not in render_audit(ok)
    assert AuditResult(0, 0, 0).confirmed_share == 1.0


def test_auditor_samples_and_asks_muse():
    seen: list = []
    auditor = MuseAuditor(_chat_client('{"parasites": [1, 2]}', seen), "muse", sample=5)
    crops = [np.full((48, 48, 3), i, dtype=np.uint8) for i in range(30)]
    result = auditor.audit(crops)
    assert (result.sampled, result.confirmed, result.parasites_counted) == (5, 2, 30)
    assert b"data:image/jpeg;base64," in seen[0].content
    assert auditor.audit([]) == AuditResult(0, 0, 0)
    with pytest.raises(MetaApiError):
        MuseAuditor(_chat_client("  "), "muse").audit(crops)


def test_agent_must_audit_before_finishing():
    client = _scripted(
        [
            [_call("examine_next_fields", {"count": 10})],
            [_call("finish", {"narrative": "Done."}, 1)],
            [_call("audit_parasites", {}, 2)],
            [_call("finish", {"narrative": "Done."}, 3)],
        ]
    )
    image = make_field()
    session = SlideSession(
        Pipeline(segmenter=_Fixed()),
        [(f"f{i}", lambda: image) for i in range(12)],
        auditor=MuseAuditor(_chat_client('{"parasites": [1]}'), "muse"),
    )
    result = CountingAgent(client, "muse").run(session)
    assert "audit_parasites" in result.steps[1].result["error"]
    assert result.finished_by_agent
    assert result.audit is not None and result.audit.flagged
    assert "Second-reader audit" in result.text


def test_fallback_audits_and_audit_errors():
    image = make_field()
    session = SlideSession(
        Pipeline(segmenter=_Fixed()),
        [(f"f{i}", lambda: image) for i in range(3)],
        auditor=MuseAuditor(_chat_client('{"parasites": [1, 2, 3, 4, 5, 6]}'), "muse"),
    )
    session.examine_rest()
    assert session.audit is not None and session.audit.sampled == 6
    assert not session.audit_needed()
    bad = SlideSession(
        Pipeline(segmenter=_Fixed()),
        [("f0", lambda: image)],
        auditor=MuseAuditor(_chat_client(" "), "muse"),
    )
    bad.examine_next_fields(1)
    assert "audit failed" in bad.audit_parasites()["error"]
    assert "no auditor" in SlideSession(Pipeline(segmenter=_Fixed()), []).audit_parasites()["error"]
