"""Live capture sessions for the phone app.

A technician captures one field (photo) or one panned clip at a time. Each upload
is analysed at once and the reply says what to do next: retake, move on, or
finish. Finishing runs the Muse Spark agent over the captured fields in a
background thread, so the phone can poll and show each tool call as it happens.

Sessions live in memory: this is a single-process demo server, not a records
system, and no patient data is kept.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from darubini.agent import AgentResult, AgentStep, CapturedField, CountingAgent, SlideSession
from darubini.audit import MuseAuditor, crop_detection, render_audit
from darubini.counting import CountStatus, SlideCount, evaluate_slide
from darubini.meta.client import MetaModelClient
from darubini.meta.reviewer import MuseReviewer
from darubini.pipeline import Pipeline
from darubini.quality import blocking_text
from darubini.report import render
from darubini.tracking import ClipCount, Track, Tracker, count_clip
from darubini.types import Detection, FieldResult, ObjectClass
from darubini.video import Frame, resize_to

#: Long side kept for each captured field; enough for the quality reviewer.
STORED_SIDE = 1024
MAX_SESSIONS = 50
SESSION_TTL_S = 4 * 3600

Action = Literal["retake", "next", "finish"]
JobState = Literal["idle", "running", "done", "failed"]


@dataclass
class ReportJob:
    """The agent run behind a session's report."""

    state: JobState = "idle"
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class CaptureSession:
    """Fields captured for one slide, in order."""

    session_id: str
    created: float
    fields: list[tuple[str, CapturedField]] = field(default_factory=list)
    job: ReportJob = field(default_factory=ReportJob)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def count(self, pipeline: Pipeline) -> SlideCount:
        """Apply the counting rule to the fields kept so far."""
        return evaluate_slide([c.result for _, c in self.fields], pipeline.protocol)


def next_action(usable: bool, count: SlideCount) -> dict[str, Any]:
    """Say what the technician should do after this capture."""
    if not usable:
        return {"action": "retake", "reason": "quality"}
    if count.status is CountStatus.CONTINUE:
        return {"action": "next", "reason": count.reason}
    return {"action": "finish", "reason": count.reason}


def running_facts(count: SlideCount, pipeline: Pipeline) -> dict[str, Any]:
    """Return the running count plus the WBC target being worked towards."""
    facts = asdict(count)
    facts["status"] = count.status.value
    if count.density_per_ul is not None:
        facts["density_per_ul"] = round(count.density_per_ul)
    p = pipeline.protocol
    facts["wbc_target"] = (
        p.extended_wbc_target
        if count.wbcs >= p.first_wbc_target and count.parasites < p.min_parasites_at_first_target
        else p.first_wbc_target
    )
    return facts


def detections_json(result: FieldResult) -> list[dict[str, Any]]:
    """Convert detections to plain JSON for the overlay."""
    return [
        {
            "class": d.cls.value,
            "box": [d.box.x_min, d.box.y_min, d.box.x_max, d.box.y_max],
            "score": round(d.score, 3),
        }
        for d in result.detections
    ]


def _captured_from_clip(frames: Sequence[Frame], clip: ClipCount, field_id: str) -> CapturedField:
    crops = [
        crop_detection(np.asarray(frames[t.first_frame]), _first_detection(t))
        for t in clip.tracks
        if t.cls is ObjectClass.PARASITE
    ]
    middle = np.asarray(frames[len(frames) // 2])
    return CapturedField(clip.as_field_result(field_id), resize_to(middle, STORED_SIDE), crops)


def _first_detection(track: Track) -> Detection:
    return Detection(track.cls, track.boxes[track.first_frame], track.score)


class SessionStore:
    """In-memory capture sessions with a size cap and expiry."""

    def __init__(self, max_sessions: int = MAX_SESSIONS, ttl_s: float = SESSION_TTL_S) -> None:
        self.max_sessions = max_sessions
        self.ttl_s = ttl_s
        self._sessions: dict[str, CaptureSession] = {}
        self._lock = threading.Lock()

    def create(self) -> CaptureSession:
        """Start a session, dropping expired ones and the oldest past the cap."""
        now = time.time()
        with self._lock:
            for sid in [s for s, v in self._sessions.items() if now - v.created > self.ttl_s]:
                del self._sessions[sid]
            while len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions.values(), key=lambda v: v.created)
                del self._sessions[oldest.session_id]
            session = CaptureSession(uuid.uuid4().hex, now)
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> CaptureSession:
        """Return a live session; KeyError if unknown or expired."""
        with self._lock:
            session = self._sessions[session_id]
            if time.time() - session.created > self.ttl_s:
                del self._sessions[session_id]
                raise KeyError(session_id)
            return session


def add_field(
    session: CaptureSession, pipeline: Pipeline, image: NDArray[np.uint8], max_fields: int
) -> dict[str, Any]:
    """Analyse one photo; keep it only if usable."""
    with session.lock:
        if len(session.fields) >= max_fields:
            raise ValueError(f"at most {max_fields} fields per slide")
        field_id = f"field-{len(session.fields) + 1:03d}"
        result = pipeline.analyse_field(image, field_id)
        if result.usable:
            captured = CapturedField.from_image(image, result)
            captured.image = resize_to(image, STORED_SIDE)
            session.fields.append((field_id, captured))
        count = session.count(pipeline)
    return {
        "field": {
            "field_id": field_id,
            "kept": result.usable,
            "usable": result.usable,
            "flags": result.quality_flags,
            "blocking_text": {
                lang: blocking_text(result.quality_flags, lang) for lang in ("en", "sw")
            },
            "parasites": result.parasites,
            "wbcs": result.wbcs,
            "width": image.shape[1],
            "height": image.shape[0],
            "detections": detections_json(result),
        },
        "running": running_facts(count, pipeline),
        "next": next_action(result.usable, count),
    }


def add_clip(
    session: CaptureSession,
    pipeline: Pipeline,
    frames: Sequence[Frame],
    tracker: Tracker,
    max_fields: int,
    keyframe_every: int = 10,
) -> dict[str, Any]:
    """Count a panned clip with tracking, so each object counts once."""
    if not frames:
        raise ValueError("the clip has no frames")
    with session.lock:
        if len(session.fields) >= max_fields:
            raise ValueError(f"at most {max_fields} fields per slide")
        field_id = f"clip-{len(session.fields) + 1:03d}"
        clip = count_clip(frames, pipeline.segmenter, tracker, keyframe_every=keyframe_every)
        session.fields.append((field_id, _captured_from_clip(frames, clip, field_id)))
        count = session.count(pipeline)
    h, w = np.asarray(frames[0]).shape[:2]
    return {
        "clip": {
            "field_id": field_id,
            "frames": clip.frames,
            "keyframes": len(clip.keyframes),
            "tracker": tracker.name,
            "parasites": clip.parasites,
            "wbcs": clip.wbcs,
            "naive_parasites": clip.naive.get(ObjectClass.PARASITE, 0),
            "naive_wbcs": clip.naive.get(ObjectClass.WBC, 0),
            "width": w,
            "height": h,
        },
        "running": running_facts(count, pipeline),
        "next": next_action(True, count),
    }


def result_json(result: AgentResult) -> dict[str, Any]:
    """Convert an agent result to plain JSON for the report screen."""
    language = result.report.language
    return {
        "language": language,
        "report": result.report.text,
        "narrative": result.narrative,
        "audit": result.audit.facts() if result.audit else None,
        "audit_text": render_audit(result.audit, language)
        if result.audit and result.audit.sampled
        else None,
        "excluded": result.excluded,
        "slide": result.report.facts,
        "finished_by_agent": result.finished_by_agent,
        "notes": result.notes,
        "text": result.text,
    }


def step_json(step: AgentStep) -> dict[str, Any]:
    """Trim one tool call for the live view."""
    shown = {k: v for k, v in step.result.items() if k not in ("examined", "running")}
    if "running" in step.result:
        shown["running"] = {k: step.result["running"][k] for k in ("parasites", "wbcs", "status")}
    if "examined" in step.result:
        shown["examined"] = len(step.result["examined"])
    return {"tool": step.tool, "arguments": step.arguments, "result": shown}


def start_report(
    session: CaptureSession,
    pipeline: Pipeline,
    language: str,
    client: MetaModelClient | None,
    model: str,
    runner: Callable[[Callable[[], None]], None] | None = None,
) -> ReportJob:
    """Start the agent over the captured fields; without the API, report at once.

    ``runner`` runs the job (a new daemon thread by default; tests pass a direct call).
    """
    with session.lock:
        if session.job.state == "running":
            return session.job
        job = session.job = ReportJob(state="running")
        fields = list(session.fields)

    if client is None:
        count = evaluate_slide([c.result for _, c in fields], pipeline.protocol)
        report = render(count, language)
        job.result = {
            "language": language,
            "report": report.text,
            "narrative": None,
            "audit": None,
            "audit_text": None,
            "excluded": {},
            "slide": report.facts,
            "finished_by_agent": False,
            "notes": ["Muse Spark is not configured; deterministic report only"],
            "text": report.text,
        }
        job.state = "done"
        return job

    slide = SlideSession(
        pipeline,
        fields,
        reviewer=MuseReviewer(client, model),
        auditor=MuseAuditor(client, model),
    )
    agent = CountingAgent(client, model)

    def work() -> None:
        try:
            result = agent.run(slide, language, on_step=lambda s: job.steps.append(step_json(s)))
            job.result = result_json(result)
            job.state = "done"
        except Exception as exc:  # surfaced to the phone, never raised
            job.error = str(exc)
            job.state = "failed"

    if runner is None:
        threading.Thread(target=work, daemon=True).start()
    else:
        runner(work)
    return job
