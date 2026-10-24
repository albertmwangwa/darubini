"""Thin HTTP client for the Meta Model API.

The exact routes and payload shapes are published to participants at the
hackathon kickoff (26 Oct 2026). Until then every route and field name lives in
:class:`ApiRoutes` and in the two ``_to_*`` mapping functions, so wiring the real
API is a one-file change with the rest of the pipeline untouched.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from darubini.config import Settings


class MetaApiError(RuntimeError):
    """Raised when the Meta Model API returns an error or an unexpected payload."""


@dataclass(frozen=True)
class ApiRoutes:
    """Relative routes. Confirm against the official docs at kickoff."""

    segment: str = "/v1/segment"
    chat: str = "/v1/chat/completions"


@dataclass(frozen=True)
class SegmentResult:
    """One instance returned by concept segmentation."""

    concept: str
    box_xyxy: tuple[float, float, float, float]
    score: float


class MetaModelClient:
    """Calls SAM 3 (concept segmentation) and Muse Spark (multimodal chat)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 60.0,
        routes: ApiRoutes | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.routes = routes or ApiRoutes()
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
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    # ---- SAM 3: promptable concept segmentation ----

    def segment_concepts(
        self, image_jpeg: bytes, concepts: list[str], model: str
    ) -> list[SegmentResult]:
        """Find every instance of each text concept in an image."""
        payload = {
            "model": model,
            "image": base64.b64encode(image_jpeg).decode("ascii"),
            "prompts": [{"type": "text", "text": c} for c in concepts],
        }
        data = self._post(self.routes.segment, payload)
        return _to_segment_results(data)

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

    def _post(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._http.post(route, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MetaApiError(f"Meta Model API call to {route} failed: {exc}") from exc
        body = response.json()
        if not isinstance(body, dict):
            raise MetaApiError(f"unexpected response type from {route}")
        return body


def _to_segment_results(data: dict[str, Any]) -> list[SegmentResult]:
    """Map the segmentation response to :class:`SegmentResult` (adjust at kickoff)."""
    try:
        return [
            SegmentResult(
                concept=str(item["concept"]),
                box_xyxy=(
                    float(item["box"][0]),
                    float(item["box"][1]),
                    float(item["box"][2]),
                    float(item["box"][3]),
                ),
                score=float(item.get("score", 1.0)),
            )
            for item in data["instances"]
        ]
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise MetaApiError(f"unexpected segmentation payload: {exc}") from exc


def _to_chat_text(data: dict[str, Any]) -> str:
    """Map a chat response to its text (adjust at kickoff)."""
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, TypeError, IndexError) as exc:
        raise MetaApiError(f"unexpected chat payload: {exc}") from exc
