"""
NETRAKSH — Unit tests for backend/database/session.py's migration guard
(architecture v4 §10 — adding Camera.evidence_key_wrapped to a pre-existing
cameras table that Base.metadata.create_all() cannot alter).
"""
import sqlite3

from sqlalchemy import create_engine, inspect, text

from backend.database.session import _migrate_add_missing_columns


def _make_legacy_engine(db_path: str):
    """A cameras table matching the schema from before architecture v4 §10 —
    no evidence_key_wrapped column, exactly like the real, pre-existing
    netraksh.db this migration was written to fix."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE cameras (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            rtsp_url TEXT,
            public_key_pem TEXT,
            owning_command_id TEXT NOT NULL,
            is_active BOOLEAN,
            created_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO cameras (id, name, location, owning_command_id, is_active) "
        "VALUES ('cam-legacy', 'Legacy Cam', 'Sector 1', 'COMMAND_A', 1)"
    )
    conn.commit()
    conn.close()
    return create_engine(f"sqlite:///{db_path}")


class TestMigrationAddsColumn:
    def test_adds_evidence_key_wrapped_to_legacy_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy.db")
        engine = _make_legacy_engine(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        cols = {c["name"] for c in inspect(engine).get_columns("cameras")}
        assert "evidence_key_wrapped" in cols

    def test_preserves_existing_rows(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy.db")
        engine = _make_legacy_engine(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, name FROM cameras WHERE id = 'cam-legacy'")).fetchone()
        assert row is not None
        assert row[1] == "Legacy Cam"

    def test_idempotent_on_an_already_migrated_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy.db")
        engine = _make_legacy_engine(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()
        _migrate_add_missing_columns()  # must not raise (no duplicate ALTER TABLE)

        cols = [c["name"] for c in inspect(engine).get_columns("cameras")]
        assert cols.count("evidence_key_wrapped") == 1

    def test_no_op_when_table_does_not_exist_yet(self, tmp_path, monkeypatch):
        """A brand-new database has no cameras table at all until
        create_all() runs — the migration must not error in that case."""
        db_path = str(tmp_path / "brand_new.db")
        engine = create_engine(f"sqlite:///{db_path}")
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()  # must not raise


def _make_legacy_engine_with_events(db_path: str):
    """cameras + events tables matching the schema from before cross-camera
    corroboration (backend/services/cross_camera.py) — no
    corroboration_score/corroborated_by_event_id/corroboration_distance_m/
    corroboration_delta_t_s columns on events."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE cameras (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            rtsp_url TEXT,
            public_key_pem TEXT,
            evidence_key_wrapped TEXT,
            latitude FLOAT,
            longitude FLOAT,
            owning_command_id TEXT NOT NULL,
            is_active BOOLEAN,
            created_at TEXT
        );
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            camera_id TEXT NOT NULL,
            zone_id TEXT,
            timestamp TEXT NOT NULL,
            detection_class TEXT NOT NULL,
            confidence FLOAT NOT NULL,
            scene_condition TEXT NOT NULL,
            camera_health_state TEXT NOT NULL,
            decision_state TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO events (id, camera_id, timestamp, detection_class, confidence, "
        "scene_condition, camera_health_state, decision_state) "
        "VALUES ('ev-legacy', 'cam-legacy', '2026-01-01T12:00:00', 'person', 0.9, "
        "'CLEAR_DAY', 'OK', 'DETECTED')"
    )
    conn.commit()
    conn.close()
    return create_engine(f"sqlite:///{db_path}")


class TestMigrationAddsCrossCameraColumns:
    def test_adds_corroboration_columns_to_legacy_events_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_events.db")
        engine = _make_legacy_engine_with_events(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        cols = {c["name"] for c in inspect(engine).get_columns("events")}
        assert "corroboration_score" in cols
        assert "corroborated_by_event_id" in cols
        assert "corroboration_distance_m" in cols
        assert "corroboration_delta_t_s" in cols

    def test_preserves_existing_event_rows(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_events.db")
        engine = _make_legacy_engine_with_events(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, camera_id FROM events WHERE id = 'ev-legacy'")).fetchone()
        assert row is not None
        assert row[1] == "cam-legacy"

    def test_idempotent_on_an_already_migrated_events_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_events.db")
        engine = _make_legacy_engine_with_events(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()
        _migrate_add_missing_columns()  # must not raise (no duplicate ALTER TABLE)

        cols = [c["name"] for c in inspect(engine).get_columns("events")]
        assert cols.count("corroboration_score") == 1
