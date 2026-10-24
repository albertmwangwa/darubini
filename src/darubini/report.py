"""Deterministic slide reports in English and Kiswahili.

This template is the source of truth for numbers. Muse Spark may add a narrative
(see :mod:`darubini.meta.reviewer`), but the figures always come from here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from darubini.counting import CountStatus, SlideCount

DISCLAIMER = {
    "en": (
        "Decision-support estimate only. A qualified microscopist must confirm "
        "this result before any clinical use."
    ),
    "sw": (
        "Haya ni makadirio ya kusaidia uamuzi tu. Mtaalamu wa hadubini aliyehitimu "
        "lazima athibitishe matokeo kabla ya matumizi yoyote ya kitabibu."
    ),
}

STATUS_TEXT = {
    "en": {
        CountStatus.COMPLETE: "Count complete",
        CountStatus.CONTINUE: "Keep counting",
        CountStatus.NEGATIVE: "No parasites seen",
    },
    "sw": {
        CountStatus.COMPLETE: "Hesabu imekamilika",
        CountStatus.CONTINUE: "Endelea kuhesabu",
        CountStatus.NEGATIVE: "Hakuna vimelea vilivyoonekana",
    },
}

LABELS = {
    "en": {
        "fields": "Fields examined",
        "usable": "usable",
        "parasites": "Parasites counted",
        "wbc": "White blood cells counted",
        "density": "Estimated density",
        "unit": "parasites/µL",
        "status": "Status",
        "na": "not yet available",
    },
    "sw": {
        "fields": "Sehemu zilizochunguzwa",
        "usable": "zinafaa",
        "parasites": "Vimelea vilivyohesabiwa",
        "wbc": "Chembe nyeupe za damu zilizohesabiwa",
        "density": "Makadirio ya msongamano",
        "unit": "vimelea/µL",
        "status": "Hali",
        "na": "bado haipatikani",
    },
}


@dataclass(frozen=True)
class Report:
    """A rendered report plus its structured facts."""

    language: str
    text: str
    facts: dict[str, Any]


def render(count: SlideCount, language: str = "en") -> Report:
    """Render a slide count as a short report in ``en`` or ``sw``."""
    if language not in LABELS:
        raise ValueError(f"unsupported language {language!r}; use 'en' or 'sw'")
    lab = LABELS[language]
    density = (
        f"{count.density_per_ul:,.0f} {lab['unit']}"
        if count.density_per_ul is not None
        else lab["na"]
    )
    lines = [
        f"{lab['fields']}: {count.fields_examined} ({count.usable_fields} {lab['usable']})",
        f"{lab['parasites']}: {count.parasites}",
        f"{lab['wbc']}: {count.wbcs}",
        f"{lab['density']}: {density}",
        f"{lab['status']}: {STATUS_TEXT[language][count.status]}",
        "",
        DISCLAIMER[language],
    ]
    facts = asdict(count)
    facts["status"] = count.status.value
    return Report(language=language, text="\n".join(lines), facts=facts)
