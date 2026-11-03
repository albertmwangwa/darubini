"""FastAPI service: the phone capture app, plus a batch analysis endpoint.

The phone app (``GET /``) captures fields one at a time through ``/v1/sessions``;
``POST /v1/analyse`` analyses a whole slide's images in one request.
"""

from __future__ import annotations

import io
from functools import lru_cache
from importlib import resources
from typing import Annotated, Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image, UnidentifiedImageError

from darubini import __version__
from darubini.api.sessions import (
    CaptureSession,
    SessionStore,
    add_clip,
    add_field,
    add_voice,
    running_facts,
    start_report,
)
from darubini.config import get_settings
from darubini.meta.client import MetaApiError, MetaModelClient
from darubini.pipeline import Pipeline
from darubini.segmentation.base import get_segmenter
from darubini.tracking import SamTracker, ShiftTracker, Tracker

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 60 * 1024 * 1024
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_FIELDS = 200
#: Clips are sampled down to this many frames before tracking.
MAX_CLIP_FRAMES = 60
CLIP_SIDE = 1280

store = SessionStore()

app = FastAPI(
    title="Darubini",
    version=__version__,
    description="Malaria thick-smear counting copilot. Decision support only.",
)


def _pipeline() -> Pipeline:
    return Pipeline(segmenter=get_segmenter(get_settings()))


@lru_cache(maxsize=1)
def _shared_pipeline() -> Pipeline:
    """One pipeline for capture sessions, so the verifier loads once."""
    return _pipeline()


def _client() -> MetaModelClient | None:
    s = get_settings()
    return MetaModelClient.from_settings(s) if s.meta_enabled else None


def _tracker() -> Tracker:
    s = get_settings()
    client = _client()
    if client is None:
        return ShiftTracker()
    return SamTracker(client, s.meta_segmentation_model)


def _session(session_id: str) -> CaptureSession:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown or expired session") from exc


async def _read_image(upload: UploadFile) -> np.ndarray[Any, np.dtype[np.uint8]]:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"{upload.filename}: file too large")
    try:
        with Image.open(io.BytesIO(data)) as img:
            return np.asarray(img.convert("RGB"), dtype=np.uint8)
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=415, detail=f"{upload.filename}: not an image") from exc


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    s = get_settings()
    return {"status": "ok", "version": __version__, "segmenter": s.segmenter}


@app.post("/v1/analyse")
async def analyse(
    files: Annotated[list[UploadFile], File(description="One image per microscope field")],
    language: Annotated[str, Query(pattern="^(en|sw)$")] = "en",
) -> dict[str, Any]:
    """Analyse the fields of one slide, in capture order."""
    if not files:
        raise HTTPException(status_code=422, detail="upload at least one field image")
    if len(files) > MAX_FIELDS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_FIELDS} fields per request")
    images = [(f.filename or f"field-{i}", await _read_image(f)) for i, f in enumerate(files)]
    fields, _count, report = _pipeline().analyse_slide(images, language=language)
    return {
        "fields": [
            {
                "field_id": f.field_id,
                "usable": f.usable,
                "quality_flags": f.quality_flags,
                "parasites": f.parasites,
                "wbcs": f.wbcs,
                "detections": [
                    {
                        "class": d.cls.value,
                        "box": [d.box.x_min, d.box.y_min, d.box.x_max, d.box.y_max],
                        "score": d.score,
                        "source": d.source,
                    }
                    for d in f.detections
                ],
            }
            for f in fields
        ],
        "slide": report.facts,
        "report": report.text,
    }


# ---- phone capture app ----


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def phone_app() -> str:
    """Serve the phone capture app, a single static page."""
    return resources.files("darubini.api").joinpath("static/index.html").read_text("utf-8")


@app.post("/v1/sessions")
def create_session() -> dict[str, Any]:
    """Start capturing a new slide."""
    session = store.create()
    pipeline = _shared_pipeline()
    return {
        "session_id": session.session_id,
        "running": running_facts(session.count(pipeline), pipeline),
        "agent": get_settings().meta_enabled,
    }


@app.get("/v1/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    """Return the running count of a session."""
    session = _session(session_id)
    pipeline = _shared_pipeline()
    return {
        "session_id": session.session_id,
        "fields": [fid for fid, _ in session.fields],
        "running": running_facts(session.count(pipeline), pipeline),
    }


@app.post("/v1/sessions/{session_id}/fields")
async def capture_field(
    session_id: str, file: Annotated[UploadFile, File(description="One field photo")]
) -> dict[str, Any]:
    """Analyse one field photo and say what to do next."""
    session = _session(session_id)
    image = await _read_image(file)
    try:
        return add_field(session, _shared_pipeline(), image, MAX_FIELDS)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=502, detail=f"segmentation failed: {exc}") from exc


@app.post("/v1/sessions/{session_id}/clips")
async def capture_clip(
    session_id: str, file: Annotated[UploadFile, File(description="A short panning clip")]
) -> dict[str, Any]:
    """Count a panned clip, each parasite and WBC once (SAM 3.1 tracking when configured)."""
    from darubini import video

    session = _session(session_id)
    data = await file.read(MAX_VIDEO_BYTES + 1)
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail=f"{file.filename}: clip too large")
    try:
        frames = video.decode(data, max_frames=MAX_CLIP_FRAMES, max_side=CLIP_SIDE)
    except Exception as exc:  # any decoder failure means the upload is not a usable video
        raise HTTPException(status_code=415, detail=f"{file.filename}: not a video") from exc
    try:
        return add_clip(session, _shared_pipeline(), frames, _tracker(), MAX_FIELDS)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetaApiError as exc:
        raise HTTPException(status_code=502, detail=f"tracking failed: {exc}") from exc


@app.post("/v1/sessions/{session_id}/voice")
async def voice_command(
    session_id: str, file: Annotated[UploadFile, File(description="A push-to-talk recording")]
) -> dict[str, Any]:
    """Transcribe a spoken command with Muse Voice Transcribe and say what it asks for."""
    from darubini.voice import KEYWORDS, parse_command, to_wav

    session = _session(session_id)
    client = _client()
    if client is None:
        raise HTTPException(status_code=503, detail="voice needs the Meta Model API")
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail=f"{file.filename}: recording too large")
    try:
        wav = to_wav(data)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=f"{file.filename}: {exc}") from exc
    try:
        transcript = client.transcribe(wav, get_settings().meta_voice_model, keywords=KEYWORDS)
    except MetaApiError as exc:
        raise HTTPException(status_code=502, detail=f"transcription failed: {exc}") from exc
    return add_voice(session, parse_command(transcript))


@app.post("/v1/sessions/{session_id}/report")
def start_session_report(
    session_id: str, language: Annotated[str, Query(pattern="^(en|sw)$")] = "en"
) -> dict[str, Any]:
    """Finish the slide: the Muse Spark agent reviews, audits and reports (poll GET)."""
    session = _session(session_id)
    job = start_report(
        session, _shared_pipeline(), language, _client(), get_settings().meta_reasoning_model
    )
    return {"state": job.state, "steps": job.steps, "result": job.result, "error": job.error}


@app.get("/v1/sessions/{session_id}/report")
def get_session_report(session_id: str) -> dict[str, Any]:
    """Progress of the report: the agent's tool calls so far, then the result."""
    job = _session(session_id).job
    return {"state": job.state, "steps": job.steps, "result": job.result, "error": job.error}
