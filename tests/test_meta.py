import json

import httpx
import numpy as np
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
    transport = httpx.MockTransport(handler)
    return MetaModelClient("https://api.example.test", "k", transport=transport, backoff_s=0)


def _chat(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def _sam(text: str) -> dict:
    """A Responses payload shaped like a real SAM 3.1 reply."""
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def _box(i: int, x1: int, y1: int, x2: int, y2: int, c: float) -> str:
    mask = f"<|mask;x=0;y=0;c={c};data={y2 - y1},{x2 - x1},!!a,b|>"
    return f"{i}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w=64;h=64;c={c}|>{mask}"


def test_sam_segmenter_maps_concepts(field):
    seen: dict = {"prompts": []}
    replies = {
        "small dark purple dot": "<0f>"
        + ",".join([_box(0, 1, 1, 6, 6, 0.9), _box(1, 1, 1, 6, 6, 0.1), _box(2, 5, 5, 5, 9, 0.9)])
        + "\n",
        "cell": "<0f>" + _box(0, 10, 10, 40, 40, 0.8) + "\n",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/responses"
        seen["auth"] = request.headers["authorization"]
        body = json.loads(request.content)
        content = body["input"][0]["content"]
        assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
        assert body["metadata"]["include_confidence"] == "true"
        concept = content[0]["text"]
        seen["prompts"].append(concept)
        return httpx.Response(200, json=_sam(replies[concept]))

    dets = SamSegmenter(_client(handler), model="sam-3.1").segment(field)
    assert seen["auth"] == "Bearer k"
    assert sorted(seen["prompts"]) == ["cell", "small dark purple dot"]
    assert [d.cls for d in dets] == [ObjectClass.PARASITE, ObjectClass.WBC]
    assert dets[0].score == pytest.approx(0.9)
    assert all(d.source == "sam3" for d in dets)


def test_segment_parses_mask_and_empty_reply():
    client = _client(lambda r: httpx.Response(200, json=_sam("<0f>" + _box(0, 1, 2, 9, 8, 0.5))))
    (res,) = client.segment_concepts(b"jpeg", ["cell"], model="sam-3.1")
    assert res.box_xyxy == (1.0, 2.0, 9.0, 8.0)
    assert res.mask == "6,8,!!a,b"
    empty = _client(lambda r: httpx.Response(200, json=_sam("")))
    assert empty.segment_concepts(b"jpeg", ["cell"], model="sam-3.1") == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={}),
        httpx.Response(200, json={"wrong": 1}),
        httpx.Response(200, json=[1]),
        httpx.Response(200, json=_sam("<0f>0<|box;x1=1;y1=1|>")),
    ],
)
def test_segment_errors_raise_meta_error(field, response):
    seg = SamSegmenter(_client(lambda r: response), model="sam-3.1")
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


def test_chat_null_content_raises():
    # Muse Spark can spend its whole token budget reasoning and return no text.
    reply = {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
    client = _client(lambda r: httpx.Response(200, json=reply))
    with pytest.raises(MetaApiError, match="finish_reason=length"):
        client.chat("m", "sys", "hi")


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
        get_segmenter(Settings(DARUBINI_SEGMENTER="sam3", _env_file=None))
    s = Settings(
        DARUBINI_SEGMENTER="sam3", META_API_KEY=SecretStr("k"), META_API_BASE_URL="https://x.test"
    )
    assert s.meta_enabled
    seg = get_segmenter(s)
    assert isinstance(seg, SamSegmenter)
    seg.client.close()


def test_segment_replies_are_cached(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_sam("<0f>" + _box(0, 1, 1, 6, 6, 0.9)))

    client = MetaModelClient(
        "https://x.test", "k", transport=httpx.MockTransport(handler), cache_dir=tmp_path
    )
    first = client.segment_concepts(b"img", ["dot"], model="sam-3.1")
    again = client.segment_concepts(b"img", ["dot"], model="sam-3.1")
    client.segment_concepts(b"other", ["dot"], model="sam-3.1")
    assert first == again
    assert len(calls) == 2
    assert client.billed_requests == 2
    assert len(list(tmp_path.rglob("*.json"))) == 2


def test_retries_rate_limits_and_network_errors():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("drop")
        if len(attempts) == 2:
            return httpx.Response(429, json={})
        return httpx.Response(200, json=_sam(""))

    assert _client(handler).segment_concepts(b"img", ["dot"], model="m") == []
    assert len(attempts) == 3

    def always_down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(MetaApiError, match="down"):
        _client(always_down).segment_concepts(b"img", ["dot"], model="m")


def test_tiled_segmentation_offsets_and_merges():
    from darubini.segmentation.sam import tile_grid

    assert tile_grid(100, 50, 64, 16) == [(0, 0, 64, 50), (36, 0, 100, 50)]
    assert tile_grid(40, 40, 64, 16) == [(0, 0, 40, 40)]
    image = np.zeros((50, 100, 3), dtype=np.uint8)

    def handler(request: httpx.Request) -> httpx.Response:
        # Every tile reports one object at tile coordinates (30, 10)-(40, 20).
        return httpx.Response(200, json=_sam("<0f>" + _box(0, 30, 10, 40, 20, 0.9)))

    seg = SamSegmenter(
        _client(handler), "m", concepts={"dot": ObjectClass.PARASITE}, tile_size=64, tile_overlap=16
    )
    boxes = sorted((d.box.x_min, d.box.x_max) for d in seg.segment(image))
    assert boxes == [(30.0, 40.0), (66.0, 76.0)]


def test_merge_duplicates_drops_overlaps_and_halves():
    from darubini.segmentation.sam import merge_duplicates
    from darubini.types import BoundingBox, Detection

    def det(x0, x1, score, cls=ObjectClass.WBC):
        return Detection(cls=cls, box=BoundingBox(x0, 0, x1, 10), score=score, source="t")

    full, half, same, other = det(0, 10, 0.9), det(5, 10, 0.5), det(1, 10, 0.8), det(20, 30, 0.7)
    parasite = det(0, 10, 0.6, ObjectClass.PARASITE)
    kept = merge_duplicates([half, same, full, other, parasite])
    assert kept == [full, other, parasite]


def test_parasites_inside_wbc_are_dropped():
    from darubini.segmentation.sam import drop_parasites_in_wbc
    from darubini.types import BoundingBox, Detection

    wbc = Detection(cls=ObjectClass.WBC, box=BoundingBox(0, 0, 50, 50))
    inside = Detection(cls=ObjectClass.PARASITE, box=BoundingBox(20, 20, 30, 30))
    outside = Detection(cls=ObjectClass.PARASITE, box=BoundingBox(60, 60, 70, 70))
    assert drop_parasites_in_wbc([wbc, inside, outside]) == [wbc, outside]


def test_tuned_segmenter_tiles_parasites_only():
    image = np.zeros((300, 600, 3), dtype=np.uint8)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["input"][0]["content"][0]["text"])
        return httpx.Response(200, json=_sam("<0f>" + _box(0, 10, 10, 20, 20, 0.5)))

    seg = SamSegmenter.tuned(_client(handler), "sam-3.1")
    seg.tile_size, seg.tile_overlap = 256, 0  # small tiles for a small test image
    dets = seg.segment(image)
    assert seen.count("cell") == 1  # whole field
    assert seen.count("small dark purple dot") == len(seg.tiles(image)) == 6
    # WBC at 0.5 is below its 0.7 threshold; one parasite per tile survives at 0.1.
    assert {d.cls for d in dets} == {ObjectClass.PARASITE}
