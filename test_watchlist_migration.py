import pytest
from sqlalchemy import create_engine, text, inspect
from backend.database.session import _migrate_add_missing_columns
from backend.models.orm import Base

def test_watchlist_migration_idempotent():
    # Use a fresh in-memory SQLite database
    test_engine = create_engine("sqlite:///:memory:")
    
    # Simulate OLD schema by creating the table manually without the new columns
    with test_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE cameras (
                id VARCHAR(36) PRIMARY KEY
            )
        """))
        conn.execute(text("""
            CREATE TABLE watchlist_persons (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                notes TEXT,
                is_active BOOLEAN,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Add a dummy row
        conn.execute(text("INSERT INTO watchlist_persons (id, name) VALUES ('test_1', 'John Doe')"))
    
    # Verify old schema lacks columns
    insp = inspect(test_engine)
    cols = {col["name"] for col in insp.get_columns("watchlist_persons")}
    assert "threat_level" not in cols
    assert "aliases" not in cols
    
    # Run migration first time
    _migrate_add_missing_columns(test_engine)
    
    # Verify columns were added
    insp = inspect(test_engine)
    cols = {col["name"] for col in insp.get_columns("watchlist_persons")}
    assert "threat_level" in cols
    assert "aliases" in cols
    assert "category" in cols
    assert "last_known_location" in cols
    assert "last_seen_at" in cols
    assert "last_seen_camera_id" in cols
    
    # Ensure data is still there
    with test_engine.connect() as conn:
        row = conn.execute(text("SELECT id, name, threat_level FROM watchlist_persons WHERE id='test_1'")).fetchone()
        assert row is not None
        assert row[0] == "test_1"
        assert row[1] == "John Doe"
        # SQLite DEFAULT doesn't backfill automatically for existing rows like Postgres does, so it's None.
    
    # Run migration second time to prove idempotency
    _migrate_add_missing_columns(test_engine)
    
    # Should not crash, columns should still exist
    insp = inspect(test_engine)
    cols = {col["name"] for col in insp.get_columns("watchlist_persons")}
    assert "threat_level" in cols
