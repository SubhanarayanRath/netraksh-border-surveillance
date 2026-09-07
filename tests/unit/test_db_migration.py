"""
NETRAKSH — Unit tests for backend/database/session.py's migration guard
(architecture v4 §10 — adding Camera.evidence_key_wrapped to a pre-existing
cameras table that Base.metadata.create_all() cannot alter).
"""
import sqlite3
from pathlib import Path

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


def _make_legacy_engine_with_alerts(db_path: str):
    """cameras + events + alerts tables matching the schema from before
    the cross-camera-corroboration escalation boost
    (backend/services/escalation.py) — no escalated_via_corroboration
    column on alerts."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE cameras (id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL);
        CREATE TABLE events (id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, timestamp TEXT NOT NULL);
        CREATE TABLE alerts (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            crosses_jurisdiction_boundary BOOLEAN,
            command_id_issuing TEXT NOT NULL,
            blockchain_status TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO alerts (id, event_id, severity, crosses_jurisdiction_boundary, "
        "command_id_issuing, blockchain_status) "
        "VALUES ('alert-legacy', 'ev-legacy', 'HIGH', 0, 'COMMAND_A', 'PENDING')"
    )
    conn.commit()
    conn.close()
    return create_engine(f"sqlite:///{db_path}")


class TestMigrationAddsEscalationCorroborationColumn:
    def test_adds_escalated_via_corroboration_to_legacy_alerts_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_alerts.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        cols = {c["name"] for c in inspect(engine).get_columns("alerts")}
        assert "escalated_via_corroboration" in cols

    def test_preserves_existing_alert_rows(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_alerts.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, severity FROM alerts WHERE id = 'alert-legacy'")).fetchone()
        assert row is not None
        assert row[1] == "HIGH"

    def test_idempotent_on_an_already_migrated_alerts_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_alerts.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()
        _migrate_add_missing_columns()  # must not raise (no duplicate ALTER TABLE)

        cols = [c["name"] for c in inspect(engine).get_columns("alerts")]
        assert cols.count("escalated_via_corroboration") == 1


class TestMigrationSqlIsPostgresCompatible:
    """
    Real production incident, not a hypothetical: the first version of the
    escalated_via_corroboration migration used
    "BOOLEAN DEFAULT 0" — SQLite accepts this silently (it has no real
    BOOLEAN type; 0/1 are just INTEGER), which is exactly why every test
    above passed even with the bug in place, and why this project's local
    SQLite-only testing never caught it. The real Postgres deployment
    (render.yaml) enforces BOOLEAN's real type and crashed on startup:
    "column ... is of type boolean but default expression is of type
    integer" — a real production outage, confirmed from the live Render
    deploy logs. This project has no Postgres available in this dev
    environment to test against directly (same class of honest limitation
    as the WSL2/Docker gap documented for blockchain), so this is a direct,
    cheap regression guard against the exact broken pattern recurring:
    every BOOLEAN column this migration guard adds must use a real boolean
    literal (TRUE/FALSE), never an integer literal, which is valid in both
    SQLite and Postgres.
    """

    def test_no_boolean_column_migration_uses_an_integer_default_literal(self):
        session_py = Path(__file__).resolve().parent.parent.parent / "backend" / "database" / "session.py"
        source = session_py.read_text()
        for line in source.splitlines():
            if "BOOLEAN" in line.upper() and "ALTER TABLE" in line.upper():
                assert "DEFAULT 0" not in line.upper() and "DEFAULT 1" not in line.upper(), (
                    f"Found an integer literal DEFAULT on a BOOLEAN column migration — this is the "
                    f"exact real bug that crashed the Postgres deployment. Use DEFAULT FALSE/TRUE "
                    f"instead: {line.strip()}"
                )


class TestMigrationAddsVehicleSubtypeColumn:
    """SIH PS 26187 vehicle classification (backend/api/events.py,
    edge/detection/detector.py) — same guard pattern, applied to the
    events table's new vehicle_subtype column."""

    def test_adds_vehicle_subtype_to_legacy_events_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_events.db")
        engine = _make_legacy_engine_with_events(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        cols = {c["name"] for c in inspect(engine).get_columns("events")}
        assert "vehicle_subtype" in cols

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
        assert cols.count("vehicle_subtype") == 1


class TestMigrationAddsFaceMatchColumns:
    """SIH PS 26187 watchlist face recognition (backend/api/watchlist.py,
    edge/detection/face_recognition.py) — same guard pattern, applied to
    the events table's new face_match_* columns. WatchlistPerson/
    WatchlistFaceImage themselves are brand-new tables, already handled
    by Base.metadata.create_all() -- see TestWatchlistTablesRealSchema
    below."""

    def test_adds_face_match_columns_to_legacy_events_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_events.db")
        engine = _make_legacy_engine_with_events(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        cols = {c["name"] for c in inspect(engine).get_columns("events")}
        assert "face_match_person_id" in cols
        assert "face_match_person_name" in cols
        assert "face_match_confidence" in cols

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
        _migrate_add_missing_columns()

        cols = [c["name"] for c in inspect(engine).get_columns("events")]
        assert cols.count("face_match_person_id") == 1


class TestWatchlistTablesRealSchema:
    """WatchlistPerson/WatchlistFaceImage are brand-new tables -- handled
    by Base.metadata.create_all() (init_db()), not the ALTER-TABLE guard
    above. Real, end-to-end verified: create a person + image, query them
    back, delete the person and confirm the cascade removes the image too."""

    def _fresh_engine(self, tmp_path):
        from sqlalchemy import create_engine
        from backend.models.orm import Base
        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        Base.metadata.create_all(bind=engine)
        return engine

    def test_watchlist_tables_are_created(self, tmp_path):
        from sqlalchemy import inspect as sa_inspect
        engine = self._fresh_engine(tmp_path)
        tables = sa_inspect(engine).get_table_names()
        assert "watchlist_persons" in tables
        assert "watchlist_face_images" in tables

    def test_real_person_and_image_round_trip(self, tmp_path):
        from sqlalchemy.orm import sessionmaker
        from backend.models.orm import WatchlistFaceImage, WatchlistPerson

        engine = self._fresh_engine(tmp_path)
        Session = sessionmaker(bind=engine)
        db = Session()

        person = WatchlistPerson(name="Alice", notes="test enrollment")
        db.add(person)
        db.flush()
        db.add(WatchlistFaceImage(person_id=person.id, image_base64="ZmFrZQ=="))
        db.commit()

        fetched = db.query(WatchlistPerson).filter(WatchlistPerson.name == "Alice").first()
        assert fetched is not None
        assert len(fetched.face_images) == 1
        assert fetched.face_images[0].image_base64 == "ZmFrZQ=="
        assert fetched.is_active is True  # real default

    def test_deleting_a_person_cascades_to_their_face_images(self, tmp_path):
        from sqlalchemy.orm import sessionmaker
        from backend.models.orm import WatchlistFaceImage, WatchlistPerson

        engine = self._fresh_engine(tmp_path)
        Session = sessionmaker(bind=engine)
        db = Session()

        person = WatchlistPerson(name="Bob")
        db.add(person)
        db.flush()
        db.add(WatchlistFaceImage(person_id=person.id, image_base64="ZmFrZQ=="))
        db.commit()

        db.delete(person)
        db.commit()

        assert db.query(WatchlistFaceImage).count() == 0


class TestMigrationAddsAlertCloseColumns:
    """SIH PS 26187 audit finding: EventState.CLOSED was defined but never
    actually set anywhere. Same guard pattern, applied to the alerts
    table's new close-action columns."""

    def test_adds_close_columns_to_legacy_alerts_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_alerts2.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        cols = {c["name"] for c in inspect(engine).get_columns("alerts")}
        assert "closed_at" in cols
        assert "closed_by" in cols
        assert "resolution_notes" in cols
        assert "lifecycle_state" in cols

    def test_legacy_rows_get_a_real_alerted_backfill_default(self, tmp_path, monkeypatch):
        """A legacy alert row predates lifecycle_state entirely, but it
        really was, at minimum, ALERTED (that's how an Alert row comes to
        exist) -- a real, honest backfill, not an arbitrary placeholder."""
        db_path = str(tmp_path / "legacy_alerts2.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT lifecycle_state FROM alerts WHERE id = 'alert-legacy'")).fetchone()
        assert row[0] == "ALERTED"

    def test_preserves_existing_alert_rows(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_alerts2.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()

        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, severity FROM alerts WHERE id = 'alert-legacy'")).fetchone()
        assert row is not None
        assert row[1] == "HIGH"

    def test_idempotent_on_an_already_migrated_alerts_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "legacy_alerts2.db")
        engine = _make_legacy_engine_with_alerts(db_path)
        monkeypatch.setattr("backend.database.session.engine", engine)

        _migrate_add_missing_columns()
        _migrate_add_missing_columns()

        cols = [c["name"] for c in inspect(engine).get_columns("alerts")]
        assert cols.count("closed_at") == 1
