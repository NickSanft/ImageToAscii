#!/usr/bin/env python3
"""
Web UI for the ASCII Art Generator.

Run with:
    python web_ui.py
Then open:
    http://127.0.0.1:8000
"""

import html as html_module
import io
import re
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from ascii_art import CHAR_SETS, image_to_ascii, remove_background, strip_ansi

app = FastAPI(title="Image to ASCII", docs_url=None, redoc_url=None)

# In-memory session store: session_id → {image, timestamp, filename, last_plain}
_sessions: dict[str, dict] = {}
MAX_SESSIONS = 10
UPLOAD_LIMIT = 10 * 1024 * 1024  # 10 MB


def _evict_oldest() -> None:
    """Drop the oldest session when the store is at capacity."""
    if len(_sessions) >= MAX_SESSIONS:
        oldest = min(_sessions, key=lambda k: _sessions[k]["timestamp"])
        del _sessions[oldest]


# ── ANSI → HTML ──────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"(\x1b\[[0-9;]*m)")


def ansi_to_html(text: str) -> str:
    """Convert ANSI 24-bit colour escapes to HTML <span> elements."""
    parts = _ANSI_RE.split(text)
    out: list[str] = []
    open_span = False
    for part in parts:
        if part.startswith("\x1b["):
            codes = part[2:-1]
            if codes in ("0", ""):
                if open_span:
                    out.append("</span>")
                    open_span = False
            elif codes.startswith("38;2;"):
                if open_span:
                    out.append("</span>")
                r, g, b = codes[5:].split(";")
                out.append(f'<span style="color:rgb({r},{g},{b})">')
                open_span = True
        else:
            out.append(html_module.escape(part))
    if open_span:
        out.append("</span>")
    return "".join(out)


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
        "timestamp": time.time(),
        "filename": image.filename or "ascii_art",
        "last_plain": "",
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
    chars: str = "standard"
    invert: bool = False
    color: bool = False
    contrast: bool = False
    sharpen: float = Field(1.0, ge=0.5, le=5.0)
    gamma: float = Field(1.0, ge=0.2, le=3.0)
    dither: bool = False
    isolate: bool = False


@app.post("/render")
def render(req: RenderRequest):
    session = _sessions.get(req.session_id)
    if session is None:
        raise HTTPException(404, "Session not found — please re-upload your image")
    if req.chars not in CHAR_SETS:
        raise HTTPException(400, f"Unknown char set: {req.chars!r}")

    img = session["image"].copy()
    if req.isolate:
        img = remove_background(img)

    ascii_text = image_to_ascii(
        img,
        width=req.width,
        char_set=req.chars,
        invert=req.invert,
        color=req.color,
        contrast=req.contrast,
        sharpen=req.sharpen,
        gamma=req.gamma,
        dither=req.dither,
    )

    plain = strip_ansi(ascii_text)
    session["last_plain"] = plain
    session["timestamp"] = time.time()

    output_html = ansi_to_html(ascii_text) if req.color else html_module.escape(plain)
    return {"html": output_html}


@app.get("/download")
def download(session_id: str):
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    stem = Path(session["filename"]).stem
    return Response(
        content=session["last_plain"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.txt"'},
    )


if __name__ == "__main__":
    uvicorn.run("web_ui:app", host="127.0.0.1", port=8000, reload=True)
