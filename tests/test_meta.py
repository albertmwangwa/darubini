import json

import httpx
import pytest
from pydantic import SecretStr

from darubini.config import Settings
from darubini.counting import evaluate_slide
from darubini.meta.client import MetaApiError, MetaModelClient
from darubini.meta.reviewer import MuseReviewer, _strip_code_fence
from darubini.segmentation.base import get_segmenter
from darubini.segmentation.baseline import BaselineSegmenter
from darubini.segmentation.sam import SamSegmenter
from darubini.types import ObjectClass


def _client(handler) -> MetaModelClient:
    return MetaModelClient("https://api.example.test", "k", transport=httpx.MockTransport(handler))


def _chat(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def test_sam_segmenter_maps_concepts(field):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        body = json.loads(request.content)
        seen["prompts"] = [p["text"] for p in body["prompts"]]
        return httpx.Response(
            200,
            json={
                "instances": [
                    {"concept": "malaria parasite", "box": [1, 1, 6, 6], "score": 0.9},
                    {"concept": "white blood cell nucleus", "box": [10, 10, 40, 40], "score": 0.8},
                    {"concept": "malaria parasite", "box": [1, 1, 6, 6], "score": 0.1},
                    {"concept": "platelet", "box": [1, 1, 3, 3], "score": 0.9},
                    {"concept": "malaria parasite", "box": [5, 5, 5, 9], "score": 0.9},
                ]
            },
        )

    dets = SamSegmenter(_client(handler), model="sam-3").segment(field)
    assert seen["auth"] == "Bearer k"
    assert "malaria parasite" in seen["prompts"]
    assert [d.cls for d in dets] == [ObjectClass.PARASITE, ObjectClass.WBC]
    assert all(d.source == "sam3" for d in dets)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={}),
        httpx.Response(200, json={"wrong": 1}),
        httpx.Response(200, json=[1]),
    ],
)
def test_segment_errors_raise_meta_error(field, response):
    seg = SamSegmenter(_client(lambda r: response), model="sam-3")
    with pytest.raises(MetaApiError):
        seg.segment(field)


def test_reviewer_parses_json_and_fences():
    reply = '```json\n{"usable": false, "issues": ["blurry"], "advice": "refocus"}\n```'
    rev = MuseReviewer(_client(lambda r: httpx.Response(200, json=_chat(reply))), "muse-spark")
    out = rev.review_field(b"jpeg")
    assert out.usable is False
    assert out.issues == ("blurry",)


def test_reviewer_bad_json_raises():
    rev = MuseReviewer(_client(lambda r: httpx.Response(200, json=_chat("not json"))), "m")
    with pytest.raises(MetaApiError):
        rev.review_field(b"jpeg")


def test_reviewer_bad_chat_payload_raises():
    rev = MuseReviewer(_client(lambda r: httpx.Response(200, json={"choices": []})), "m")
    with pytest.raises(MetaApiError):
        rev.review_field(b"jpeg")


def test_draft_report_sends_facts_in_kiswahili():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat("Muhtasari"))

    text = MuseReviewer(_client(handler), "m").draft_report(evaluate_slide([]), language="sw")
    assert text == "Muhtasari"
    user = captured["body"]["messages"][1]["content"][0]["text"]
    assert "Kiswahili" in user and "parasites_counted" in user


def test_strip_code_fence_edge_cases():
    assert _strip_code_fence("```") == ""
    assert _strip_code_fence(' {"a": 1} ') == '{"a": 1}'


def test_factory_and_settings():
    assert isinstance(get_segmenter(Settings(DARUBINI_SEGMENTER="baseline")), BaselineSegmenter)
    with pytest.raises(ValueError):
        get_segmenter(Settings(DARUBINI_SEGMENTER="nope"))
    with pytest.raises(MetaApiError):
        get_segmenter(Settings(DARUBINI_SEGMENTER="sam3"))
    s = Settings(
        DARUBINI_SEGMENTER="sam3", META_API_KEY=SecretStr("k"), META_API_BASE_URL="https://x.test"
    )
    assert s.meta_enabled
    seg = get_segmenter(s)
    assert isinstance(seg, SamSegmenter)
    seg.client.close()
