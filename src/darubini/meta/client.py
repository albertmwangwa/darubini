"""Thin HTTP client for the Meta Model API (base URL ``https://api.meta.ai/v1``).

SAM 3.1 runs through the Responses API: one ``input_text`` concept plus one
``input_image`` per request. The reply is a token stream in ``output_text``, one
line per frame, for example::

    <0f>0<|box;x1=93;y1=368;x2=180;y2=456;w=750;h=750;c=0.90|><|mask;...|>,1<|box;...

Muse Spark uses the OpenAI-compatible Chat Completions API. Every route and
field name lives in :class:`ApiRoutes` and the ``_to_*`` mapping functions.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from darubini.config import Settings

log = logging.getLogger(__name__)

#: Status codes worth retrying: rate limiting and transient server errors.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

#: SAM 3.1 rejects more than 16 prompted objects in one request.
MAX_PROMPTED_OBJECTS = 16


class MetaApiError(RuntimeError):
    """Raised when the Meta Model API returns an error or an unexpected payload."""


@dataclass(frozen=True)
class ApiRoutes:
    """Routes relative to the base URL, which already ends in ``/v1``."""

    segment: str = "/responses"
    chat: str = "/chat/completions"
    transcribe: str = "/asr/transcribe"


@dataclass(frozen=True)
class SegmentResult:
    """One instance returned by concept segmentation."""

    concept: str
    box_xyxy: tuple[float, float, float, float]
    score: float
    #: Raw SAM mask token (``H,W,<enc>payload``, base85); kept undecoded for now.
    mask: str | None = None
    #: The object id in the reply; for object prompts, the id the prompt gave.
    object_id: int = -1


@dataclass(frozen=True)
class TrackedBox:
    """One object's box on one video frame; ``object_id`` is stable across frames."""

    frame: int
    object_id: int
    box_xyxy: tuple[float, float, float, float]
    score: float = 1.0


class MetaModelClient:
    """Calls SAM 3 (concept segmentation) and Muse Spark (multimodal chat)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 60.0,
        routes: ApiRoutes | None = None,
        transport: httpx.BaseTransport | None = None,
        cache_dir: Path | None = None,
        retries: int = 3,
        backoff_s: float = 2.0,
    ) -> None:
        self.routes = routes or ApiRoutes()
        self.cache_dir = cache_dir
        self.retries = retries
        self.backoff_s = backoff_s
        #: Segmentation requests actually sent (cache misses), for cost tracking.
        self.billed_requests = 0
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> MetaModelClient:
        """Build a client from settings, failing clearly if it is not configured."""
        if not settings.meta_enabled or settings.meta_api_key is None:
            raise MetaApiError(
                "Meta Model API is not configured: set META_API_KEY and META_API_BASE_URL"
            )
        return cls(
            base_url=str(settings.meta_api_base_url),
            api_key=settings.meta_api_key.get_secret_value(),
            timeout_s=settings.meta_timeout_s,
            cache_dir=settings.meta_cache_dir,
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    # ---- SAM 3: promptable concept segmentation ----

    def segment_concepts(
        self, image_jpeg: bytes, concepts: list[str], model: str
    ) -> list[SegmentResult]:
        """Find every instance of each text concept in an image.

        SAM 3.1 takes one concept per request, so this makes one call per concept.
        Segmentation is deterministic, so replies are cached on disk by request body
        when ``cache_dir`` is set; a repeated image and prompt is never billed twice.
        """
        results: list[SegmentResult] = []
        for concept in concepts:
            data = self._post_cached(
                self.routes.segment, _image_payload(model, concept, image_jpeg)
            )
            results.extend(_to_segment_results(data, concept))
        return results

    def segment_objects(
        self,
        image_jpeg: bytes,
        boxes: list[tuple[int, int, int, int]],
        size: tuple[int, int],
        model: str,
    ) -> dict[int, SegmentResult]:
        """Segment the objects marked by box prompts, keyed by their index in ``boxes``.

        ``boxes`` are inclusive pixel corners ``(x1, y1, x2, y2)`` in an image of
        ``size`` (width, height). SAM 3.1 takes at most 16 objects per request and
        returns a confidence for each one it finds; an index missing from the result
        is an object SAM did not segment. Cached like :meth:`segment_concepts`.
        """
        if not 0 < len(boxes) <= MAX_PROMPTED_OBJECTS:
            raise ValueError(f"between 1 and {MAX_PROMPTED_OBJECTS} boxes per request")
        w, h = size
        tokens = []
        for i, (x1, y1, x2, y2) in enumerate(boxes):
            # SAM rejects corners outside the image, and x2 == w.
            x1, y1 = min(max(0, x1), w - 2), min(max(0, y1), h - 2)
            x2, y2 = max(min(w - 1, x2), x1 + 1), max(min(h - 1, y2), y1 + 1)
            tokens.append(f"{i}<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={w};h={h}|>")
        prompt = "<0f>" + ",".join(tokens)
        data = self._post_cached(self.routes.segment, _image_payload(model, prompt, image_jpeg))
        return {r.object_id: r for r in _to_segment_results(data, "object")}

    def segment_video(
        self, video_mp4: bytes, prompt: str, model: str, metadata: dict[str, str] | None = None
    ) -> list[TrackedBox]:
        """Segment and track objects through an MP4 clip.

        ``prompt`` is a text concept, or object prompts in SAM tokens such as
        ``<0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>,1<|box;...|>``, which SAM
        follows through the clip. Replies are cached like :meth:`segment_concepts`.
        """
        video_url = "data:video/mp4;base64," + base64.b64encode(video_mp4).decode("ascii")
        payload = {
            "model": model,
            "metadata": {"mask_encoding": "one_bit", **(metadata or {})},
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_video", "video_url": video_url},
                    ],
                }
            ],
        }
        return _to_tracked_boxes(self._post_cached(self.routes.segment, payload))

    # ---- Muse Spark: multimodal reasoning ----

    def chat(self, model: str, system: str, user_text: str, image_jpeg: bytes | None = None) -> str:
        """Send one multimodal turn and return the text reply."""
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if image_jpeg is not None:
            b64 = base64.b64encode(image_jpeg).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        return _to_chat_text(self._post(self.routes.chat, payload))

    def chat_turn(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Send a whole conversation and return the assistant message.

        The message may hold ``tool_calls`` instead of text; append it unchanged to
        ``messages`` before sending the tool results back.
        """
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        data = self._post(self.routes.chat, payload)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, TypeError, IndexError) as exc:
            raise MetaApiError(f"unexpected chat payload: {exc}") from exc
        if not isinstance(message, dict):
            raise MetaApiError("unexpected chat payload: message is not an object")
        return message

    # ---- Muse Voice Transcribe: speech to text ----

    def transcribe(
        self,
        wav: bytes,
        model: str,
        keywords: list[str] | None = None,
        language_bias: list[str] | None = None,
    ) -> str:
        """Transcribe one push-to-talk recording (mono 16-bit PCM WAV, 16 or 24 kHz).

        ``keywords`` bias the recogniser towards a vocabulary; ``language_bias`` names
        likely languages (a hint only). Not cached: every recording is new.
        """
        request: dict[str, Any] = {"model": model, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
        if keywords:
            request["keywords"] = keywords
        if language_bias:
            request["languageBias"] = language_bias
        files = {
            "request": (None, json.dumps(request), "application/json"),
            "audio": ("speech.wav", wav, "audio/wav"),
        }
        data = self._post(self.routes.transcribe, files=files)
        transcript = data.get("transcript")
        if not isinstance(transcript, str):
            raise MetaApiError("unexpected transcription payload: no transcript")
        return transcript

    def _post_cached(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.cache_dir is None:
            self.billed_requests += 1
            return self._post(route, payload)
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / key[:2] / f"{key}.json"
        if path.is_file():
            cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return cached
        self.billed_requests += 1
        data = self._post(route, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
        return data

    def _post(
        self, route: str, payload: dict[str, Any] | None = None, files: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            wait = self.backoff_s * 2**attempt
            try:
                if files is None:
                    response = self._http.post(route, json=payload)
                else:
                    response = self._http.post(route, files=files)
            except httpx.TransportError as exc:
                if attempt < self.retries:
                    log.warning("%s failed (%s); retrying in %.0fs", route, exc, wait)
                    time.sleep(wait)
                    continue
                raise MetaApiError(f"Meta Model API call to {route} failed: {exc}") from exc
            if response.status_code in RETRY_STATUS and attempt < self.retries:
                log.warning("%s returned %s; retrying in %.0fs", route, response.status_code, wait)
                time.sleep(wait)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text[:300]
                raise MetaApiError(
                    f"Meta Model API call to {route} failed: {exc}; {detail}"
                ) from exc
            break
        body = response.json()
        if not isinstance(body, dict):
            raise MetaApiError(f"unexpected response type from {route}")
        return body


_RECORD = re.compile(
    r"(?P<id>\d+)<\|box;(?P<box>[^|]*)\|>(?:<\|mask;(?P<mask>.*?)\|>)?(?=,\d+<\|box|\s*$)",
    re.MULTILINE,
)


_FRAME = re.compile(r"^<(?P<frame>\d+)f>")


def _image_payload(model: str, text: str, image_jpeg: bytes) -> dict[str, Any]:
    """Build a SAM 3.1 image request: a concept or object prompts, with confidences."""
    image_url = "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode("ascii")
    return {
        "model": model,
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    }


def _output_text(data: dict[str, Any]) -> str:
    return "".join(
        str(part.get("text") or "")
        for item in data["output"]
        if item.get("type") == "message"
        for part in item["content"]
        if part.get("type") == "output_text"
    )


def _box_fields(token: str) -> tuple[tuple[float, float, float, float], float]:
    fields = dict(kv.split("=", 1) for kv in token.split(";"))
    box = (float(fields["x1"]), float(fields["y1"]), float(fields["x2"]), float(fields["y2"]))
    return box, float(fields.get("c", 1.0))


def _to_tracked_boxes(data: dict[str, Any]) -> list[TrackedBox]:
    """Parse a video reply: one ``<Nf>`` line per frame that shows any object."""
    try:
        boxes = []
        for line in _output_text(data).splitlines():
            frame = _FRAME.match(line)
            if frame is None:
                continue
            for m in _RECORD.finditer(line):
                box, score = _box_fields(m["box"])
                boxes.append(TrackedBox(int(frame["frame"]), int(m["id"]), box, score))
        return boxes
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise MetaApiError(f"unexpected segmentation payload: {exc}") from exc


def _to_segment_results(data: dict[str, Any], concept: str) -> list[SegmentResult]:
    """Parse the SAM token stream in a Responses payload into results for ``concept``."""
    try:
        text = _output_text(data)
        results = []
        for m in _RECORD.finditer(text):
            box, score = _box_fields(m["box"])
            mask = m["mask"]
            results.append(
                SegmentResult(
                    concept=concept,
                    box_xyxy=box,
                    score=score,
                    mask=mask.split("data=", 1)[1] if mask and "data=" in mask else None,
                    object_id=int(m["id"]),
                )
            )
        return results
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise MetaApiError(f"unexpected segmentation payload: {exc}") from exc


def _to_chat_text(data: dict[str, Any]) -> str:
    """Map a chat response to its text (adjust at kickoff)."""
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, TypeError, IndexError) as exc:
        raise MetaApiError(f"unexpected chat payload: {exc}") from exc
    if not isinstance(content, str):
        # Muse Spark reasons before answering; a token cap can leave content null.
        reason = choice.get("finish_reason", "unknown")
        raise MetaApiError(f"chat reply has no text (finish_reason={reason})")
    return content
