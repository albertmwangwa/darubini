import json

import httpx
import numpy as np
import pytest
from PIL import Image

from darubini import cli
from darubini.agent import (
    EXCLUDED_FLAG,
    TOOLS,
    CountingAgent,
    SlideSession,
    unsupported_numbers,
)
from darubini.meta.client import MetaApiError, MetaModelClient
from darubini.meta.reviewer import MuseReviewer
from darubini.pipeline import Pipeline
from darubini.types import BoundingBox, Detection, ObjectClass
from tests.conftest import make_field

P, W = ObjectClass.PARASITE, ObjectClass.WBC


class _Fixed:
    """Every field has 2 parasites and 20 WBC, so 10 fields reach 200 WBC."""

    name = "fixed"

    def segment(self, image):
        box = BoundingBox(0, 0, 4, 4)
        return [Detection(P, box)] * 2 + [Detection(W, box)] * 20


def _session(n_fields=15, reviewer=None):
    image = make_field()
    sources = [(f"f{i:02d}", lambda: image) for i in range(n_fields)]
    return SlideSession(Pipeline(segmenter=_Fixed()), sources, reviewer=reviewer)


def _call(name, args, i=0):
    return {
        "id": f"c{i}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _scripted(turns, captured=None):
    """A client whose chat replies follow ``turns``: lists of tool calls, text, or a status."""
    script = iter(turns)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if captured is not None:
            captured.append(body)
        if "tools" not in body:  # the quality reviewer's own call
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"usable": false, "issues": ["blur"]}'}}]
                },
            )
        turn = next(script)
        if isinstance(turn, int):
            return httpx.Response(turn, json={"error": "boom"})
        if isinstance(turn, str):
            message = {"role": "assistant", "content": turn}
        else:
            message = {"role": "assistant", "content": None, "tool_calls": turn}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    return MetaModelClient(
        "https://api.example.test",
        "k",
        transport=httpx.MockTransport(handler),
        backoff_s=0,
        retries=0,
    )


def test_agent_counts_a_slide_and_keeps_a_grounded_narrative():
    captured: list = []
    client = _scripted(
        [
            [_call("examine_next_fields", {"count": 3})],
            [
                _call("review_field", {"field_id": "f01"}, 1),
                _call("exclude_field", {"field_id": "f01", "reason": "blur"}, 2),
            ],
            [_call("examine_next_fields", {"count": 10})],
            [_call("get_count", {})],
            [_call("finish", {"narrative": "Counted 20 parasites against 200 WBC: 800 per µL."})],
        ],
        captured,
    )
    session = _session(reviewer=MuseReviewer(client, "muse"))
    result = CountingAgent(client, "muse").run(session, language="sw")
    assert result.finished_by_agent
    assert result.count.wbcs == 200 and result.count.parasites == 20
    assert result.excluded == {"f01": "blur"}
    assert any(f.startswith(EXCLUDED_FLAG) for f in session.fields[1].quality_flags)
    assert result.narrative is not None and "800" in result.text
    assert "f01: blur" in result.text
    assert [s.tool for s in result.steps][:3] == [
        "examine_next_fields",
        "review_field",
        "exclude_field",
    ]
    assert result.steps[1].result["usable"] is False
    first = captured[0]
    assert first["tools"] == TOOLS and "Kiswahili" in first["messages"][1]["content"]
    # tool results go back with the assistant message that asked for them
    second_agent_call = [b for b in captured if "tools" in b][1]
    assert second_agent_call["messages"][2]["tool_calls"][0]["id"] == "c0"
    assert second_agent_call["messages"][3]["role"] == "tool"


def test_finish_is_refused_early_and_fallback_completes():
    client = _scripted(
        [
            [_call("finish", {"narrative": "done"})],
            "I think we are done.",
            "Really done.",
        ]
    )
    session = _session()
    result = CountingAgent(client, "muse").run(session)
    assert "error" in result.steps[0].result
    assert not result.finished_by_agent
    assert result.narrative is None
    assert result.count.wbcs == 200  # fallback counted to the stopping rule
    assert any("without the agent" in n for n in result.notes)


def test_invented_numbers_drop_the_narrative():
    client = _scripted(
        [
            [_call("examine_next_fields", {"count": 10})],
            [_call("finish", {"narrative": "We saw 37 parasites."})],
        ]
    )
    result = CountingAgent(client, "muse").run(_session())
    assert result.finished_by_agent
    assert result.narrative is None
    assert any("37" in n for n in result.notes)


def test_api_failure_and_turn_limit_fall_back():
    result = CountingAgent(_scripted([500]), "muse").run(_session(n_fields=3))
    assert not result.finished_by_agent
    assert result.count.fields_examined == 3
    assert any("agent stopped" in n for n in result.notes)

    looping = _scripted([[_call("get_count", {}, i)] for i in range(3)])
    result = CountingAgent(looping, "muse", max_turns=3).run(_session(n_fields=2))
    assert any("turn limit" in n for n in result.notes)


def test_tool_errors_are_reported_to_the_agent():
    client = _scripted(
        [
            [
                {"id": "a", "function": {"name": "examine_next_fields", "arguments": "{bad"}},
                {"id": "b", "function": {"name": "exclude_field", "arguments": "{}"}},
                {"id": "c", "function": {"name": "nope", "arguments": "{}"}},
                {"id": "d", "function": {"name": "get_count", "arguments": "[]"}},
                _call("review_field", {"field_id": "f00"}),
                _call("exclude_field", {"field_id": "zz", "reason": "x"}),
            ],
            "stop",
            "stop",
        ]
    )
    result = CountingAgent(client, "muse").run(_session(n_fields=1))
    assert all("error" in s.result for s in result.steps)


def test_session_tools_directly():
    session = _session(n_fields=12)
    assert session.review_field("f00") == {"error": "no reviewer is configured"}
    out = session.examine_next_fields(50)  # capped at 10, stops when the rule is met
    assert len(out["examined"]) == 10 and out["running"]["stop_rule_met"]
    assert "error" in session.examine_next_fields(1)
    assert session.finish_allowed() is None
    assert "no longer be excluded" in session.exclude_field("f00", "a")["error"]
    assert session.excluded == {}


def test_exclusion_before_the_rule_is_met():
    session = _session(n_fields=12)
    session.examine_next_fields(9)
    assert session.exclude_field("f00", "a")["excluded"] == "f00"
    session.exclude_field("f00", "again")
    assert session.excluded == {"f00": "a"}
    assert session.get_count()["status"] == "continue"
    session.examine_rest()
    assert session.remaining == 1 and session.decided()  # 10 usable fields reach 200 WBC


def test_reviewer_failures_and_unknown_fields():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    client = MetaModelClient(
        "https://api.example.test", "k", transport=httpx.MockTransport(handler)
    )
    session = _session(n_fields=2, reviewer=MuseReviewer(client, "muse"))
    assert "unknown" in session.review_field("f00")["error"]
    session.examine_next_fields(1)
    assert "review failed" in session.review_field("f00")["error"]


def test_unsupported_numbers():
    allowed = [646, 200, 25840.4, "x", True]
    assert unsupported_numbers("646 vimelea, 200 WBC, 25,840 kwa µL", allowed) == []
    assert unsupported_numbers("about 650 parasites", allowed) == ["650"]


def test_chat_turn_rejects_odd_payloads():
    for body in ({"choices": []}, {"choices": [{"message": "text"}]}):
        client = MetaModelClient(
            "https://api.example.test",
            "k",
            transport=httpx.MockTransport(lambda r, b=body: httpx.Response(200, json=b)),
        )
        with pytest.raises(Exception, match="unexpected chat payload"):
            client.chat_turn("muse", [], max_tokens=10)


def _images(tmp_path, n=3):
    folder = tmp_path / "slide"
    folder.mkdir()
    for i in range(n):
        Image.fromarray(make_field(seed=i)).save(folder / f"field{i}.png")
    (folder / "notes.txt").write_text("not an image")
    return folder


def test_cli_agent_runs_with_a_mock_client(tmp_path, monkeypatch, capsys):
    client = _scripted(
        [[_call("examine_next_fields", {"count": 3})], [_call("finish", {"narrative": "Done."})]]
    )
    monkeypatch.setattr(MetaModelClient, "from_settings", classmethod(lambda cls, s: client))
    out = tmp_path / "t" / "agent.json"
    code = cli.main(
        [
            "agent",
            str(_images(tmp_path)),
            "--segmenter",
            "baseline",
            "--transcript",
            str(out),
            "--no-review",
            "--no-audit",
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "> examine_next_fields" in text and "finished by agent: True" in text
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["finished_by_agent"] and saved["narrative"] == "Done."


def test_cli_agent_errors(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["agent", str(empty)]) == 2


def test_cli_track_synthetic_offline(tmp_path, capsys):
    pytest.importorskip("av")
    rng = np.random.default_rng(0)
    big = np.kron(
        rng.integers(0, 255, (100, 250, 3), dtype=np.uint8), np.ones((8, 8, 1), dtype=np.uint8)
    )
    still = tmp_path / "field.png"
    Image.fromarray(big).save(still)
    clip = tmp_path / "clip.mp4"
    code = cli.main(
        [
            "track",
            str(still),
            "--synthetic",
            "--tracker",
            "shift",
            "--segmenter",
            "baseline",
            "--max-frames",
            "12",
            "--keyframe-every",
            "6",
            "--save-clip",
            str(clip),
        ]
    )
    assert code == 0
    facts = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert facts["tracker"] == "shift" and facts["frames"] == 12
    assert cli.main(["track", str(clip), "--tracker", "shift", "--segmenter", "baseline"]) == 0
    assert (
        cli.main(
            ["track", str(clip), "--tracker", "sam", "--segmenter", "baseline", "--max-cost", "0"]
        )
        == 2
    )


class _Flaky(_Fixed):
    """Fails on the second field, as a SAM call can mid-slide."""

    def __init__(self):
        self.calls = 0

    def segment(self, image):
        self.calls += 1
        if self.calls == 2:
            raise MetaApiError("timeout")
        return super().segment(image)


def test_segmentation_failure_is_reported_not_raised():
    image = make_field()
    session = SlideSession(
        Pipeline(segmenter=_Flaky()), [(f"f{i}", lambda: image) for i in range(3)]
    )
    out = session.examine_next_fields(3)
    assert "segmentation failed on f1" in out["error"]
    assert len(out["examined"]) == 1 and session.remaining == 2
    session.examine_rest()  # retries f1, which now works
    assert session.remaining == 0


def test_fallback_stops_on_persistent_failure():
    class _Down(_Fixed):
        def segment(self, image):
            raise MetaApiError("down")

    image = make_field()
    session = SlideSession(Pipeline(segmenter=_Down()), [("f0", lambda: image)])
    session.examine_rest()
    assert session.remaining == 1
