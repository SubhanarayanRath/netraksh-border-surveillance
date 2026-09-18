"""
NETRAKSH Backend — Database connection and session management.
"""
import logging
from typing import Generator

from sqlalchemy import create_engine, inspect, text
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


def _migrate_add_missing_columns(test_engine=None) -> None:
    """
    Base.metadata.create_all() only creates NEW tables — it never alters an
    existing one. A cameras table created before architecture v4 §10 has no
    evidence_key_wrapped column; this adds it if missing, the same way
    edge/sync/sync_client.py's own migration guard handles the equivalent
    gap on the edge side. Database-agnostic (SQLAlchemy's inspector, not
    SQLite-only PRAGMA) since DATABASE_URL can point at SQLite or Postgres.
    Safe to call every startup — a no-op once the column exists.
    """
    active_engine = test_engine if test_engine is not None else engine
    inspector = inspect(active_engine)
    if "cameras" not in inspector.get_table_names():
        return  # brand-new database — create_all() above already got it right
    existing_columns = {col["name"] for col in inspector.get_columns("cameras")}
    if "evidence_key_wrapped" not in existing_columns:
        logger.info("[DB] Migrating cameras table: adding evidence_key_wrapped column")
        with active_engine.begin() as conn:
            conn.execute(text("ALTER TABLE cameras ADD COLUMN evidence_key_wrapped TEXT"))
    # latitude/longitude — added for the real geospatial map (previously the
    # Alerts page's map was pure decoration: no camera anywhere had real
    # coordinates). Same guard pattern as evidence_key_wrapped above.
    if "latitude" not in existing_columns:
        logger.info("[DB] Migrating cameras table: adding latitude/longitude columns")
        with active_engine.begin() as conn:
            conn.execute(text("ALTER TABLE cameras ADD COLUMN latitude FLOAT"))
            conn.execute(text("ALTER TABLE cameras ADD COLUMN longitude FLOAT"))

    # Performance telemetry counters were historically written only to the
    # edge log.  Add nullable columns without backfilling so old snapshots
    # remain explicitly unavailable rather than incorrectly becoming zero.
    if "pipeline_metrics" in inspector.get_table_names():
        metrics_columns = {col["name"] for col in inspector.get_columns("pipeline_metrics")}
        missing_metrics_columns = {
            "telemetry_produced": "INTEGER",
            "telemetry_dropped": "INTEGER",
            "telemetry_errors": "INTEGER",
        }
        with active_engine.begin() as conn:
            for column, column_type in missing_metrics_columns.items():
                if column not in metrics_columns:
                    logger.info("[DB] Migrating pipeline_metrics table: adding %s", column)
                    conn.execute(text(f"ALTER TABLE pipeline_metrics ADD COLUMN {column} {column_type}"))

    # Cross-camera corroboration (backend/services/cross_camera.py) — same
    # guard pattern, applied to the events table.
    if "events" in inspector.get_table_names():
        existing_event_columns = {col["name"] for col in inspector.get_columns("events")}
        if "corroboration_score" not in existing_event_columns:
            logger.info("[DB] Migrating events table: adding cross-camera corroboration columns")
            with active_engine.begin() as conn:
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
            with active_engine.begin() as conn:
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
    # applied to the alerts table.
    # A REAL, PREVIOUSLY-SHIPPED PRODUCTION CRASH, found via the live Render
    # deploy log (2026-09-07): `DATETIME` is a SQLite type-affinity keyword,
    # not a real Postgres type -- SQLite accepts it silently (this project's
    # entire local test suite runs against SQLite only, so nothing local
    # could have caught it), Postgres raises
    # `psycopg2.errors.UndefinedObject: type "datetime" does not exist` and
    # crashes application startup. This is the exact same class of
    # SQLite-lenient/Postgres-strict divergence as the earlier
    # `BOOLEAN DEFAULT 0` incident (see docs/ARCHITECTURE.md/LIMITATIONS.md)
    # -- the "VARCHAR defaults, so no risk of the BOOLEAN-literal bug"
    # comment this replaced checked for that one specific pattern and missed
    # this different one. Fixed to `TIMESTAMP`, a real type in both engines.
    if "alerts" in inspector.get_table_names():
        existing_alert_columns = {col["name"] for col in inspector.get_columns("alerts")}
        if "closed_at" not in existing_alert_columns:
            logger.info("[DB] Migrating alerts table: adding close-action columns")
            with active_engine.begin() as conn:
                conn.execute(text("ALTER TABLE alerts ADD COLUMN closed_at TIMESTAMP"))
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
            with active_engine.begin() as conn:
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
            with active_engine.begin() as conn:
                conn.execute(text("ALTER TABLE events ADD COLUMN face_match_person_id VARCHAR(36)"))
                conn.execute(text("ALTER TABLE events ADD COLUMN face_match_person_name VARCHAR(128)"))
                conn.execute(text("ALTER TABLE events ADD COLUMN face_match_confidence FLOAT"))

    # Complete Event Schema Reconciliation (Phase 7.4.2B)
    # NOTE: This block is intentionally at module scope (NOT nested inside the
    # alerts guard above). Previously it was erroneously indented under
    # `if "alerts" in inspector.get_table_names()`, which caused it to be
    # silently skipped in any environment where the alerts table didn't
    # exist (test environments using sqlite in-memory DBs, fresh deploys
    # that hadn't yet created alerts). The fix: own independent guard.
    if "events" in inspector.get_table_names():
        # Re-inspect: the earlier block (cross-camera corroboration) may have
        # already been applied to an older session_module.engine; get a fresh
        # column set so the diff is accurate.
        existing_event_columns = {col["name"] for col in inspect(active_engine).get_columns("events")}

        # Full set of non-base columns the Event ORM declares. "Base columns"
        # (id, camera_id, zone_id, timestamp, event_type, detection_class,
        # confidence, scene_condition, camera_health_state, decision_state,
        # decision_reason, track_id, severity, direction, rule, rule_value,
        # plate_text, plate_confidence, evidence_clip_ref, evidence_image_ref)
        # were present in v1 schema and are excluded here.
        expected_event_columns = {
            "stream_id": "VARCHAR(36)",
            "video_time": "FLOAT",
            "vehicle_subtype": "VARCHAR(32)",
            "face_match_person_id": "VARCHAR(36)",
            "face_match_person_name": "VARCHAR(128)",
            "face_match_confidence": "FLOAT",
            "storage_provider": "VARCHAR(32) DEFAULT 'local'",
            "object_key": "VARCHAR(512)",
            "storage_status": "VARCHAR(32) DEFAULT 'CREATED'",
            "content_hash": "VARCHAR(64)",
            "content_size": "INTEGER",
            "uploaded_at": "TIMESTAMP",
            "storage_version_id": "VARCHAR(128)",
            "failure_reason": "VARCHAR(256)",
            "corroboration_score": "FLOAT",
            "corroborated_by_event_id": "VARCHAR(36)",
            "corroboration_distance_m": "FLOAT",
            "corroboration_delta_t_s": "FLOAT",
            "corroboration_t_expected_s": "FLOAT",
            "corroboration_sigma_s": "FLOAT",
            "corroborating_camera_id": "VARCHAR(36)",
            "corroboration_status": "VARCHAR(32)",
            "appearance_similarity": "FLOAT",
            "representation_type": "VARCHAR(64)",
            "bbox_x": "FLOAT",
            "bbox_y": "FLOAT",
            "bbox_w": "FLOAT",
            "bbox_h": "FLOAT",
            "score_d": "FLOAT",
            "score_t": "FLOAT",
            "score_s": "FLOAT",
            "score_h": "FLOAT",
            "score_r": "FLOAT",
            "edge_device_id": "VARCHAR(64)",
            "sequence_number": "INTEGER",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "synced_from_edge": "BOOLEAN DEFAULT FALSE"
        }
        
        missing_columns = [
            (col, col_type) for col, col_type in expected_event_columns.items()
            if col not in existing_event_columns
        ]
        
        if missing_columns:
            logger.info(f"[DB] Migrating events table: adding {len(missing_columns)} missing columns")
            with active_engine.begin() as conn:
                for col_name, col_type in missing_columns:
                    logger.info(f"[DB] Adding column: {col_name} {col_type}")
                    if active_engine.url.drivername == "sqlite" and "DEFAULT" in col_type.upper():
                        col_type = col_type.split("DEFAULT")[0].strip()
                    conn.execute(text(f"ALTER TABLE events ADD COLUMN {col_name} {col_type}"))

    # evidence_packages — Phase 4 WP-4 introduced kid, verification booleans,
    # raw_package_json, and created_at after the table's original creation.
    # create_all() never alters an existing table so these are never applied
    # automatically when an old DB is in use.
    if "evidence_packages" in inspector.get_table_names():
        existing_ep_cols = {col["name"] for col in inspector.get_columns("evidence_packages")}
        expected_ep_columns = {
            "schema_version": "VARCHAR(32)",
            "crypto_version": "VARCHAR(32)",
            "kid": "VARCHAR(64)",
            "hash_valid": "BOOLEAN",
            "signature_valid": "BOOLEAN",
            "chain_valid": "BOOLEAN",
            "raw_package_json": "TEXT",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        missing_ep = [
            (col, typ) for col, typ in expected_ep_columns.items()
            if col not in existing_ep_cols
        ]
        if missing_ep:
            logger.info(f"[DB] Migrating evidence_packages table: adding {len(missing_ep)} missing columns")
            with active_engine.begin() as conn:
                for col_name, col_type in missing_ep:
                    logger.info(f"[DB] Adding column: evidence_packages.{col_name} {col_type}")
                    if active_engine.url.drivername == "sqlite" and "DEFAULT" in col_type.upper():
                        col_type = col_type.split("DEFAULT")[0].strip()
                    conn.execute(text(f"ALTER TABLE evidence_packages ADD COLUMN {col_name} {col_type}"))

    # evidence_chain — created by Phase 4 WP-4; kid/verification columns may
    # be absent on databases created before that work landed.
    if "evidence_chain" in inspector.get_table_names():
        existing_ec_cols = {col["name"] for col in inspector.get_columns("evidence_chain")}
        expected_ec_columns = {
            "kid": "VARCHAR(64)",
            "chain_valid": "BOOLEAN",
            "verified_at": "TIMESTAMP",
        }
        missing_ec = [
            (col, typ) for col, typ in expected_ec_columns.items()
            if col not in existing_ec_cols
        ]
        if missing_ec:
            logger.info(f"[DB] Migrating evidence_chain table: adding {len(missing_ec)} missing columns")
            with engine.begin() as conn:
                for col_name, col_type in missing_ec:
                    logger.info(f"[DB] Adding column: evidence_chain.{col_name} {col_type}")
                    conn.execute(text(f"ALTER TABLE evidence_chain ADD COLUMN {col_name} {col_type}"))

    # webhook_subscriptions — Phase 4 delivery-health columns.
    if "webhook_subscriptions" in inspector.get_table_names():
        existing_ws_cols = {col["name"] for col in inspector.get_columns("webhook_subscriptions")}
        expected_ws_columns = {
            "last_delivery_at": "TIMESTAMP",
            "last_delivery_status": "VARCHAR(16)",
            "last_delivery_error": "VARCHAR(512)",
        }
        missing_ws = [
            (col, typ) for col, typ in expected_ws_columns.items()
            if col not in existing_ws_cols
        ]
        if missing_ws:
            logger.info(f"[DB] Migrating webhook_subscriptions table: adding {len(missing_ws)} missing columns")
            with engine.begin() as conn:
                for col_name, col_type in missing_ws:
                    logger.info(f"[DB] Adding column: webhook_subscriptions.{col_name} {col_type}")
                    conn.execute(text(f"ALTER TABLE webhook_subscriptions ADD COLUMN {col_name} {col_type}"))

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
