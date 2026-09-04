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
