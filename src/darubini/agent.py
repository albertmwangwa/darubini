"""Muse Spark as a counting agent: it runs the slide through deterministic tools.

The agent decides how many fields to examine at a time, when to ask for a second
opinion on image quality, which fields to exclude and why, and when the slide is
done; then it writes the narrative in English or Kiswahili. It never produces a
count itself. Guardrails:

- every number comes from :mod:`darubini.counting` through the tools;
- ``finish`` is refused while the WHO counting rule is unmet and fields remain;
- a narrative that quotes a number the tools never returned is dropped;
- if the agent stalls or the API fails, the remaining fields are counted
  deterministically and the report says so.
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from darubini.audit import AuditResult, MuseAuditor, crop_detection, render_audit
from darubini.counting import CountStatus, SlideCount, evaluate_slide
from darubini.meta.client import MetaApiError, MetaModelClient
from darubini.meta.reviewer import MuseReviewer
from darubini.pipeline import Pipeline
from darubini.report import Report, render
from darubini.types import FieldResult, ObjectClass
from darubini.video import resize_to

log = logging.getLogger(__name__)

#: Fields the agent may examine in one tool call.
MAX_BATCH = 10
#: Long side of the JPEG kept for each field, for the quality second reader.
REVIEW_SIDE = 1024
EXCLUDED_FLAG = "blocking: excluded by agent"

FieldSource = Callable[[], NDArray[np.uint8]]


@dataclass
class CapturedField:
    """A field analysed before the agent runs, as in the capture app.

    The agent reuses ``result`` instead of segmenting again; ``image`` is what the
    quality reviewer sees, and ``crops`` are the parasite crops for the audit.
    """

    result: FieldResult
    image: NDArray[np.uint8]
    crops: list[NDArray[np.uint8]] = field(default_factory=list)

    @classmethod
    def from_image(cls, image: NDArray[np.uint8], result: FieldResult) -> CapturedField:
        """Wrap an analysed photo, cutting a crop for each parasite."""
        crops = [
            crop_detection(image, d) for d in result.detections if d.cls is ObjectClass.PARASITE
        ]
        return cls(result, image, crops)


SYSTEM = """You are Darubini, a counting assistant for malaria thick blood smear microscopy \
in a Tanzanian laboratory. You run the count for one slide with tools; you never count or \
estimate numbers yourself.

Procedure (WHO thick-film rule, applied by the tools):
1. Call examine_next_fields to analyse fields in capture order. Use small batches (2-3) at \
first, larger ones (up to 10) once the slide looks consistent.
2. Right after each batch, before examining more, call review_field on any field with \
warnings or numbers that look implausible next to the others. Call exclude_field only for \
blocking problems: out of focus, smear far too thick, or no usable stain. Pale or bright \
fields where cells are still clear stay in. Never exclude a field because it contains \
parasites. Once the stop rule is met, fields can no longer be excluded; mention any \
concern in the narrative instead.
3. Stop when a tool reports stop_rule_met or no fields remain. If parasites were counted, \
call audit_parasites: a second reader checks a random sample of the detections.
4. Call finish with a 3-5 sentence narrative for the technician in the requested language. \
If the audit is flagged, say plainly that the count is probably inflated and needs manual \
review. Quote only numbers the tools returned. Do not diagnose or suggest treatment; \
say a qualified microscopist must confirm the result."""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "examine_next_fields",
            "description": (
                "Quality-check and segment the next fields in capture order. Returns each "
                "field's parasites, white blood cells and quality flags, and the running count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": f"How many fields to examine, 1 to {MAX_BATCH}.",
                    }
                },
                "required": ["count"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_field",
            "description": (
                "Ask an image-quality reviewer (vision model) whether an examined field is "
                "usable: focus, staining, thickness, debris."
            ),
            "parameters": {
                "type": "object",
                "properties": {"field_id": {"type": "string"}},
                "required": ["field_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exclude_field",
            "description": "Exclude an examined field from the count, with a reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["field_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_parasites",
            "description": (
                "Have a second reader check a random sample of this slide's parasite "
                "detections. Returns how many it confirmed and an audited estimate."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_count",
            "description": "Return the running slide count and what the counting rule says.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "End the session with a short narrative for the technician.",
            "parameters": {
                "type": "object",
                "properties": {"narrative": {"type": "string"}},
                "required": ["narrative"],
            },
        },
    },
]


def _jpeg(image: NDArray[np.uint8]) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(resize_to(image, REVIEW_SIDE)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _field_summary(result: FieldResult) -> dict[str, Any]:
    return {
        "field_id": result.field_id,
        "usable": result.usable,
        "parasites": result.parasites,
        "wbcs": result.wbcs,
        "flags": result.quality_flags,
    }


class SlideSession:
    """The deterministic side of the agent: state and tool implementations."""

    def __init__(
        self,
        pipeline: Pipeline,
        sources: Sequence[tuple[str, FieldSource | CapturedField]],
        reviewer: MuseReviewer | None = None,
        auditor: MuseAuditor | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.sources = list(sources)
        self.reviewer = reviewer
        self.auditor = auditor
        self.fields: list[FieldResult] = []
        self.excluded: dict[str, str] = {}
        self.audit: AuditResult | None = None
        self._jpegs: dict[str, bytes] = {}
        self._crops: dict[str, list[NDArray[np.uint8]]] = {}

    @property
    def remaining(self) -> int:
        """Fields not yet examined."""
        return len(self.sources) - len(self.fields)

    def count(self) -> SlideCount:
        """Apply the counting rule to the fields examined so far."""
        return evaluate_slide(self.fields, self.pipeline.protocol)

    def decided(self) -> bool:
        """Return True once the counting rule has reached a result."""
        return self.count().status is not CountStatus.CONTINUE

    def count_facts(self) -> dict[str, Any]:
        """Return the running count as plain JSON-ready facts."""
        c = self.count()
        facts = asdict(c)
        facts["status"] = c.status.value
        if c.density_per_ul is not None:
            facts["density_per_ul"] = round(c.density_per_ul)
        facts["fields_remaining"] = self.remaining
        facts["stop_rule_met"] = c.status is not CountStatus.CONTINUE
        return facts

    # ---- tools ----

    def examine_next_fields(self, count: int = 1) -> dict[str, Any]:
        """Analyse up to ``count`` more fields, stopping early once the rule is met."""
        if self.decided():
            return {"error": "the counting rule is already met; call finish", **self.count_facts()}
        n = max(1, min(int(count), MAX_BATCH))
        examined: list[dict[str, Any]] = []
        for _ in range(n):
            if self.remaining == 0:
                break
            field_id, source = self.sources[len(self.fields)]
            if isinstance(source, CapturedField):
                image = source.image
                # A copy, so exclusions do not change the caller's result.
                result = FieldResult(
                    field_id, list(source.result.detections), list(source.result.quality_flags)
                )
                self.fields.append(result)
                if self.reviewer is not None:
                    self._jpegs[field_id] = _jpeg(image)
                if self.auditor is not None:
                    self._crops[field_id] = list(source.crops)
                examined.append(_field_summary(result))
                if self.decided():
                    break
                continue
            image = source()
            try:
                result = self.pipeline.analyse_field(image, field_id)
            except MetaApiError as exc:
                # The field stays unexamined, so a retry picks it up again.
                return {
                    "examined": examined,
                    "error": f"segmentation failed on {field_id}: {exc}",
                    "running": self.count_facts(),
                }
            self.fields.append(result)
            if self.reviewer is not None:
                self._jpegs[field_id] = _jpeg(image)
            if self.auditor is not None:
                self._crops[field_id] = [
                    crop_detection(image, d)
                    for d in result.detections
                    if d.cls is ObjectClass.PARASITE
                ]
            examined.append(_field_summary(result))
            if self.decided():
                break
        return {"examined": examined, "running": self.count_facts()}

    def review_field(self, field_id: str) -> dict[str, Any]:
        """Second-reader quality review of one examined field."""
        if self.reviewer is None:
            return {"error": "no reviewer is configured"}
        jpeg = self._jpegs.get(field_id)
        if jpeg is None:
            return {"error": f"unknown or unexamined field {field_id!r}"}
        try:
            review = self.reviewer.review_field(jpeg)
        except MetaApiError as exc:
            return {"error": f"review failed: {exc}"}
        return {"field_id": field_id, **asdict(review)}

    def exclude_field(self, field_id: str, reason: str) -> dict[str, Any]:
        """Mark an examined field unusable so it leaves the count.

        Refused once the counting rule is met: excluding then would reopen a finished
        count, often with no fields left to replace the excluded one.
        """
        if self.decided():
            return {
                "error": "the counting rule is already met; fields can no longer be excluded. "
                "Mention the concern in the narrative.",
                **self.count_facts(),
            }
        for f in self.fields:
            if f.field_id == field_id:
                if field_id not in self.excluded:
                    self.excluded[field_id] = reason
                    f.quality_flags.append(f"{EXCLUDED_FLAG}: {reason}")
                return {"excluded": field_id, "running": self.count_facts()}
        return {"error": f"unknown or unexamined field {field_id!r}"}

    def audit_parasites(self) -> dict[str, Any]:
        """Second-reader check of a random sample of the counted parasites."""
        if self.auditor is None:
            return {"error": "no auditor is configured"}
        crops = [c for f in self.fields if f.usable for c in self._crops.get(f.field_id, [])]
        try:
            self.audit = self.auditor.audit(crops)
        except MetaApiError as exc:
            return {"error": f"audit failed: {exc}"}
        return {**self.audit.facts(), "parasites_counted": self.audit.parasites_counted}

    def audit_needed(self) -> bool:
        """Return True when an auditor is set and the current count is not audited."""
        if self.auditor is None:
            return False
        parasites = self.count().parasites
        return parasites > 0 and (self.audit is None or self.audit.parasites_counted != parasites)

    def get_count(self) -> dict[str, Any]:
        """Return the running count."""
        return self.count_facts()

    def finish_allowed(self) -> str | None:
        """Why ``finish`` must be refused now, or None if it may proceed."""
        if not self.decided() and self.remaining > 0:
            c = self.count()
            return (
                f"the counting rule is not met ({c.reason}) and {self.remaining} fields "
                "remain; keep examining"
            )
        if self.audit_needed():
            return "parasites were counted but not audited; call audit_parasites first"
        return None

    def examine_rest(self) -> None:
        """Deterministic fallback: examine fields until the rule is met or none remain."""
        while self.remaining and not self.decided():
            if "error" in self.examine_next_fields(MAX_BATCH):
                break
        if self.audit_needed():
            self.audit_parasites()


@dataclass(frozen=True)
class AgentStep:
    """One tool call the agent made, for the audit trail and the demo UI."""

    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class AgentResult:
    """Outcome of an agent session."""

    fields: list[FieldResult]
    count: SlideCount
    report: Report
    narrative: str | None
    steps: list[AgentStep] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    audit: AuditResult | None = None
    #: True when the agent itself reached ``finish``; False if the fallback ran.
    finished_by_agent: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """The report with the agent's narrative, if one was kept."""
        parts = [self.report.text]
        if self.audit is not None and self.audit.sampled:
            parts.insert(0, render_audit(self.audit, self.report.language) + "\n")
        if self.narrative:
            parts.insert(0, self.narrative.strip() + "\n")
        if self.excluded:
            parts.append("")
            parts.extend(f"- {fid}: {why}" for fid, why in self.excluded.items())
        return "\n".join(parts)


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def unsupported_numbers(narrative: str, allowed: Sequence[Any]) -> list[str]:
    """Numbers in ``narrative`` that match none of the ``allowed`` values.

    Compared after removing thousands separators, with whole-number rounding.
    """
    ok: set[float] = set()
    for v in allowed:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        ok.update({float(v), float(round(v))})
    bad = []
    for token in _NUMBER.findall(narrative):
        value = float(token.replace(",", ""))
        if value not in ok and float(round(value)) not in ok:
            bad.append(token)
    return bad


def _numbers_in(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers_in(v)]
    if isinstance(obj, list):
        return [n for v in obj for n in _numbers_in(v)]
    if isinstance(obj, (int, float)):
        return [obj]
    if isinstance(obj, str):
        return [float(t.replace(",", "")) for t in _NUMBER.findall(obj)]
    return []


class CountingAgent:
    """Runs a :class:`SlideSession` with Muse Spark choosing the tool calls."""

    def __init__(
        self, client: MetaModelClient, model: str, max_turns: int = 40, max_tokens: int = 4000
    ) -> None:
        self.client = client
        self.model = model
        self.max_turns = max_turns
        self.max_tokens = max_tokens

    def run(
        self,
        session: SlideSession,
        language: str = "en",
        on_step: Callable[[AgentStep], None] | None = None,
    ) -> AgentResult:
        """Count one slide; always returns a result, falling back if the agent fails.

        ``on_step`` is called after every tool call, for live progress displays.
        """
        lang = "Kiswahili" if language == "sw" else "English"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Count this slide. {len(session.sources)} fields were captured. "
                    f"Write the narrative in {lang}."
                ),
            },
        ]
        steps: list[AgentStep] = []
        notes: list[str] = []
        narrative: str | None = None
        finished = False
        nudged = False
        for _ in range(self.max_turns):
            try:
                message = self.client.chat_turn(
                    self.model, messages, TOOLS, max_tokens=self.max_tokens
                )
            except MetaApiError as exc:
                notes.append(f"agent stopped: {exc}")
                break
            calls = message.get("tool_calls") or []
            messages.append(
                {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
                if calls
                else {"role": "assistant", "content": message.get("content") or ""}
            )
            if not calls:
                if nudged:
                    notes.append("agent stopped calling tools")
                    break
                nudged = True
                messages.append(
                    {
                        "role": "user",
                        "content": "Use the tools. Call finish when the slide is done.",
                    }
                )
                continue
            for call in calls:
                name, args, result = self._dispatch(session, call)
                steps.append(AgentStep(name, args, result))
                if on_step is not None:
                    on_step(steps[-1])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(result),
                    }
                )
                if name == "finish" and "error" not in result:
                    narrative = str(args.get("narrative", "")) or None
                    finished = True
            if finished:
                break
        else:
            notes.append(f"agent reached the {self.max_turns}-turn limit")

        if not finished or session.finish_allowed() is not None:
            session.examine_rest()
            finished = False
            notes.append("remaining fields were counted without the agent")

        count = session.count()
        report = render(count, language)
        if narrative is not None:
            allowed = [n for s in steps for n in _numbers_in(s.result)]
            allowed += _numbers_in(report.facts) + _numbers_in(asdict(session.pipeline.protocol))
            bad = unsupported_numbers(narrative, allowed)
            if bad:
                notes.append(f"narrative dropped: quoted numbers the tools never returned {bad}")
                narrative = None
        return AgentResult(
            fields=session.fields,
            count=count,
            report=report,
            narrative=narrative,
            steps=steps,
            excluded=dict(session.excluded),
            audit=session.audit,
            finished_by_agent=finished,
            notes=notes,
        )

    @staticmethod
    def _dispatch(
        session: SlideSession, call: dict[str, Any]
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        fn = call.get("function") or {}
        name = str(fn.get("name", ""))
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                raise TypeError("arguments must be an object")
        except (json.JSONDecodeError, TypeError) as exc:
            return name, {}, {"error": f"bad arguments: {exc}"}
        try:
            if name == "examine_next_fields":
                result = session.examine_next_fields(int(args.get("count", 1)))
            elif name == "review_field":
                result = session.review_field(str(args["field_id"]))
            elif name == "exclude_field":
                result = session.exclude_field(str(args["field_id"]), str(args["reason"]))
            elif name == "audit_parasites":
                result = session.audit_parasites()
            elif name == "get_count":
                result = session.get_count()
            elif name == "finish":
                refusal = session.finish_allowed()
                result = {"error": refusal} if refusal else {"ok": True, **session.count_facts()}
            else:
                result = {"error": f"unknown tool {name!r}"}
        except (KeyError, ValueError, TypeError) as exc:
            result = {"error": f"bad arguments: {exc}"}
        log.info("agent -> %s(%s)", name, json.dumps(args)[:120])
        return name, args, result
