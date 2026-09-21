"""
NETRAKSH — System / health / sync status router.
GET  /health           — liveness (no auth)
GET  /system/status    — system overview (authenticated)
GET  /sync/status      — edge sync queue status
POST /system/metrics   — periodic real edge performance telemetry
GET  /system/metrics   — latest performance snapshot per edge device
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import (
    Alert, Camera, Event, PipelineMetricsSnapshot, SyncQueue, AuditLog,
    CameraHealth, AnalysisTelemetrySnapshot,
)
from backend.security.auth import require_edge_auth
from backend.security.auth import require_any_role
from shared.schemas import PipelineMetricsReport, PipelineMetricsResponse, LiveTelemetryPayload
from backend.api.websocket import broadcast_telemetry

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


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe — verifies required dependencies (like DB) are reachable."""
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Database unavailable")


@router.get("/system/diagnostic")
async def diagnostic_snapshot(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Safe aggregate operational diagnostic view.
    Never exposes passwords, keys, tokens, or raw evidence payloads.
    """
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "HEALTHY"
    except Exception as e:
        logger.error(f"Diagnostic DB check failed: {e}")
        db_status = "FAILED"

    # Count cameras by health state
    total_cameras = db.query(Camera).count()
    degraded = db.query(CameraHealth).filter(CameraHealth.health_state == "DEGRADED").count()
    failed = db.query(CameraHealth).filter(CameraHealth.health_state == "FAILED").count()
    healthy = total_cameras - (degraded + failed)

    # Sync status
    queued = db.query(SyncQueue).filter(SyncQueue.sync_status == "QUEUED").count()
    failed_sync = db.query(SyncQueue).filter(SyncQueue.sync_status == "FAILED").count()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "backend_readiness": "HEALTHY" if db_status == "HEALTHY" else "FAILED",
        "database_status": db_status,
        "cameras": {
            "total": total_cameras,
            "healthy": healthy,
            "degraded": degraded,
            "failed": failed,
        },
        "sync_queue": {
            "queued": queued,
            "failed": failed_sync,
        }
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
    # Read the latest metric snapshot to get the real edge queue depth
    latest_metrics = (
        db.query(PipelineMetricsSnapshot)
        .order_by(desc(PipelineMetricsSnapshot.timestamp))
        .first()
    )
    
    edge_queued = 0
    if latest_metrics and latest_metrics.events_json and "queue_depth" in latest_metrics.events_json:
        edge_queued = latest_metrics.events_json["queue_depth"]

    # For 'synced' and 'failed', we can either use the metrics or keep using the backend DB 
    # to show the overall backend-to-chain status as well, but the instruction specifically 
    # said: "Propagate the true edge queue depth... UI must show the edge's actual outbound queue size."
    return {
        "queued": edge_queued,
        "synced": latest_metrics.events_json.get("sent", {}).get("count", 0) if latest_metrics and latest_metrics.events_json else 0,
        "failed": latest_metrics.events_json.get("failed", {}).get("count", 0) if latest_metrics and latest_metrics.events_json else 0,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/system/verify-chain")
async def verify_chain(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    from backend.models.orm import EvidencePackage
    evidence_list = db.query(EvidencePackage).order_by(EvidencePackage.id).all()
    if not evidence_list:
        return {"is_valid": True, "message": "No evidence on chain yet."}
    
    invalid_count = sum(1 for ev in evidence_list if ev.chain_status == 'INVALID')
    pending_count = sum(1 for ev in evidence_list if ev.chain_status == 'PENDING')
    
    if invalid_count > 0:
        return {"is_valid": False, "message": f"{invalid_count} block(s) failed integrity verification. Chain compromised."}
    elif pending_count > 0:
        return {"is_valid": True, "message": f"Verified {len(evidence_list) - pending_count} blocks. {pending_count} blocks pending chain sync."}
    else:
        return {"is_valid": True, "message": f"Successfully verified {len(evidence_list)} blocks across all edge hash chains."}


_telemetry_requests = 0
_latest_telemetry: Dict[str, Dict[str, Any]] = {}

@router.post("/system/telemetry", status_code=202)
async def post_telemetry(
    payload: LiveTelemetryPayload,
    db: Session = Depends(get_db),
    edge_identity=Depends(require_edge_auth)
):
    """
    Ingest live track telemetry from the edge pipeline.
    This is an operational snapshot, kept in memory and broadcast to clients.
    Keeping the latest item per camera lets a browser reload restore the real
    PROCESSING/COMPLETED lifecycle without inventing status client-side.
    """
    if edge_identity and edge_identity.edge_id != payload.camera_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Authenticated edge identity does not match camera_id")

    global _telemetry_requests
    _telemetry_requests += 1
    if _telemetry_requests % 100 == 0:
        logger.info(f"[Telemetry] Received {_telemetry_requests} payloads from edge")
        
    telemetry = payload.model_dump()
    _latest_telemetry[payload.camera_id] = telemetry
    # Keep one durable latest snapshot per camera/session. This is intentionally
    # not a telemetry history table: it provides restart restoration without
    # turning high-frequency live telemetry into unbounded database growth.
    query = db.query(AnalysisTelemetrySnapshot).filter(
        AnalysisTelemetrySnapshot.camera_id == payload.camera_id,
    )
    if payload.stream_id is None:
        query = query.filter(AnalysisTelemetrySnapshot.stream_id.is_(None))
    else:
        query = query.filter(AnalysisTelemetrySnapshot.stream_id == payload.stream_id)
    snapshot = query.first()
    snapshot_values = {
        "camera_id": payload.camera_id,
        "stream_id": payload.stream_id,
        "timestamp": payload.timestamp,
        "video_time": payload.video_time,
        "sequence": payload.sequence,
        "frame_width": payload.frame_width,
        "frame_height": payload.frame_height,
        "analysis_state": payload.analysis_state,
        "tracks_json": [track.model_dump() for track in payload.tracks],
    }
    if snapshot is None:
        db.add(AnalysisTelemetrySnapshot(**snapshot_values))
    else:
        for key, value in snapshot_values.items():
            setattr(snapshot, key, value)
    db.commit()
    await broadcast_telemetry(telemetry)
    return {"status": "ok"}


@router.get("/system/telemetry/latest")
async def latest_telemetry(
    camera_id: Optional[str] = None,
    stream_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user=Depends(require_any_role),
):
    """Return real last-seen telemetry snapshots matching the active context."""
    query = db.query(AnalysisTelemetrySnapshot)
    if camera_id:
        query = query.filter(AnalysisTelemetrySnapshot.camera_id == camera_id)
    if stream_id:
        query = query.filter(AnalysisTelemetrySnapshot.stream_id == stream_id)
    persisted = query.order_by(desc(AnalysisTelemetrySnapshot.timestamp)).all()
    return [
        {
            "camera_id": item.camera_id,
            "timestamp": item.timestamp,
            "video_time": item.video_time,
            "sequence": item.sequence,
            "frame_width": item.frame_width,
            "frame_height": item.frame_height,
            "stream_id": item.stream_id,
            "analysis_state": item.analysis_state,
            "tracks": item.tracks_json or [],
        }
        for item in persisted
    ]


@router.post("/system/metrics", status_code=201)
async def report_metrics(
    payload: PipelineMetricsReport,
    db: Session = Depends(get_db),
    edge_identity = Depends(require_edge_auth),
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
    if edge_identity and edge_identity.edge_id != payload.edge_device_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Authenticated edge identity does not match edge_device_id")

    record = PipelineMetricsSnapshot(
        edge_device_id=edge_identity.edge_id if edge_identity else payload.edge_device_id,
        timestamp=payload.timestamp,
        uptime_seconds=payload.uptime_seconds,
        fps=payload.fps,
        frames_json=payload.frames,
        events_json=payload.events,
        alerts_generated=payload.alerts_generated,
        telemetry_produced=payload.telemetry_produced,
        telemetry_dropped=payload.telemetry_dropped,
        telemetry_errors=payload.telemetry_errors,
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
        telemetry_produced=snap.telemetry_produced,
        telemetry_dropped=snap.telemetry_dropped,
        telemetry_errors=snap.telemetry_errors,
        cpu_percent=snap.cpu_percent,
        rss_mb=snap.rss_mb,
        psutil_available=snap.psutil_available,
        adaptive_gate=snap.adaptive_gate_json,
    )

@router.get("/api/nodes/health")
async def nodes_health(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Consolidated operational health of all registered sensors (Phase 6).
    Aggregates CameraHealth and PipelineMetricsSnapshot.
    """
    cameras = db.query(Camera).filter(Camera.is_active == True).all()
    results = []
    
    for cam in cameras:
        # Get latest health record
        latest_health = (
            db.query(CameraHealth)
            .filter(CameraHealth.camera_id == cam.id)
            .order_by(desc(CameraHealth.timestamp))
            .first()
        )
        
        # Get latest metrics snapshot matching this camera's edge_device_id. 
        # (Assuming edge_device_id maps 1:1 to camera_id for this demo, or we can just fetch metrics by camera_id if they are the same)
        # The schema uses edge_device_id. For demo, edge_device_id == camera_id typically.
        latest_metrics = (
            db.query(PipelineMetricsSnapshot)
            .filter(PipelineMetricsSnapshot.edge_device_id == cam.id)
            .order_by(desc(PipelineMetricsSnapshot.timestamp))
            .first()
        )
        
        results.append({
            "camera_id": cam.id,
            "name": cam.name,
            "health_state": latest_health.health_state if latest_health else "UNKNOWN",
            # Missing measurements are not zero measurements.  Consumers use
            # null together with last_ping freshness to render N/A/OFFLINE.
            "uptime_seconds": latest_metrics.uptime_seconds if latest_metrics else None,
            "cpu_percent": latest_metrics.cpu_percent if latest_metrics else None,
            "fps": latest_metrics.fps if latest_metrics else None,
            "last_ping": (latest_metrics.timestamp.isoformat() + "Z") if latest_metrics else ((latest_health.timestamp.isoformat() + "Z") if latest_health else None),
        })
        
    return results
