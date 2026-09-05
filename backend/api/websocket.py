"""
NETRAKSH — WebSocket router for live dashboard alerts.
WS /ws/alerts — push new alerts to dashboard clients.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

# Global set of connected WebSocket clients
_connected_clients: Set[WebSocket] = set()


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    """
    Live alert stream for the dashboard.
    """
    await websocket.accept()
    _connected_clients.add(websocket)
    logger.info(f"WebSocket alerts client connected. Total: {len(_connected_clients)}")

@router.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """
    Live event stream for the dashboard.
    """
    await websocket.accept()
    _connected_clients.add(websocket)
    logger.info(f"WebSocket dashboard client connected. Total: {len(_connected_clients)}")
    try:
        # Keep alive
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "timestamp": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        _connected_clients.discard(websocket)
        logger.info(f"WebSocket dashboard client disconnected.")


async def broadcast_alert(alert_data: dict) -> None:
    """Called by escalation service when a new alert is created."""
    if not _connected_clients:
        return
    message = json.dumps({
        "type": "new_alert", 
        "alert": jsonable_encoder(alert_data), 
        "timestamp": datetime.utcnow().isoformat()
    })
    disconnected = set()
    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    _connected_clients.difference_update(disconnected)


async def broadcast_camera_health(health_data: dict) -> None:
    """Called when camera health state changes."""
    if not _connected_clients:
        return
    message = json.dumps({
        "type": "camera_health",
        "health": jsonable_encoder(health_data),
        "timestamp": datetime.utcnow().isoformat()
    })
    disconnected = set()
    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    _connected_clients.difference_update(disconnected)


async def broadcast_metrics(metrics_data: dict) -> None:
    """Called when a real edge performance snapshot is ingested (POST /system/metrics)."""
    if not _connected_clients:
        return
    message = json.dumps({
        "type": "pipeline_metrics",
        "metrics": jsonable_encoder(metrics_data),
        "timestamp": datetime.utcnow().isoformat(),
    })
    disconnected = set()
    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    _connected_clients.difference_update(disconnected)

from fastapi.encoders import jsonable_encoder

async def broadcast_event(event_data: dict) -> None:
    """Called when a new event is ingested."""
    if not _connected_clients:
        return
    message = json.dumps({
        "type": "new_event", 
        "payload": jsonable_encoder(event_data), 
        "timestamp": datetime.utcnow().isoformat()
    })
    disconnected = set()
    for client in _connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    _connected_clients.difference_update(disconnected)
