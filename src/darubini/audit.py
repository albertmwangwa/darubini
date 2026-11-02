"""Audit a slide's parasite detections with Muse Spark as a second reader.

The verifier's false positives are not spread evenly: on some slides platelets,
bacteria and stain debris pass as parasites, and on a low-density slide they can
multiply the count several times over. Muse Spark looks at a random sample of
detections, shown as one numbered montage, and says which are parasites. The
share it confirms estimates the slide's precision.

The audit never changes the WHO count. It adds an audited estimate beside it and
flags the slide for manual review when the confirmed share is low.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from darubini.meta.client import MetaApiError, MetaModelClient
from darubini.types import Detection

#: Detections Muse Spark reviews per slide.
AUDIT_SAMPLE = 20
#: Below this confirmed share, the slide is flagged as likely over-counted.
#: Chosen on 8 NIH validation slides: the 5 slides over-counted by 1.7x to 15x
#: all scored 0.50 or less; the 3 accurate slides scored 0.65 or more. Repeated
#: audits (2 Nov) show slides over-counted about 1.7x land near this line, so the
#: flag is reliable for gross over-counts and borderline for mild ones.
FLAG_BELOW = 0.6
TILE = 128
COLUMNS = 5

AUDIT_SYSTEM = (
    "You are an expert malaria microscopist reviewing candidate objects from a "
    "Giemsa-stained THICK blood film. Each numbered tile is centred on one candidate; "
    "judge only the object at the centre. In a thick film the red cells are lysed, so "
    "Plasmodium falciparum trophozoites appear free in the background as a compact, "
    "sharply defined, deep red-purple chromatin dot (sometimes two) with a small amount "
    "of blue-purple cytoplasm beside it, often scant, comma- or exclamation-mark-shaped. "
    "Count these as parasites even when cytoplasm is barely visible. NOT parasites: "
    "platelets (pale pink-violet, granular, irregular clumps, often several together, no "
    "distinct chromatin dot), rods or bacteria, stain precipitate, fibres, edges of the "
    "field and pale out-of-focus smudges. Look at every tile in order, 1 to N, and decide "
    "for each one. Reply with JSON only, one entry per tile in order: "
    '{"tiles": [{"n": 1, "parasite": true}, {"n": 2, "parasite": false}, ...]}.'
)


def crop_detection(image: NDArray[np.uint8], det: Detection) -> NDArray[np.uint8]:
    """Cut a square crop around a detection, about 2% of the image's long side wide."""
    h, w = image.shape[:2]
    half = max(24, round(max(h, w) / 100))
    cx, cy = (round(v) for v in det.box.center)
    pad = np.pad(image[..., :3], ((half, half), (half, half), (0, 0)), mode="edge")
    return np.ascontiguousarray(pad[cy : cy + 2 * half, cx : cx + 2 * half])


def montage(crops: Sequence[NDArray[np.uint8]]) -> bytes:
    """Lay out numbered tiles (1-based), five per row, as a JPEG."""
    rows = max(1, -(-len(crops) // COLUMNS))
    sheet = Image.new("RGB", (COLUMNS * TILE, rows * (TILE + 18)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, crop in enumerate(crops):
        x, y = (i % COLUMNS) * TILE, (i // COLUMNS) * (TILE + 18)
        sheet.paste(Image.fromarray(crop).resize((TILE, TILE)), (x, y))
        draw.text((x + 4, y + TILE + 2), str(i + 1), fill="black")
    buf = io.BytesIO()
    sheet.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def parse_confirmed(reply: str, n_tiles: int) -> set[int]:
    """Tile numbers (1-based) Muse Spark called parasites, ignoring out-of-range ones.

    Reads the per-tile reply the prompt asks for, and the older
    ``{"parasites": [...]}`` list form.
    """
    text = reply.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
        if "tiles" in data:
            numbers = [int(t["n"]) for t in data["tiles"] if t.get("parasite") is True]
        else:
            numbers = [int(n) for n in data["parasites"]]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        tail = reply.split("parasites", 1)[-1]
        numbers = [int(n) for n in re.findall(r"\d+", tail)]
    return {n for n in numbers if 1 <= n <= n_tiles}


@dataclass(frozen=True)
class AuditResult:
    """What the second reader confirmed in a random sample of detections."""

    sampled: int
    confirmed: int
    parasites_counted: int

    @property
    def confirmed_share(self) -> float:
        """Share of sampled detections confirmed as parasites."""
        return self.confirmed / self.sampled if self.sampled else 1.0

    @property
    def audited_parasites(self) -> int:
        """Counted parasites scaled by the confirmed share."""
        return round(self.parasites_counted * self.confirmed_share)

    @property
    def flagged(self) -> bool:
        """True when the count is likely inflated and needs manual review."""
        return self.sampled > 0 and self.confirmed_share < FLAG_BELOW

    def facts(self) -> dict[str, object]:
        """Plain facts for tool results and reports."""
        return {
            "sampled": self.sampled,
            "confirmed": self.confirmed,
            "confirmed_percent": round(100 * self.confirmed_share),
            "audited_parasites": self.audited_parasites,
            "flagged": self.flagged,
        }


class MuseAuditor:
    """Samples detections and asks Muse Spark which are parasites."""

    def __init__(
        self, client: MetaModelClient, model: str, sample: int = AUDIT_SAMPLE, seed: int = 0
    ) -> None:
        self.client = client
        self.model = model
        self.sample = sample
        self.seed = seed

    def audit(self, crops: Sequence[NDArray[np.uint8]]) -> AuditResult:
        """Review a random sample of parasite crops from one slide."""
        if not crops:
            return AuditResult(0, 0, 0)
        rng = np.random.default_rng(self.seed)
        pick = rng.choice(len(crops), min(self.sample, len(crops)), replace=False)
        chosen = [crops[i] for i in sorted(pick)]
        reply = self.client.chat(
            self.model,
            AUDIT_SYSTEM,
            "Which numbered tiles show a malaria parasite?",
            image_jpeg=montage(chosen),
        )
        if not reply.strip():
            raise MetaApiError("empty audit reply")
        confirmed = parse_confirmed(reply, len(chosen))
        return AuditResult(len(chosen), len(confirmed), len(crops))


AUDIT_TEXT = {
    "en": {
        "line": (
            "Second-reader audit: Muse Spark confirmed {confirmed} of {sampled} sampled "
            "detections ({percent}%). Audited estimate: {audited} parasites."
        ),
        "flag": (
            "Warning: the count is probably inflated by platelets or debris. "
            "A microscopist must review this slide."
        ),
    },
    "sw": {
        "line": (
            "Ukaguzi wa msomaji wa pili: Muse Spark ilithibitisha {confirmed} kati ya "
            "{sampled} vilivyochaguliwa ({percent}%). Makadirio baada ya ukaguzi: "
            "vimelea {audited}."
        ),
        "flag": (
            "Tahadhari: hesabu huenda imeongezeka kwa sababu ya chembe sahani au uchafu. "
            "Mtaalamu wa hadubini lazima akague slaidi hii."
        ),
    },
}


def render_audit(result: AuditResult, language: str = "en") -> str:
    """Render the audit as one or two report lines in ``en`` or ``sw``."""
    text = AUDIT_TEXT[language]
    lines = [
        text["line"].format(
            confirmed=result.confirmed,
            sampled=result.sampled,
            percent=round(100 * result.confirmed_share),
            audited=result.audited_parasites,
        )
    ]
    if result.flagged:
        lines.append(text["flag"])
    return "\n".join(lines)
