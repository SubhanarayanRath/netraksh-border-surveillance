"""
NETRAKSH — System / health / sync status router.
GET  /health           — liveness (no auth)
GET  /system/status    — system overview (authenticated)
GET  /sync/status      — edge sync queue status
POST /system/metrics   — periodic real edge performance telemetry
GET  /system/metrics   — latest performance snapshot per edge device
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import Alert, Camera, Event, PipelineMetricsSnapshot, SyncQueue
from backend.security.auth import require_any_role
from shared.schemas import PipelineMetricsReport, PipelineMetricsResponse

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


@router.post("/system/metrics", status_code=201)
async def report_metrics(
    payload: PipelineMetricsReport,
    db: Session = Depends(get_db),
    # MVP: edge authentication disabled for local demo, same posture as
    # POST /events and POST /cameras/{id}/health — see docs/LIMITATIONS.md.
):
    """
    Periodic real performance telemetry push from the edge
    (edge/main.py's EdgePipeline._report_metrics, every
    metrics_report_interval_seconds — default 10s).

    Before this endpoint existed, edge/instrumentation/metrics.py's real,
    perf_counter()-measured latency/FPS/CPU/RSS was written only to a local
    JSON file on the edge device (edge/data/metrics_*.json) and never
    reached the backend at all — there was nothing for a Performance
    dashboard page to show. This is what actually connects the two.
    """
    record = PipelineMetricsSnapshot(
        edge_device_id=payload.edge_device_id,
        timestamp=payload.timestamp,
        uptime_seconds=payload.uptime_seconds,
        fps=payload.fps,
        frames_json=payload.frames,
        events_json=payload.events,
        alerts_generated=payload.alerts_generated,
        cpu_percent=payload.cpu_percent,
        rss_mb=payload.rss_mb,
        psutil_available=payload.psutil_available,
        adaptive_gate_json=payload.adaptive_gate,
    )
    db.add(record)
    db.commit()

    from backend.api.websocket import broadcast_metrics
    asyncio.create_task(broadcast_metrics(_metrics_to_response(record).model_dump(mode="json")))

    return {"edge_device_id": payload.edge_device_id, "fps": payload.fps}


@router.get("/system/metrics", response_model=List[PipelineMetricsResponse])
async def list_latest_metrics(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    The single latest snapshot per distinct edge device that has ever
    reported — real "current status of every known edge process", the
    same "one row per known X" shape as GET /cameras.
    """
    device_ids = [row[0] for row in db.query(PipelineMetricsSnapshot.edge_device_id).distinct().all()]
    latest = []
    for device_id in device_ids:
        snap = (
            db.query(PipelineMetricsSnapshot)
            .filter(PipelineMetricsSnapshot.edge_device_id == device_id)
            .order_by(desc(PipelineMetricsSnapshot.timestamp))
            .first()
        )
        if snap:
            latest.append(_metrics_to_response(snap))
    return latest


@router.get("/system/metrics/history", response_model=List[PipelineMetricsResponse])
async def metrics_history(
    edge_device_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Recent snapshots for one edge device, oldest first — for a trend line."""
    rows = (
        db.query(PipelineMetricsSnapshot)
        .filter(PipelineMetricsSnapshot.edge_device_id == edge_device_id)
        .order_by(desc(PipelineMetricsSnapshot.timestamp))
        .limit(min(limit, 500))
        .all()
    )
    return [_metrics_to_response(r) for r in reversed(rows)]


def _metrics_to_response(snap: PipelineMetricsSnapshot) -> PipelineMetricsResponse:
    return PipelineMetricsResponse(
        edge_device_id=snap.edge_device_id,
        timestamp=snap.timestamp,
        uptime_seconds=snap.uptime_seconds,
        fps=snap.fps,
        frames=snap.frames_json,
        events=snap.events_json,
        alerts_generated=snap.alerts_generated,
        cpu_percent=snap.cpu_percent,
        rss_mb=snap.rss_mb,
        psutil_available=snap.psutil_available,
        adaptive_gate=snap.adaptive_gate_json,
    )

