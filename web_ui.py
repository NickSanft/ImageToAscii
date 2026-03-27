#!/usr/bin/env python3
"""
Web UI for the ASCII Art Generator.

Run with:
    python web_ui.py
Then open:
    http://127.0.0.1:8000
"""

import asyncio
import io
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from ascii_art import (
    CHAR_SETS,
    ansi_to_html,
    ascii_to_html_document,
    image_to_ascii,
    remove_background,
    strip_ansi,
)

app = FastAPI(title="Image to ASCII", docs_url=None, redoc_url=None)

# In-memory session store:
#   session_id → {image, isolated_image, timestamp, filename, last_plain, last_html_doc}
_sessions: dict[str, dict] = {}
MAX_SESSIONS = 10
UPLOAD_LIMIT = 10 * 1024 * 1024  # 10 MB


def _evict_oldest() -> None:
    """Drop the oldest session when the store is at capacity."""
    if len(_sessions) >= MAX_SESSIONS:
        oldest = min(_sessions, key=lambda k: _sessions[k]["timestamp"])
        del _sessions[oldest]


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("templates/index.html")


@app.post("/upload")
async def upload(image: UploadFile = File(...)):
    contents = await image.read()
    if len(contents) > UPLOAD_LIMIT:
        raise HTTPException(413, "File too large (max 10 MB)")
    try:
        img = Image.open(io.BytesIO(contents))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"Invalid image: {exc}")

    _evict_oldest()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "image": img,
        "isolated_image": None,   # cached after first --isolate render
        "timestamp": time.time(),
        "filename": image.filename or "ascii_art",
        "last_plain": "",
        "last_html_doc": "",
    }
    return {
        "session_id": session_id,
        "filename": image.filename,
        "width": img.width,
        "height": img.height,
    }


class RenderRequest(BaseModel):
    session_id: str
    width: int = Field(80, ge=20, le=200)
    chars: str = "standard"          # preset name OR custom char string
    invert: bool = False
    color: bool = False
    contrast: bool = False
    sharpen: float = Field(1.0, ge=0.5, le=5.0)
    gamma: float = Field(1.0, ge=0.2, le=3.0)
    dither: bool = False
    isolate: bool = False
    edge_strength: float = Field(0.0, ge=0.0, le=0.5)
    aspect: float = Field(0.45, ge=0.35, le=0.65)


@app.post("/render")
async def render(req: RenderRequest):
    session = _sessions.get(req.session_id)
    if session is None:
        raise HTTPException(404, "Session not found — please re-upload your image")
    if req.chars not in CHAR_SETS and len(req.chars) < 2:
        raise HTTPException(400, f"Invalid char set: {req.chars!r}")

    def _do_render() -> str:
        # Use cached isolated image if available, otherwise compute once and cache
        if req.isolate:
            if session["isolated_image"] is None:
                session["isolated_image"] = remove_background(session["image"].copy())
            img = session["isolated_image"].copy()
        else:
            img = session["image"].copy()

        return image_to_ascii(
            img,
            width=req.width,
            char_set=req.chars,
            invert=req.invert,
            color=req.color,
            contrast=req.contrast,
            sharpen=req.sharpen,
            gamma=req.gamma,
            dither=req.dither,
            edge_strength=req.edge_strength,
            aspect=req.aspect,
        )

    # Run CPU-bound render in a thread so the event loop stays responsive
    ascii_text = await asyncio.to_thread(_do_render)

    plain = strip_ansi(ascii_text)
    session["last_plain"] = plain
    session["last_html_doc"] = ascii_to_html_document(ascii_text)
    session["timestamp"] = time.time()

    output_html = ansi_to_html(ascii_text) if req.color else __import__("html").escape(plain)
    return {"html": output_html}


@app.get("/download")
def download(session_id: str, format: str = "txt"):
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    stem = Path(session["filename"]).stem

    if format == "html":
        return Response(
            content=session["last_html_doc"],
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.html"'},
        )
    return Response(
        content=session["last_plain"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'},
    )


if __name__ == "__main__":
    uvicorn.run("web_ui:app", host="127.0.0.1", port=8000, reload=True)
