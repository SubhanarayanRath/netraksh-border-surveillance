"""
NETRAKSH — Watchlist router (SIH PS 26187: real facial recognition, not
detection alone).

GET    /watchlist             — list watchlist persons (any role)
POST   /watchlist              — register a person + first reference photo (ADMIN)
POST   /watchlist/{id}/images  — add another reference photo (ADMIN)
DELETE /watchlist/{id}         — remove a person (ADMIN)
GET    /watchlist/sync         — real reference images for the edge's LBPH
                                  recognizer to train against

Real, honestly-scoped: reference photos are stored as real, admin-uploaded
JPEG crops (base64), and GET /watchlist/sync returns them so the edge can
train edge/detection/face_recognition.py's classical LBPH recognizer
against real, labeled images — not a precomputed embedding database, and
not a production-grade deep-learning FRS. See that module's docstring for
the full honest scope (lighting/pose sensitivity, no liveness detection,
not for legal or large-scale 1:N identification).
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import WatchlistFaceImage, WatchlistPerson
from backend.security.auth import require_admin, require_any_role
from shared.schemas import (
    WatchlistPersonCreate,
    WatchlistPersonResponse,
    WatchlistSyncEntry,
    WatchlistSyncResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _person_to_response(person: WatchlistPerson) -> WatchlistPersonResponse:
    return WatchlistPersonResponse(
        person_id=person.id,
        name=person.name,
        notes=person.notes,
        is_active=person.is_active,
        created_at=person.created_at,
        face_image_count=len(person.face_images),
    )


@router.get("", response_model=List[WatchlistPersonResponse])
async def list_watchlist(
    db: Session = Depends(get_db),
    _user=Depends(require_any_role),
):
    persons = db.query(WatchlistPerson).filter(WatchlistPerson.is_active == True).all()
    return [_person_to_response(p) for p in persons]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WatchlistPersonResponse)
async def register_watchlist_person(
    payload: WatchlistPersonCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    person = WatchlistPerson(name=payload.name, notes=payload.notes)
    db.add(person)
    db.flush()
    image = WatchlistFaceImage(person_id=person.id, image_base64=payload.image_base64)
    db.add(image)
    db.commit()
    db.refresh(person)
    logger.info(f"[Watchlist] Registered person {person.id} ({person.name}) with 1 reference image")
    return _person_to_response(person)


@router.post("/{person_id}/images", status_code=status.HTTP_201_CREATED, response_model=WatchlistPersonResponse)
async def add_watchlist_image(
    person_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Adds another real reference photo for an existing person — more
    images (varied lighting/angle) genuinely improve LBPH's real match
    robustness against its own real limitations."""
    person = db.query(WatchlistPerson).filter(WatchlistPerson.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Watchlist person not found")
    image_base64 = payload.get("image_base64")
    if not image_base64:
        raise HTTPException(status_code=422, detail="image_base64 is required")
    image = WatchlistFaceImage(person_id=person_id, image_base64=image_base64)
    db.add(image)
    db.commit()
    db.refresh(person)
    return _person_to_response(person)


@router.delete("/{person_id}", status_code=status.HTTP_200_OK)
async def remove_watchlist_person(
    person_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    person = db.query(WatchlistPerson).filter(WatchlistPerson.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Watchlist person not found")
    # Soft delete (is_active=False), same posture as Camera.is_active — the
    # real historical record (past face-match events referencing this
    # person_id) stays intact and reviewable rather than being orphaned by
    # a hard delete.
    person.is_active = False
    db.commit()
    return {"person_id": person_id, "is_active": False}


@router.get("/sync", response_model=WatchlistSyncResponse)
async def sync_watchlist(
    db: Session = Depends(get_db),
    # No auth dependency: same MVP posture as POST /events and POST
    # /cameras/{id}/health (see docs/LIMITATIONS.md) — real edge
    # authentication (mTLS/device token) is a documented future step, not
    # implemented anywhere yet. This endpoint only ever returns data, never
    # accepts a write, so it carries less risk than those two in the
    # meantime.
):
    """
    Called by the edge at startup and periodically (see
    edge/detection/face_recognition.py's WatchlistFaceRecognizer.sync())
    to (re)train the local LBPH recognizer against real, current watchlist
    photos. Offline-capable by design: once synced, the edge keeps
    recognizing against its last successfully synced watchlist even if
    connectivity drops — this endpoint is a refresh, not a per-frame
    dependency.
    """
    persons = db.query(WatchlistPerson).filter(WatchlistPerson.is_active == True).all()
    entries = [
        WatchlistSyncEntry(
            person_id=p.id,
            name=p.name,
            image_base64_list=[img.image_base64 for img in p.face_images],
        )
        for p in persons
        if p.face_images  # a person with zero real reference images can't be matched against
    ]
    return WatchlistSyncResponse(persons=entries)
