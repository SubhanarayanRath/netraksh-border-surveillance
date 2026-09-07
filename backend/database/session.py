"""
NETRAKSH Backend — Database connection and session management.
"""
import logging
from typing import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings
from backend.models.orm import Base

logger = logging.getLogger(__name__)

# SQLite requires connect_args={'check_same_thread': False} and does not support pool_size/max_overflow
if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=settings.DEBUG,
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=settings.DEBUG,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_add_missing_columns() -> None:
    """
    Base.metadata.create_all() only creates NEW tables — it never alters an
    existing one. A cameras table created before architecture v4 §10 has no
    evidence_key_wrapped column; this adds it if missing, the same way
    edge/sync/sync_client.py's own migration guard handles the equivalent
    gap on the edge side. Database-agnostic (SQLAlchemy's inspector, not
    SQLite-only PRAGMA) since DATABASE_URL can point at SQLite or Postgres.
    Safe to call every startup — a no-op once the column exists.
    """
    inspector = inspect(engine)
    if "cameras" not in inspector.get_table_names():
        return  # brand-new database — create_all() above already got it right
    existing_columns = {col["name"] for col in inspector.get_columns("cameras")}
    if "evidence_key_wrapped" not in existing_columns:
        logger.info("[DB] Migrating cameras table: adding evidence_key_wrapped column")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cameras ADD COLUMN evidence_key_wrapped TEXT"))
    # latitude/longitude — added for the real geospatial map (previously the
    # Alerts page's map was pure decoration: no camera anywhere had real
    # coordinates). Same guard pattern as evidence_key_wrapped above.
    if "latitude" not in existing_columns:
        logger.info("[DB] Migrating cameras table: adding latitude/longitude columns")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cameras ADD COLUMN latitude FLOAT"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN longitude FLOAT"))

    # Cross-camera corroboration (backend/services/cross_camera.py) — same
    # guard pattern, applied to the events table.
    if "events" in inspector.get_table_names():
        existing_event_columns = {col["name"] for col in inspector.get_columns("events")}
        if "corroboration_score" not in existing_event_columns:
            logger.info("[DB] Migrating events table: adding cross-camera corroboration columns")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE events ADD COLUMN corroboration_score FLOAT"))
                conn.execute(text("ALTER TABLE events ADD COLUMN corroborated_by_event_id VARCHAR(36)"))
                conn.execute(text("ALTER TABLE events ADD COLUMN corroboration_distance_m FLOAT"))
                conn.execute(text("ALTER TABLE events ADD COLUMN corroboration_delta_t_s FLOAT"))

    # Cross-camera corroboration wired into escalation (backend/services/
    # escalation.py) — same guard pattern, applied to the alerts table.
    if "alerts" in inspector.get_table_names():
        existing_alert_columns = {col["name"] for col in inspector.get_columns("alerts")}
        if "escalated_via_corroboration" not in existing_alert_columns:
            logger.info("[DB] Migrating alerts table: adding escalated_via_corroboration column")
            with engine.begin() as conn:
                # "DEFAULT 0" (an integer literal) is real, honest evidence of
                # this project's SQLite-only local testing: SQLite has no
                # real BOOLEAN type (it stores 0/1 as INTEGER and accepts
                # this silently), so it never caught the bug. The real
                # Postgres deployment (render.yaml) does enforce BOOLEAN's
                # real type and rejected it outright on startup:
                # "column ... is of type boolean but default expression is
                # of type integer" — a genuine production crash, not
                # hypothetical. FALSE is valid in both SQLite and Postgres.
                conn.execute(text("ALTER TABLE alerts ADD COLUMN escalated_via_corroboration BOOLEAN DEFAULT FALSE"))

    # Real alert "close" action (SIH PS 26187 audit finding: EventState.CLOSED
    # was defined but never actually set anywhere) -- same guard pattern,
    # applied to the alerts table. VARCHAR defaults, so no risk of the
    # BOOLEAN-literal bug immediately above.
    if "alerts" in inspector.get_table_names():
        existing_alert_columns = {col["name"] for col in inspector.get_columns("alerts")}
        if "closed_at" not in existing_alert_columns:
            logger.info("[DB] Migrating alerts table: adding close-action columns")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE alerts ADD COLUMN closed_at DATETIME"))
                conn.execute(text("ALTER TABLE alerts ADD COLUMN closed_by VARCHAR(64)"))
                conn.execute(text("ALTER TABLE alerts ADD COLUMN resolution_notes TEXT"))
                # Existing rows predate this column entirely; every alert
                # that already exists really was, at minimum, ALERTED (that
                # is how an Alert row comes to exist at all -- see
                # backend/services/escalation.py) -- a real, honest backfill
                # default, not an arbitrary placeholder.
                conn.execute(text("ALTER TABLE alerts ADD COLUMN lifecycle_state VARCHAR(16) DEFAULT 'ALERTED'"))

    # Vehicle classification (SIH PS 26187) -- same guard pattern, applied
    # to the events table. VARCHAR default, so no risk of the
    # SQLite/Postgres BOOLEAN-literal bug immediately above.
    if "events" in inspector.get_table_names():
        existing_event_columns = {col["name"] for col in inspector.get_columns("events")}
        if "vehicle_subtype" not in existing_event_columns:
            logger.info("[DB] Migrating events table: adding vehicle_subtype column")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE events ADD COLUMN vehicle_subtype VARCHAR(32)"))

    # Watchlist face recognition (SIH PS 26187) -- same guard pattern,
    # applied to the events table. WatchlistPerson/WatchlistFaceImage
    # themselves are brand-new tables, already handled by
    # Base.metadata.create_all() above; only these new columns on the
    # pre-existing events table need an explicit migration.
    if "events" in inspector.get_table_names():
        existing_event_columns = {col["name"] for col in inspector.get_columns("events")}
        if "face_match_person_id" not in existing_event_columns:
            logger.info("[DB] Migrating events table: adding face-match columns")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE events ADD COLUMN face_match_person_id VARCHAR(36)"))
                conn.execute(text("ALTER TABLE events ADD COLUMN face_match_person_name VARCHAR(128)"))
                conn.execute(text("ALTER TABLE events ADD COLUMN face_match_confidence FLOAT"))


def init_db() -> None:
    """Create all tables if they don't exist. Used for dev/test without migrations."""
    Base.metadata.create_all(bind=engine)
    _migrate_add_missing_columns()
    logger.info("Database tables created/verified")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a database session, closes after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
