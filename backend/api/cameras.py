"""
NETRAKSH — Cameras router.
GET  /cameras          — list all cameras with latest health
GET  /cameras/{id}     — get camera detail + health history
POST /cameras          — register camera (ADMIN)
POST /cameras/{id}/health       — periodic real health telemetry from the edge
PUT  /cameras/{id}/public-key   — upload edge device public key (ADMIN)
PUT  /cameras/{id}/evidence-key — upload edge device evidence-encryption key (ADMIN)
PUT  /cameras/{id}/location     — set real lat/lon for the geospatial map (ADMIN)
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import Camera, CameraHealth
from backend.security.auth import require_admin, require_any_role
from backend.security.evidence_key_wrap import wrap_key
from shared.schemas import CameraHealthReport, CameraLocationUpdate, CameraStatusResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=List[CameraStatusResponse])
async def list_cameras(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    cameras = db.query(Camera).filter(Camera.is_active == True).all()
    return [_camera_to_response(cam, db) for cam in cameras]


@router.get("/{camera_id}", response_model=CameraStatusResponse)
async def get_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return _camera_to_response(cam, db)


@router.post("/{camera_id}/health", status_code=status.HTTP_201_CREATED)
async def report_camera_health(
    camera_id: str,
    payload: CameraHealthReport,
    db: Session = Depends(get_db),
    # MVP: edge authentication disabled for local demo, same posture as
    # POST /events (backend/api/events.py) — see docs/LIMITATIONS.md.
):
    """
    Periodic real health telemetry push from the edge (edge/main.py's
    EdgePipeline._report_camera_health, roughly every 5s), independent of
    any detection event.

    Before this endpoint existed, CameraHealthMonitor
    (edge/health/camera_health.py) computed real health every frame but
    nothing ever persisted it — the CameraHealth table was never written to
    by any code path, so GET /cameras always returned health_state=UNKNOWN
    for every real camera and the frontend's Camera Health Matrix page ran
    entirely on mock data. This is what actually connects the two.
    """
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        logger.warning(f"Health report from unknown camera {camera_id} — creating stub camera")
        camera = Camera(id=camera_id, name=f"Unknown-{camera_id[:8]}", location="unknown")
        db.add(camera)
        db.flush()

    record = CameraHealth(
        camera_id=camera_id,
        health_state=str(payload.health_state),
        health_reason=str(payload.health_reason),
        timestamp=payload.health_timestamp,
        fps_actual=payload.fps_actual,
        fps_declared=payload.fps_declared,
        drift_seconds=payload.drift_seconds,
        blur_score=payload.blur_score,
        exposure_clip_fraction=payload.exposure_clip_fraction,
        frame_variance=payload.frame_variance,
    )
    db.add(record)
    db.commit()

    from backend.api.websocket import broadcast_camera_health
    asyncio.create_task(broadcast_camera_health({
        "camera_id": camera_id,
        "status": record.health_state,
        "health_reason": record.health_reason,
        "fps": record.fps_actual,
        "blur_score": record.blur_score,
        "exposure_clip_fraction": record.exposure_clip_fraction,
        "drift_seconds": record.drift_seconds,
    }))

    return {"camera_id": camera_id, "health_state": record.health_state}


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_camera(
    payload: dict,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    cam = Camera(
        name=payload.get("name", "Unnamed"),
        location=payload.get("location", "Unknown"),
        rtsp_url=payload.get("rtsp_url"),
        owning_command_id=payload.get("owning_command_id", "COMMAND_A"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
    )
    db.add(cam)
    db.commit()
    return {"camera_id": cam.id, "name": cam.name}


@router.put("/{camera_id}/public-key", status_code=status.HTTP_200_OK)
async def upload_public_key(
    camera_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    """Upload the Ed25519 public key PEM for a registered edge device."""
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam.public_key_pem = payload.get("public_key_pem", "")
    db.commit()
    return {"status": "ok", "camera_id": camera_id}


@router.put("/{camera_id}/evidence-key", status_code=status.HTTP_200_OK)
async def upload_evidence_key(
    camera_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    """
    Upload the edge device's raw AES-256 evidence-encryption key (base64;
    see edge/evidence/packager.py::EvidenceEncryptor.get_raw_key_b64(), and
    scripts/upload_evidence_key.py for a ready-made client for this call).

    The raw key is wrapped with a server-derived key before being stored
    (backend/security/evidence_key_wrap.py) — it is never persisted in the
    clear. Call this once per camera, over a trusted channel: in any
    non-local deployment this endpoint MUST be served over TLS, since the
    request body carries the raw key in transit — see docs/LIMITATIONS.md.

    Architecture v4 §10: this is what lets an authorized dashboard viewer
    decrypt this camera's evidence via GET /events/{event_id}/evidence-image.
    Before this is called for a camera, its evidence stays encrypted at rest
    (as it always has) but simply cannot be decrypted for viewing yet.
    """
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    raw_key_b64 = payload.get("evidence_key_b64", "")
    try:
        raw_key = base64.b64decode(raw_key_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="evidence_key_b64 is not valid base64")
    if len(raw_key) != 32:
        raise HTTPException(
            status_code=400,
            detail=f"Evidence key must be exactly 32 bytes (AES-256); got {len(raw_key)}",
        )

    cam.evidence_key_wrapped = wrap_key(raw_key)
    db.commit()
    logger.info(f"[Cameras] Evidence-encryption key registered for camera {camera_id}")
    return {"status": "ok", "camera_id": camera_id}


@router.put("/{camera_id}/location", status_code=status.HTTP_200_OK)
async def update_camera_location(
    camera_id: str,
    payload: CameraLocationUpdate,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    """
    Set a camera's real latitude/longitude — what the Alerts page's
    geospatial map actually plots. Before this endpoint existed, no camera
    anywhere had real coordinates and that map was pure decoration (a
    static illustrative image with hardcoded pin positions).
    """
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam.latitude = payload.latitude
    cam.longitude = payload.longitude
    db.commit()
    return {"status": "ok", "camera_id": camera_id, "latitude": cam.latitude, "longitude": cam.longitude}


def _camera_to_response(cam: Camera, db: Session) -> CameraStatusResponse:
    latest_health = (
        db.query(CameraHealth)
        .filter(CameraHealth.camera_id == cam.id)
        .order_by(desc(CameraHealth.timestamp))
        .first()
    )
    return CameraStatusResponse(
        camera_id=cam.id,
        name=cam.name,
        location=cam.location,
        health_state=latest_health.health_state if latest_health else None,
        health_reason=latest_health.health_reason if latest_health else None,
        last_health_check=latest_health.timestamp if latest_health else None,
        fps_declared=latest_health.fps_declared if latest_health else None,
        blur_score=latest_health.blur_score if latest_health else None,
        exposure_clip_fraction=latest_health.exposure_clip_fraction if latest_health else None,
        fps_actual=latest_health.fps_actual if latest_health else None,
        drift_seconds=latest_health.drift_seconds if latest_health else None,
        latitude=cam.latitude,
        longitude=cam.longitude,
    )
