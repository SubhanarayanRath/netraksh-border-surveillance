"""
NETRAKSH — FastAPI application entrypoint.
Boots the backend: database init, user bootstrap, routers, CORS, WebSocket.
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import alerts, auth, cameras, events, system, websocket
from backend.config import settings
from backend.database.session import SessionLocal, init_db
from backend.security.auth import bootstrap_users

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("NETRAKSH backend starting up...")
    # Initialize database tables
    init_db()
    # Bootstrap default users
    db = SessionLocal()
    try:
        bootstrap_users(db)
        # Seed a demo camera if none exist
        _seed_demo_data(db)
    finally:
        db.close()
    logger.info(f"Command Center ready. Command ID: {settings.COMMAND_ID}")
    logger.info(f"Blockchain mode: {settings.BLOCKCHAIN_MODE.upper()}")
    if settings.BLOCKCHAIN_MODE == "mock":
        logger.warning(f"  -> {settings.BLOCKCHAIN_MOCK_LABEL}")
    yield
    logger.info("NETRAKSH backend shutting down.")


def _seed_demo_data(db) -> None:
    """Seed demo cameras and zones if the database is empty."""
    from backend.models.orm import Camera, Zone
    import json

    if db.query(Camera).count() > 0:
        return

    logger.info("Seeding demo camera and zone data...")

    # Coordinates placed near the real Attari-Wagah border checkpoint,
    # Punjab (a real, publicly-known India-Pakistan border crossing) for
    # geographic plausibility on the geospatial map — these are NOT real
    # deployed camera positions or an implied actual MHA installation,
    # same "realistic but clearly a demo" spirit as the rest of this
    # project's seed data (e.g. scripts/seed_demo_events.py).
    # Command A — main camera
    cam_a = Camera(
        id="cam-border-01",
        name="Border Post Alpha - Camera 1",
        location="Sector 7, Border Post Alpha",
        rtsp_url=None,
        owning_command_id="COMMAND_A",
        latitude=31.6050,
        longitude=74.5700,
    )
    cam_b = Camera(
        id="cam-checkpoint-01",
        name="Checkpoint Bravo - Camera 1",
        location="Main checkpoint, Sector 7",
        rtsp_url=None,
        owning_command_id="COMMAND_A",
        latitude=31.6025,
        longitude=74.5745,
    )
    db.add_all([cam_a, cam_b])
    db.flush()

    # Fence zone on cam_a — crosses jurisdiction to COMMAND_B
    fence_zone = Zone(
        id="zone-fence-01",
        camera_id="cam-border-01",
        name="Border Fence Zone",
        zone_type="fence",
        polygon_json=json.dumps([
            {"x": 0.1, "y": 0.4}, {"x": 0.9, "y": 0.4},
            {"x": 0.9, "y": 0.6}, {"x": 0.1, "y": 0.6}
        ]),
        owning_command_id="COMMAND_A",
        adjacent_command_id="COMMAND_B",  # → cross-command escalation eligible
    )
    # Checkpoint zone — ANPR
    checkpoint_zone = Zone(
        id="zone-checkpoint-01",
        camera_id="cam-checkpoint-01",
        name="Checkpoint Entry Zone",
        zone_type="checkpoint",
        polygon_json=json.dumps([
            {"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2},
            {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}
        ]),
        owning_command_id="COMMAND_A",
        adjacent_command_id=None,
    )
    db.add_all([fence_zone, checkpoint_zone])
    db.commit()
    logger.info("Demo seed complete: 2 cameras, 2 zones")


app = FastAPI(
    title="NETRAKSH Command Center",
    description=(
        "AI-Based Intelligent Video Analytics Platform for Border Surveillance. "
        "Reliability-qualified decisions: DETECTED / UNCERTAIN / ABSTAIN. "
        "SIH 2026, PS #187, Team SecureX."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — restricted to known frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include all routers
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(events.router)
app.include_router(alerts.router)
app.include_router(websocket.router)

from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from pathlib import Path

# Mount static frontend. Resolved relative to this file's own location
# (repo_root/backend/main.py -> repo_root/frontend/dist), not a hardcoded
# absolute path — the previous "d:/SIH/netraksh/frontend/dist" only ever
# worked on this one Windows dev machine and would 404 everything on any
# other machine, including a Linux container.
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Allow API routes to pass through if they 404 (handled before this catch-all)
        # But for anything else, serve index.html for SPA routing
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
