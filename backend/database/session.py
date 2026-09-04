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
