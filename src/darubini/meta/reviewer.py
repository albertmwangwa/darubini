"""Muse Spark as a second reader: field quality review and report drafting.

The model never sets the count. It reviews image quality, flags fields a human
should look at, and writes the narrative around numbers the pipeline computed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from darubini.counting import SlideCount
from darubini.meta.client import MetaApiError, MetaModelClient

QC_SYSTEM = (
    "You are a quality-control assistant for malaria thick blood smear microscopy. "
    "Judge only image quality: focus, staining, smear thickness, debris, artefacts. "
    "Do not diagnose. Reply with JSON only: "
    '{"usable": bool, "issues": [string], "advice": string}.'
)

REPORT_SYSTEM = (
    "You write short, plain-language microscopy summaries for a laboratory technician. "
    "Use only the numbers provided. Never change them, never add a diagnosis or treatment "
    "advice, and always end by saying a qualified microscopist must confirm the result."
)


@dataclass(frozen=True)
class FieldReview:
    """Muse Spark's quality opinion on one field."""

    usable: bool
    issues: tuple[str, ...]
    advice: str


class MuseReviewer:
    """Wraps Muse Spark calls with strict parsing and safe fallbacks."""

    def __init__(self, client: MetaModelClient, model: str) -> None:
        self.client = client
        self.model = model

    def review_field(self, image_jpeg: bytes) -> FieldReview:
        """Ask for a JSON quality verdict on one field image."""
        reply = self.client.chat(
            self.model, QC_SYSTEM, "Assess this field image.", image_jpeg=image_jpeg
        )
        try:
            data = json.loads(_strip_code_fence(reply))
            return FieldReview(
                usable=bool(data["usable"]),
                issues=tuple(str(i) for i in data.get("issues", [])),
                advice=str(data.get("advice", "")),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MetaApiError(f"could not parse QC reply: {exc}") from exc

    def draft_report(self, count: SlideCount, language: str = "en") -> str:
        """Write a narrative summary around computed numbers, in English or Kiswahili."""
        lang = "Kiswahili" if language == "sw" else "English"
        facts = {
            "fields_examined": count.fields_examined,
            "usable_fields": count.usable_fields,
            "parasites_counted": count.parasites,
            "wbc_counted": count.wbcs,
            "status": count.status.value,
            "density_per_ul": count.density_per_ul,
            "reason": count.reason,
        }
        return self.client.chat(
            self.model,
            REPORT_SYSTEM,
            f"Write the summary in {lang}. Facts: {json.dumps(facts)}",
        )


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()
