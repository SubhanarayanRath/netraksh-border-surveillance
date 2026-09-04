"""
NETRAKSH — Cameras router.
GET /cameras          — list all cameras with latest health
GET /cameras/{id}     — get camera detail + health history
POST /cameras         — register camera (ADMIN)
PUT /cameras/{id}/public-key    — upload edge device public key (ADMIN)
PUT /cameras/{id}/evidence-key  — upload edge device evidence-encryption key (ADMIN)
"""
from __future__ import annotations

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
from shared.schemas import CameraStatusResponse

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
        health_state=latest_health.health_state if latest_health else "UNKNOWN",
        health_reason=latest_health.health_reason if latest_health else None,
        last_health_check=latest_health.timestamp if latest_health else None,
        fps_actual=latest_health.fps_actual if latest_health else None,
        drift_seconds=latest_health.drift_seconds if latest_health else None,
    )
