import pytest
from sqlalchemy import create_engine, text, inspect
from backend.models.orm import Base, Event
from backend.database.session import _migrate_add_missing_columns

def test_event_comprehensive_schema_migration():
    engine = create_engine("sqlite:///:memory:")
    
    # Simulate old schema by creating tables with only base columns
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE cameras (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(128)
            )
        """))
        conn.execute(text("""
            CREATE TABLE events (
                id VARCHAR(36) PRIMARY KEY,
                camera_id VARCHAR(36) NOT NULL,
                timestamp DATETIME NOT NULL,
                detection_class VARCHAR(32) NOT NULL,
                confidence FLOAT NOT NULL,
                scene_condition VARCHAR(32) NOT NULL,
                camera_health_state VARCHAR(16) NOT NULL,
                decision_state VARCHAR(16) NOT NULL
            )
        """))
    
    # Verify columns are missing
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("events")}
    assert "storage_provider" not in columns
    assert "appearance_similarity" not in columns
    assert "bbox_x" not in columns
    
    # Run migration
    import backend.database.session as session_module
    session_module.engine = engine
    _migrate_add_missing_columns()
    
    # Verify migration creates all required columns deterministically
    inspector = inspect(engine)
    new_columns = {col["name"] for col in inspector.get_columns("events")}
    
    expected_new_cols = [
        "vehicle_subtype", "face_match_person_id", "face_match_person_name", 
        "face_match_confidence", "storage_provider", "object_key", 
        "storage_status", "content_hash", "content_size", "uploaded_at", 
        "storage_version_id", "failure_reason", "corroboration_score", 
        "corroborated_by_event_id", "corroboration_distance_m", 
        "corroboration_delta_t_s", "corroboration_t_expected_s", 
        "corroboration_sigma_s", "corroborating_camera_id", 
        "corroboration_status", "appearance_similarity", "representation_type", 
        "bbox_x", "bbox_y", "bbox_w", "bbox_h", "score_d", "score_t", 
        "score_s", "score_h", "score_r", "edge_device_id", "sequence_number", 
        "created_at", "synced_from_edge"
    ]
    
    for col in expected_new_cols:
        assert col in new_columns, f"Expected {col} to be added by migration"
        
    # Test that existing event schema remains compatible and double migration is idempotent
    _migrate_add_missing_columns()
    
def test_event_orm_matches_migration():
    # If the ORM has the fields, they should be accessible
    event = Event(
        id="123", 
        camera_id="cam-1", 
        storage_provider="gcp", 
        object_key="test",
        appearance_similarity=0.95,
        bbox_x=0.1
    )
    assert event.storage_provider == "gcp"
    assert event.object_key == "test"
    assert event.appearance_similarity == 0.95
    assert event.bbox_x == 0.1

def test_event_migration_duplicate_column_regression():
    """
    Phase 7.4.2G Regression Test:
    Ensures that if an older schema already contains corroboration_score,
    the comprehensive migration block does NOT attempt to add it again,
    which would otherwise cause 'sqlite3.OperationalError: duplicate column name'.
    """
    engine = create_engine("sqlite:///:memory:")
    
    # Simulate a partially-migrated schema that ALREADY has corroboration_score
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE cameras (
                id VARCHAR(36) PRIMARY KEY
            )
        """))
        conn.execute(text("""
            CREATE TABLE events (
                id VARCHAR(36) PRIMARY KEY,
                camera_id VARCHAR(36) NOT NULL,
                timestamp DATETIME NOT NULL,
                detection_class VARCHAR(32) NOT NULL,
                confidence FLOAT NOT NULL,
                scene_condition VARCHAR(32) NOT NULL,
                camera_health_state VARCHAR(16) NOT NULL,
                decision_state VARCHAR(16) NOT NULL,
                corroboration_score FLOAT
            )
        """))
    
    import backend.database.session as session_module
    session_module.engine = engine
    
    # This must complete WITHOUT OperationalError
    _migrate_add_missing_columns()
    
    # Verify corroboration_score exists and genuinely missing columns were added
    inspector = inspect(engine)
    new_columns = {col["name"] for col in inspector.get_columns("events")}
    
    assert "corroboration_score" in new_columns
    assert "vehicle_subtype" in new_columns
    assert "appearance_similarity" in new_columns

