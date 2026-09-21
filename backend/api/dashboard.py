"""
NETRAKSH — Dashboard Video API.

Provides authenticated video upload and preview for the Command Center dashboard.
Mounted unconditionally in all environments (not dev-only) because SIH
presentation video functionality is required regardless of ENV mode.

Only exposes the minimum surface needed for the dashboard video workflow:
  POST /api/dashboard/video/upload   — upload presentation video (OPERATOR+)
  GET  /api/dashboard/video/current  — structured current-video state

Scenario-switching and other demo-control endpoints remain restricted to
development via the demo router in main.py.

Static file serving for /demo/videos/* is handled by the unconditional
StaticFiles mount in main.py — this router does NOT duplicate it.

Security:
  - All endpoints require OPERATOR or ADMIN role (via require_operator_or_admin)
  - File extension AND MIME type validated before saving
  - Server-controlled filenames — no user-supplied paths
  - No public or unauthenticated access
  - ffmpeg availability checked at runtime; clear actionable error when absent
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from backend.security.auth import require_operator_or_admin

# Import the shared in-memory state from the demo module.  This is a plain
# module-level dict — the same object across all imports — so writing here
# is immediately visible to the edge runner's /demo/scenario poll (every 5s).
# The import is unconditional because demo.py is always importable (Python
# module loading is independent of whether the router is mounted in main.py).
try:
    from backend.api.demo import _state as _demo_state
except ImportError:
    # Fallback in case demo module is structurally unavailable
    import uuid as _uuid
    _demo_state: dict = {
        "scenario": "paused",
        "video_source": None,
        "video_preview": None,
        "video_session_id": None,
    }


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
    ".flv", ".wmv", ".mpeg", ".mpg", ".m4v",
    ".3gp", ".ogv", ".ts", ".mts", ".m2ts",
})

_ALLOWED_MIME_PREFIX = "video/"

# Relative to repo root (where uvicorn is launched)
_VIDEOS_SUBDIR = Path("demo") / "videos"


def _videos_dir() -> Path:
    """Resolved absolute path to demo/videos/, always relative to CWD."""
    return Path(os.getcwd()) / _VIDEOS_SUBDIR


def _ffmpeg_bin() -> str | None:
    """Return ffmpeg binary path if available on PATH, else None."""
    return shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
# GET /api/dashboard/video/current
# ---------------------------------------------------------------------------

@router.get("/video/current")
async def get_current_video(_user=Depends(require_operator_or_admin)):
    """
    Return the structured state of the currently active dashboard video.

    The frontend should call this on mount to discover any pre-existing video
    from a previous session, instead of guessing filenames.

    Returns one of:
      { "available": false }
      { "available": false, "error": "no_browser_preview", "hint": "...", "source_name": "..." }
      {
        "available": true,
        "preview_url": "/api/dashboard/video/current/media",
        "source_name": "uploaded_demo_preview.mp4",
        "session_id": "<uuid>",
        "processing_status": "active"
      }
    """
    source: str | None = _demo_state.get("video_source")
    session_id: str | None = _demo_state.get("video_session_id")

    if not source:
        return {"available": False}

    vdir = _videos_dir()
    source_path = Path(source)
    abs_source = (
        Path(os.getcwd()) / source_path
        if not source_path.is_absolute()
        else source_path
    )

    # Priority 1: explicit ffmpeg-converted preview for this upload session.
    # Older sessions used one global preview filename, so retain that path only
    # for the legacy global source.
    preview_source = _demo_state.get("video_preview")
    if preview_source:
        preview_ref = Path(preview_source)
        preview_path = (
            Path(os.getcwd()) / preview_ref
            if not preview_ref.is_absolute()
            else preview_ref
        )
    elif source_path.name.startswith("uploaded_demo"):
        preview_path = vdir / "uploaded_demo_preview.mp4"
    else:
        preview_path = None
    if preview_path and preview_path.exists() and preview_path.stat().st_size > 0:
        return {
            "available": True,
            "preview_url": "/api/dashboard/video/current/media",
            "source_name": preview_path.name,
            "session_id": session_id,
            "processing_status": "active",
        }

    # Priority 2: original file is already MP4
    if abs_source.exists() and abs_source.suffix.lower() == ".mp4":
        return {
            "available": True,
            "preview_url": "/api/dashboard/video/current/media",
            "source_name": abs_source.name,
            "session_id": session_id,
            "processing_status": "active",
        }

    # Non-MP4 file with no preview available
    if abs_source.exists():
        return {
            "available": False,
            "error": "no_browser_preview",
            "source_name": abs_source.name,
            "hint": (
                "ffmpeg is not installed — upload an MP4 file for in-browser playback. "
                "The file is still queued for edge processing."
            ),
        }

    return {"available": False}


# ---------------------------------------------------------------------------
# GET /api/dashboard/video/internal-sync
# ---------------------------------------------------------------------------

@router.get("/video/internal-sync")
async def get_internal_sync():
    """
    Unauthenticated endpoint for the local edge runner to poll the current video
    source and session ID. This replaces the need for the edge runner to poll
    the development-only /demo/scenario endpoint.
    """
    return {
        "video_source": _demo_state.get("video_source"),
        "video_session_id": _demo_state.get("video_session_id"),
        "scenario": _demo_state.get("scenario", "normal"),
        "video_time": _demo_state.get("video_time", 0.0),
        "video_time_updated_at": _demo_state.get("video_time_updated_at", 0.0)
    }


@router.post("/video/scenario")
async def post_video_scenario(
    payload: dict,
    _user=Depends(require_operator_or_admin)
):
    """
    Authenticated endpoint for the frontend to control the demo scenario
    (e.g., play/pause) and update the session ID or video time.
    """
    requested = payload.get("scenario")
    if requested in {"normal", "fog", "failure", "offline", "paused"}:
        _demo_state["scenario"] = requested
    if "video_session_id" in payload:
        _demo_state["video_session_id"] = payload["video_session_id"]
    if "video_time" in payload:
        _demo_state["video_time"] = float(payload["video_time"])
        import time
        _demo_state["video_time_updated_at"] = time.time()
    return {"status": "success", "state": _demo_state}


# ---------------------------------------------------------------------------
# GET /api/dashboard/video/current/media
# ---------------------------------------------------------------------------

@router.get("/video/current/media")
async def get_current_video_media(_user=Depends(require_operator_or_admin)):
    """
    Securely serve the current dashboard video media using an authenticated endpoint.
    """
    source: str | None = _demo_state.get("video_source")
    if not source:
        raise HTTPException(status_code=404, detail="No video available")

    vdir = _videos_dir()
    source_path = Path(source)
    abs_source = (
        Path(os.getcwd()) / source_path
        if not source_path.is_absolute()
        else source_path
    )

    # Priority 1: explicit ffmpeg-converted preview for this upload session.
    preview_source = _demo_state.get("video_preview")
    if preview_source:
        preview_ref = Path(preview_source)
        preview_path = (
            Path(os.getcwd()) / preview_ref
            if not preview_ref.is_absolute()
            else preview_ref
        )
    elif source_path.name.startswith("uploaded_demo"):
        preview_path = vdir / "uploaded_demo_preview.mp4"
    else:
        preview_path = None
    if preview_path and preview_path.exists() and preview_path.stat().st_size > 0:
        return FileResponse(preview_path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

    # Priority 2: original file is already MP4
    if abs_source.exists() and abs_source.suffix.lower() == ".mp4":
        return FileResponse(abs_source, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

    raise HTTPException(status_code=404, detail="Media file not found")



# ---------------------------------------------------------------------------
# POST /api/dashboard/video/upload
# ---------------------------------------------------------------------------

@router.post("/video/upload", status_code=status.HTTP_200_OK)
async def upload_dashboard_video(
    file: UploadFile = File(...),
    _user=Depends(require_operator_or_admin),
):
    """
    Upload a presentation video for the dashboard and edge pipeline.
    Requires OPERATOR or ADMIN role.

    ffmpeg behaviour:
      - If ffmpeg is installed: converts to H.264/AAC MP4 (yuv420p, faststart).
      - If ffmpeg is absent AND file is MP4: serves it directly.
      - If ffmpeg is absent AND file is non-MP4: saves for edge processing but
        returns ok_no_preview with a clear actionable message; browser cannot play.

    Returns:
      {
        "status": "ok" | "ok_no_preview",
        "preview_url": "/demo/videos/..." | null,
        "session_id": "<uuid>",
        "source_name": "<filename>",
        "ffmpeg_available": true | false,
        "message": "<human-readable status>"
      }
    """
    # --- Validate MIME type ---
    content_type = (file.content_type or "").lower()
    if not content_type.startswith(_ALLOWED_MIME_PREFIX):
        raise HTTPException(
            status_code=400,
            detail=f"Only video files are accepted (received Content-Type: {content_type or 'unknown'})",
        )

    # --- Validate extension ---
    original_name = file.filename or "upload"
    ext = Path(original_name).suffix.lower()
    if not ext:
        ext = ".mp4"
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported video extension '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )

    # --- Ensure target directory ---
    vdir = _videos_dir()
    vdir.mkdir(parents=True, exist_ok=True)

    # A worker can still have the previous source open while a new upload
    # arrives.  Reusing one fixed filename is therefore a Windows sharing
    # violation race.  Give every session its own server-controlled paths so
    # the active reader and the next writer never contend for the same file.
    new_session_id = str(uuid.uuid4())
    target_name = f"uploaded_{new_session_id}{ext}"
    target_path = vdir / target_name
    try:
        with open(target_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
    except OSError as exc:
        logger.error(f"[Dashboard] Failed to save uploaded video: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to save video file: {exc}")

    logger.info(f"[Dashboard] Video saved: {target_path} ({target_path.stat().st_size} bytes)")

    # --- Attempt ffmpeg conversion to browser-compatible H.264 MP4 ---
    ffmpeg = _ffmpeg_bin()
    preview_name = f"uploaded_{new_session_id}_preview.mp4"
    preview_path = vdir / preview_name
    preview_url: str | None = None

    if ffmpeg:
        try:
            result = subprocess.run(
                [
                    ffmpeg, "-y",
                    "-i", str(target_path),
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    str(preview_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode == 0 and preview_path.exists() and preview_path.stat().st_size > 0:
                preview_url = "/api/dashboard/video/current/media"
                logger.info(f"[Dashboard] ffmpeg preview created: {preview_path}")
            else:
                logger.warning(
                    f"[Dashboard] ffmpeg exited {result.returncode}. "
                    f"stderr: {result.stderr[-400:]}"
                )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(f"[Dashboard] ffmpeg conversion failed: {exc}")
    # If no ffmpeg conversion but original is already MP4, serve directly
    if not preview_url and ext == ".mp4":
        preview_url = "/api/dashboard/video/current/media"
        logger.info("[Dashboard] Serving original MP4 directly (ffmpeg not installed)")

    # Do NOT update shared demo state here so edge runner does not start immediately.
    # The frontend will call /analyze to trigger playback.
    
    if preview_url:
        return {
            "status": "ok",
            "preview_url": preview_url,
            "session_id": new_session_id,
            "source_name": target_path.name,
            "ffmpeg_available": bool(ffmpeg),
            "message": (
                "Video accepted. Edge processor will pick up the new source "
                "within 5 seconds and begin generating telemetry."
            ),
        }

    # Non-MP4 without ffmpeg — saved for edge, but no browser preview
    return {
        "status": "ok_no_preview",
        "preview_url": None,
        "session_id": new_session_id,
        "source_name": target_path.name,
        "ffmpeg_available": False,
        "message": (
            f"Video saved for edge processing, but cannot be previewed in the browser "
            f"(ffmpeg is not installed and '{ext}' requires transcoding for Chromium). "
            "Upload an MP4 file for in-browser video playback."
        ),
    }

# ---------------------------------------------------------------------------
# POST /api/dashboard/video/analyze
# ---------------------------------------------------------------------------
from pydantic import BaseModel

class AnalyzeRequest(BaseModel):
    session_id: str
    source_name: str
    preview_name: str | None = None

@router.post("/video/analyze", status_code=status.HTTP_200_OK)
async def analyze_dashboard_video(
    req: AnalyzeRequest,
    _user=Depends(require_operator_or_admin),
):
    """
    Trigger the Edge processor to begin analysis of an uploaded video.
    This separates upload (buffering/transcoding) from actual playback/analysis,
    allowing the frontend to stay paused until the user hits Play.
    """
    target_name = req.source_name
    preview_name = req.preview_name

    vdir = _videos_dir()
    target_path = vdir / target_name
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found. Please upload again.")

    _demo_state["video_source"] = str(Path("demo") / "videos" / target_name)
    _demo_state["video_preview"] = (
        str(Path("demo") / "videos" / preview_name)
        if preview_name and (vdir / preview_name).exists()
        else None
    )
    _demo_state["video_session_id"] = req.session_id

    logger.info(
        f"[Dashboard] Analysis triggered: source={_demo_state['video_source']} "
        f"session={req.session_id}"
    )

    return {"status": "ok", "message": "Analysis started"}
