"""
NETRAKSH — System / health / sync status router.
GET /health          — liveness (no auth)
GET /system/status   — system overview (authenticated)
GET /sync/status     — edge sync queue status
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import Alert, Camera, Event, SyncQueue
from backend.security.auth import require_any_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check():
    """Liveness probe — no authentication required."""
    return {
        "status": "ok",
        "service": "NETRAKSH Command Center",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    }


@router.get("/system/status")
async def system_status(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    camera_count = db.query(Camera).filter(Camera.is_active == True).count()
    event_count = db.query(Event).count()
    alert_count = db.query(Alert).count()
    pending_acks = db.query(Alert).filter(Alert.acknowledged_at.is_(None)).count()
    queued_sync = db.query(SyncQueue).filter(SyncQueue.sync_status == "QUEUED").count()

    return {
        "status": "operational",
        "command_id": settings.COMMAND_ID,
        "blockchain_mode": settings.BLOCKCHAIN_MODE,
        "blockchain_label": settings.BLOCKCHAIN_MOCK_LABEL if settings.BLOCKCHAIN_MODE == "mock" else "FABRIC",
        "cameras_active": camera_count,
        "total_events": event_count,
        "total_alerts": alert_count,
        "pending_acknowledgements": pending_acks,
        "queued_for_sync": queued_sync,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/sync/status")
async def sync_status(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    queued = db.query(SyncQueue).filter(SyncQueue.sync_status == "QUEUED").count()
    synced = db.query(SyncQueue).filter(SyncQueue.sync_status == "SYNCED").count()
    failed = db.query(SyncQueue).filter(SyncQueue.sync_status == "FAILED").count()

    return {
        "queued": queued,
        "synced": synced,
        "failed": failed,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/system/verify-chain")
async def verify_chain(
    db: Session = Depends(get_db),
):
    from backend.models.orm import EvidencePackage
    evidence_list = db.query(EvidencePackage).order_by(EvidencePackage.id).all()
    if not evidence_list:
        return {"is_valid": True, "message": "No evidence on chain yet."}
    
    invalid_count = sum(1 for ev in evidence_list if not ev.verified_ok)
    if invalid_count == 0:
        return {"is_valid": True, "message": f"Successfully verified {len(evidence_list)} blocks across all edge hash chains."}
    else:
        return {"is_valid": False, "message": f"{invalid_count} block(s) failed integrity verification. Chain compromised."}

