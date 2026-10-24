"""FastAPI service: upload field images, get detections, counts and a report."""

from __future__ import annotations

import io
from typing import Annotated, Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from PIL import Image, UnidentifiedImageError

from darubini import __version__
from darubini.config import get_settings
from darubini.pipeline import Pipeline
from darubini.segmentation.base import get_segmenter

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FIELDS = 200

app = FastAPI(
    title="Darubini",
    version=__version__,
    description="Malaria thick-smear counting copilot. Decision support only.",
)


def _pipeline() -> Pipeline:
    return Pipeline(segmenter=get_segmenter(get_settings()))


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
