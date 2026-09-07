"""
NETRAKSH — Events router.
GET  /events           — list events (paginated, filterable)
GET  /events/{id}      — get single event with evidence
GET  /events/{id}/evidence-image — decrypted evidence image for an authorized viewer
POST /events           — ingest event from edge sync (edge device auth)
POST /events/{id}/verify — run integrity verification
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import Camera, EvidencePackage, Event
from backend.security.auth import require_any_role
from backend.security.evidence_key_wrap import unwrap_key
from backend.services.verification import verify_event_integrity
from shared.crypto import aes_gcm_decrypt
from shared.schemas import (
    EventCreateRequest,
    EventResponse,
    VerificationResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=List[EventResponse])
async def list_events(
    camera_id: Optional[str] = Query(None),
    decision_state: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    q = db.query(Event)
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    if decision_state:
        q = q.filter(Event.decision_state == decision_state)
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if severity:
        q = q.filter(Event.severity == severity)
    events = q.order_by(desc(Event.timestamp)).offset(offset).limit(limit).all()
    return [_event_to_response(e, db) for e in events]


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_to_response(event, db)


@router.get("/{event_id}/evidence-image")
async def get_evidence_image(
    event_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Returns the decrypted evidence image for an event, for an authenticated,
    RBAC-gated viewer (architecture v4 §10). Requires require_any_role, same
    as get_event() and verify_event() above (auth was added to those two as
    part of the pre-deployment hardening pass — see docs/LIMITATIONS.md).

    IMPORTANT DEPLOYMENT CAVEAT (docs/LIMITATIONS.md): this reads the file
    directly from the local path stored in Event.evidence_clip_ref, which
    only works because the backend and edge device share a filesystem in
    this project's current single-machine deployment. Edge sync
    (edge/sync/sync_client.py) transmits only this path string today, not
    the evidence bytes themselves — a real distributed deployment, where
    the edge device and backend run on different machines, would need the
    edge to actually upload the bytes during sync. That is a separate,
    larger change, not implemented here.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if not event.evidence_clip_ref:
        raise HTTPException(status_code=404, detail="This event has no evidence clip")

    path = event.evidence_clip_ref
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=(
                "Evidence file not found on this server's filesystem. This endpoint only "
                "works when the backend and edge device share a filesystem (the current "
                "single-machine demo deployment) — see docs/LIMITATIONS.md."
            ),
        )

    with open(path, "rb") as f:
        raw = f.read()

    if path.endswith(".jpg.enc"):
        camera = db.query(Camera).filter(Camera.id == event.camera_id).first()
        if not camera or not camera.evidence_key_wrapped:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Camera {event.camera_id} has not registered its evidence-encryption key "
                    f"yet — PUT /cameras/{event.camera_id}/evidence-key (see "
                    f"scripts/upload_evidence_key.py)."
                ),
            )
        try:
            raw_key = unwrap_key(camera.evidence_key_wrapped)
            image_bytes = aes_gcm_decrypt(raw_key, raw)
        except Exception as exc:
            logger.error(f"Evidence decryption failed for event {event_id}: {exc}")
            raise HTTPException(
                status_code=500,
                detail="Evidence decryption failed — wrong key, or the file was tampered with.",
            )
    else:
        # Legacy plain JPEG predating the AES-256 encryption change (real
        # examples of this exist in edge/data/clips/ from before that change
        # — see docs/LIMITATIONS.md) — served as-is, not an error case.
        image_bytes = raw

    return Response(content=image_bytes, media_type="image/jpeg")


@router.post("", status_code=status.HTTP_201_CREATED)
async def ingest_event(
    payload: EventCreateRequest,
    db: Session = Depends(get_db),
    # MVP: Edge authentication disabled for local demo. 
    # In production, this validates mTLS or device token.
):
    """
    Called by edge sync client when connectivity is restored.
    Runs server-side verification before storing.
    """
    from backend.services.escalation import check_and_escalate

    ep = payload.evidence_package

    # Ensure camera exists (create stub if unknown, mark for review)
    camera = db.query(Camera).filter(Camera.id == ep.camera_id).first()
    if not camera:
        logger.warning(f"Event from unknown camera {ep.camera_id} — creating stub camera")
        camera = Camera(id=ep.camera_id, name=f"Unknown-{ep.camera_id[:8]}", location="unknown")
        db.add(camera)
        db.flush()

    # Create event record
    event = Event(
        id=ep.event_id,
        camera_id=ep.camera_id,
        zone_id=ep.zone_id,
        timestamp=ep.timestamp,
        event_type=str(ep.event_type) if ep.event_type else None,
        detection_class=str(ep.detection_class),
        confidence=ep.confidence,
        scene_condition=str(ep.scene_condition),
        camera_health_state=str(ep.camera_health_state),
        decision_state=str(ep.decision_state),
        decision_reason=ep.decision_reason,
        track_id=ep.track_id,
        severity=str(ep.severity) if ep.severity else None,
        direction=str(ep.direction) if ep.direction else None,
        rule=ep.rule,
        rule_value=ep.rule_value,
        plate_text=ep.plate_text,
        plate_confidence=ep.plate_confidence,
        vehicle_subtype=str(ep.vehicle_subtype) if ep.vehicle_subtype else None,
        face_match_person_id=ep.face_match_person_id,
        face_match_person_name=ep.face_match_person_name,
        face_match_confidence=ep.face_match_confidence,
        evidence_clip_ref=ep.evidence_clip_ref,
        edge_device_id=payload.edge_device_id,
        sequence_number=payload.sequence_number,
        synced_from_edge=True,
    )
    db.add(event)
    db.flush()

    # Store evidence package
    evidence = EvidencePackage(
        event_id=ep.event_id,
        sha256=ep.hash or "",
        digital_signature=ep.signature or "",
        previous_hash=ep.previous_hash,
        current_hash=ep.hash or "",
        raw_package_json=json.dumps(ep.model_dump(), default=str),
    )
    db.add(evidence)

    # Server-side verification
    camera_pubkey = camera.public_key_pem
    vr = verify_event_integrity(ep, camera_pubkey, db, payload.edge_device_id, payload.sequence_number)
    evidence.hash_valid = vr.hash_valid
    evidence.signature_valid = vr.signature_valid
    evidence.chain_valid = vr.chain_valid
    evidence.verified_ok = vr.hash_valid and vr.signature_valid and vr.chain_valid
    evidence.verified_at = datetime.utcnow()

    db.commit()
    logger.info(f"Event {ep.event_id} ingested. Verified: {evidence.verified_ok}")

    # Cross-camera corroboration (backend/services/cross_camera.py) — real,
    # computed now because it needs other cameras' already-committed events,
    # which only exist backend-side, never on the edge. Failure here must
    # never block ingest of the actual event; same non-fatal posture as
    # escalation/blockchain below.
    try:
        from backend.services.cross_camera import apply_corroboration
        apply_corroboration(event, db)
    except Exception as exc:
        logger.error(f"Cross-camera corroboration failed for event {ep.event_id} (non-fatal): {exc}")

    # Check escalation eligibility
    check_and_escalate(event, db)

    # Push to live dashboard
    from backend.api.websocket import broadcast_event
    import asyncio
    asyncio.create_task(broadcast_event(_event_to_response(event, db).model_dump(mode="json")))

    return {"event_id": ep.event_id, "verified": evidence.verified_ok}


@router.post("/{event_id}/verify", response_model=VerificationResponse)
async def verify_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """One-click 'verify integrity' from the dashboard."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    evidence = db.query(EvidencePackage).filter(EvidencePackage.event_id == event_id).first()
    if not evidence or not evidence.raw_package_json:
        raise HTTPException(status_code=404, detail="Evidence package not found")

    from shared.schemas import EvidencePackage as EPSchema

    camera = db.query(Camera).filter(Camera.id == event.camera_id).first()
    ep = EPSchema(**json.loads(evidence.raw_package_json))
    vr = verify_event_integrity(ep, camera.public_key_pem if camera else None, db, event.edge_device_id, event.sequence_number)

    # Update stored verification state
    evidence.hash_valid = vr.hash_valid
    evidence.signature_valid = vr.signature_valid
    evidence.chain_valid = vr.chain_valid
    evidence.verified_ok = vr.hash_valid and vr.signature_valid and vr.chain_valid
    evidence.verified_at = datetime.utcnow()
    db.commit()

    return vr


def _event_to_response(event: Event, db: Session) -> EventResponse:
    ep = db.query(EvidencePackage).filter(EvidencePackage.event_id == event.id).first()
    return EventResponse(
        event_id=event.id,
        camera_id=event.camera_id,
        timestamp=event.timestamp,
        event_type=event.event_type,
        detection_class=event.detection_class,
        confidence=event.confidence,
        scene_condition=event.scene_condition,
        camera_health_state=event.camera_health_state,
        decision_state=event.decision_state,
        decision_reason=event.decision_reason,
        zone_id=event.zone_id or "",
        track_id=event.track_id,
        severity=event.severity,
        hash=ep.sha256 if ep else None,
        signature=ep.digital_signature if ep else None,
        verified_ok=ep.verified_ok if ep else None,
        edge_device_id=event.edge_device_id,
        corroboration_score=event.corroboration_score,
        corroborated_by_event_id=event.corroborated_by_event_id,
        corroboration_distance_m=event.corroboration_distance_m,
        corroboration_delta_t_s=event.corroboration_delta_t_s,
        vehicle_subtype=event.vehicle_subtype,
        face_match_person_id=event.face_match_person_id,
        face_match_person_name=event.face_match_person_name,
        face_match_confidence=event.face_match_confidence,
    )
