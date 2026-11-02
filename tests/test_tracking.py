import json

import httpx
import numpy as np
import pytest

from darubini import video
from darubini.meta.client import MetaModelClient, _to_tracked_boxes
from darubini.tracking import (
    ClipCount,
    SamTracker,
    ShiftTracker,
    Track,
    box_token,
    count_clip,
    estimate_shift,
    keyframe_indices,
    sam_cost_usd,
    same_object,
)
from darubini.types import BoundingBox, Detection, ObjectClass

P, W = ObjectClass.PARASITE, ObjectClass.WBC


def _texture(h: int = 400, w: int = 900, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (h // 8, w // 8, 3), dtype=np.uint8)
    return np.kron(small, np.ones((8, 8, 1), dtype=np.uint8))


def _sam(text: str) -> dict:
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


class _Truth:
    """Segmenter that reports fixed slide objects, shifted with the pan."""

    name = "truth"

    def __init__(self, objects, step):
        self.objects = objects  # (cls, x, y) in frame-0 coordinates
        self.step = step
        self.frame = 0

    def segment(self, image):
        out = []
        for cls, x, y in self.objects:
            cx = x - self.step * self.frame
            if 0 <= cx < image.shape[1]:
                out.append(Detection(cls, BoundingBox(cx - 4, y - 4, cx + 4, y + 4)))
        self.frame += 10  # count_clip visits keyframes every 10 frames
        return out


def test_keyframes_and_matching():
    assert keyframe_indices(25, 10) == (0, 10, 20, 24)
    assert keyframe_indices(21, 10) == (0, 10, 20)
    assert keyframe_indices(0, 10) == ()
    with pytest.raises(ValueError):
        keyframe_indices(5, 0)
    a = BoundingBox(0, 0, 4, 4)
    assert same_object(a, BoundingBox(1, 1, 5, 5))
    assert same_object(a, BoundingBox(8, 0, 12, 4))  # within tolerance
    assert not same_object(a, BoundingBox(30, 30, 34, 34))


def test_estimate_shift_recovers_pan():
    big = _texture()
    a, b = big[:, 100:612], big[:, 113:625]  # content moves 13 px left
    dx, dy = estimate_shift(a, b, crop=256)
    assert dx == pytest.approx(-13, abs=0.5)
    assert dy == pytest.approx(0, abs=0.5)


def test_shift_tracker_counts_each_object_once():
    big = _texture(seed=1)
    frames = [big[:, i * 6 : i * 6 + 400] for i in range(31)]
    objects = [(P, 380, 50), (P, 200, 120), (W, 300, 300), (P, 395, 200)]
    clip = count_clip(frames, _Truth(objects, 6), ShiftTracker(crop=256), keyframe_every=10)
    assert clip.parasites == 3
    assert clip.wbcs == 1
    assert clip.naive[P] > clip.parasites
    result = clip.as_field_result("clip-1")
    assert result.parasites == 3 and result.wbcs == 1


def test_sam_tracker_prompts_boxes_and_maps_back():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["input"][0]["content"]
        assert content[1]["video_url"].startswith("data:video/mp4;base64,")
        assert body["metadata"]["propagation_direction"] == "forward"
        prompt = content[0]["text"]
        seen.append(prompt)
        n = prompt.count("<|box")
        lines = [
            f"<{f}f>"
            + ",".join(
                f"{i}<|box;x1={10 + f};y1=10;x2={20 + f};y2=20;w=64;h=48|>" for i in range(n)
            )
            for f in range(3)
        ]
        lines.append("<3f>99<|box;x1=1;y1=1;x2=2;y2=2;w=64;h=48|>")  # unknown id, ignored
        return httpx.Response(200, json=_sam("\n".join(lines)))

    pytest.importorskip("av")
    client = MetaModelClient(
        "https://api.example.test", "k", transport=httpx.MockTransport(handler)
    )
    tracker = SamTracker(client, "sam-3.1", max_side=64)
    frames = [_texture(96, 128, seed=i)[:, :128] for i in range(4)]
    boxes = [BoundingBox(20 + i, 20, 40 + i, 40) for i in range(17)]
    paths = tracker.propagate(frames, 1, boxes)
    assert len(seen) == 2  # 16 objects per request
    assert seen[0].startswith("<0f>0<|box;x1=10;y1=10;x2=20;y2=20;w=64;h=48|>")
    assert len(paths) == 17
    assert paths[0][2] == BoundingBox(22, 20, 42, 40)  # frame 1 of the sub-clip, scaled x2
    assert tracker.frames_sent == 100  # 50-frame minimum per request
    assert sam_cost_usd(tracker.frames_sent) == pytest.approx(0.02)
    assert tracker.propagate(frames, 0, []) == []


def test_box_token_stays_inside_frame():
    assert box_token(BoundingBox(-3, 5, 70, 50), 1.0, 64, 48) == "x1=0;y1=5;x2=63;y2=47"
    assert box_token(BoundingBox(63.5, 47.2, 64, 48), 1.0, 64, 48) == "x1=62;y1=46;x2=63;y2=47"


def test_parse_video_reply():
    text = (
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=9;h=9;c=0.5|><|mask;x=0;y=0;data=2,2,!ab|>,"
        "2<|box;x1=5;y1=5;x2=7;y2=7;w=9;h=9|>\nnoise\n<4f>2<|box;x1=6;y1=5;x2=8;y2=7;w=9;h=9|>"
    )
    boxes = _to_tracked_boxes(_sam(text))
    assert [(b.frame, b.object_id) for b in boxes] == [(0, 0), (0, 2), (4, 2)]
    assert boxes[0].score == 0.5 and boxes[1].score == 1.0


def test_clip_count_totals():
    t = Track(0, P, 0.9, {3: BoundingBox(0, 0, 2, 2), 5: BoundingBox(1, 0, 3, 2)})
    assert t.first_frame == 3
    clip = ClipCount(10, (0, 9), (t,), {P: 4})
    assert (clip.parasites, clip.wbcs) == (1, 0)


def test_video_round_trip_and_pan(tmp_path):
    pytest.importorskip("av")
    big = _texture(200, 400)
    frames = video.synthetic_pan(big, size=(161, 120), frames=5, step=(10, 2), eyepiece=True)
    assert frames[0][0, 0].tolist() == [0, 0, 0]
    mp4 = video.encode(frames, fps=5)
    path = tmp_path / "clip.mp4"
    path.write_bytes(mp4)
    back = video.decode(path)
    assert len(back) == 5 and back[0].shape == (120, 160, 3)  # odd width trimmed
    assert len(video.decode(mp4, max_frames=3, max_side=80)) == 3
    assert video.decode(mp4, max_side=80)[0].shape[1] == 80
    with pytest.raises(ValueError):
        video.encode([])
    with pytest.raises(ValueError):
        video.synthetic_pan(big, size=(400, 200), frames=3)
    assert video.resize_to(big, 1000) is big
