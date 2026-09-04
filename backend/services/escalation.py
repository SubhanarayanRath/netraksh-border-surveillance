"""
NETRAKSH — Escalation engine.
Implements §1.3: trigger cross-command alert when BOTH conditions hold:
  1. severity >= HIGH
  2. the track's trajectory approaches/crosses a boundary zone
     (zone.adjacent_command_id is not None)

Only this code path submits to blockchain.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.orm import Alert, Event, Zone
from backend.services.blockchain import get_blockchain_client
from shared.constants import Severity
from shared.schemas import AlertIssuedTransaction

logger = logging.getLogger(__name__)


def check_and_escalate(event: Event, db: Session) -> None:
    """
    Called after event ingest. Determines escalation eligibility
    and submits AlertIssued to blockchain if both conditions hold.
    Non-blocking: blockchain failure is logged but does not propagate.
    """
    # Condition 1: severity threshold
    severity_eligible = event.severity in (Severity.HIGH.value,)
    if not severity_eligible:
        logger.debug(f"Event {event.id}: severity={event.severity}, not escalation-eligible")
        return

    # Condition 2: zone boundary check
    zone = db.query(Zone).filter(Zone.id == event.zone_id).first()
    crosses_boundary = zone is not None and zone.adjacent_command_id is not None

    if not crosses_boundary:
        logger.debug(f"Event {event.id}: zone {event.zone_id} has no adjacent command, not escalation-eligible")

    # Create alert record (for any HIGH severity event, even non-cross-command)
    existing_alert = db.query(Alert).filter(Alert.event_id == event.id).first()
    if existing_alert:
        return

    alert = Alert(
        event_id=event.id,
        severity=event.severity,
        crosses_jurisdiction_boundary=crosses_boundary,
        command_id_issuing=settings.COMMAND_ID,
        command_id_receiving=zone.adjacent_command_id if (zone and crosses_boundary) else None,
        blockchain_status="PENDING",
    )
    db.add(alert)
    db.flush()

    # Submit to blockchain only if BOTH conditions hold
    if severity_eligible and crosses_boundary:
        _submit_alert_issued(alert, event, db)

    db.commit()

    # Broadcast via WebSocket (non-blocking import to avoid circular dep)
    try:
        import asyncio
        from backend.api.websocket import broadcast_alert
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_alert({
                "alert_id": alert.id,
                "event_id": event.id,
                "severity": event.severity,
                "crosses_jurisdiction_boundary": crosses_boundary,
                "decision_state": event.decision_state,
                "camera_id": event.camera_id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            }))
    except Exception as exc:
        logger.debug(f"WebSocket broadcast failed (non-fatal): {exc}")


def _submit_alert_issued(alert: Alert, event: Event, db: Session) -> None:
    """Submit AlertIssued to blockchain. Failure is caught and logged — never propagates."""
    ep = db.query(
        __import__("backend.models.orm", fromlist=["EvidencePackage"]).EvidencePackage
    ).filter_by(event_id=event.id).first()

    tx = AlertIssuedTransaction(
        alert_id=alert.id,
        evidence_package_hash=ep.sha256 if ep else "",
        severity=event.severity,
        zone_id=event.zone_id or "",
        issuing_command_id=settings.COMMAND_ID,
        timestamp=datetime.utcnow(),
    )
    bc = get_blockchain_client()
    try:
        result = bc.submit_alert_issued(tx)
        alert.blockchain_tx_id = result.get("tx_id")
        alert.blockchain_status = result.get("status", "MOCK")
        alert.blockchain_submitted_at = datetime.utcnow()
        logger.info(
            f"AlertIssued submitted. alert_id={alert.id}, tx_id={alert.blockchain_tx_id}, "
            f"mode={settings.BLOCKCHAIN_MODE}"
        )
    except Exception as exc:
        logger.error(f"AlertIssued blockchain submission failed (non-fatal): {exc}")
        alert.blockchain_status = "FAILED"
