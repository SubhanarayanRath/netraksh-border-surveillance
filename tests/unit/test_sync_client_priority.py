"""
NETRAKSH — Unit tests for the priority-ordered offline sync queue
(architecture v4 §10, edge/sync/sync_client.py).
"""
import os
import sqlite3
from datetime import datetime

import pytest

from edge.sync.sync_client import SyncClient, severity_rank
from shared.constants import Severity
from shared.schemas import EvidencePackage


def _package(event_id="evt-1", severity=None) -> EvidencePackage:
    return EvidencePackage(
        event_id=event_id,
        camera_id="cam-1",
        timestamp=datetime.utcnow(),
        zone_id="zone-1",
        detection_class="person",
        confidence=0.8,
        scene_condition="CLEAR_DAY",
        camera_health_state="OK",
        decision_state="DETECTED",
        severity=severity,
    )


def _client(tmp_path, name="sync.db") -> SyncClient:
    return SyncClient(
        edge_device_id="edge-1",
        backend_url="http://localhost:9999",
        db_path=os.path.join(str(tmp_path), name),
        auth_token="",
    )


class TestSeverityRank:
    def test_high_ranks_above_medium_above_low(self):
        assert severity_rank(Severity.HIGH) > severity_rank(Severity.MEDIUM) > severity_rank(Severity.LOW)

    def test_accepts_plain_string(self):
        assert severity_rank("HIGH") == severity_rank(Severity.HIGH)

    def test_none_ranks_below_every_known_level(self):
        assert severity_rank(None) < severity_rank(Severity.LOW)

    def test_unrecognized_string_ranks_like_none(self):
        assert severity_rank("NOT_A_REAL_SEVERITY") == severity_rank(None)


class TestFetchOrdering:
    def test_high_severity_syncs_before_older_low_severity(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-low", severity=Severity.LOW), sequence_number=1)
        client.enqueue(_package("evt-high", severity=Severity.HIGH), sequence_number=2)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-high", "evt-low"]

    def test_same_severity_breaks_tie_by_sequence_number(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-a", severity=Severity.MEDIUM), sequence_number=5)
        client.enqueue(_package("evt-b", severity=Severity.MEDIUM), sequence_number=3)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-b", "evt-a"]  # lower sequence_number first

    def test_missing_severity_sorts_last(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-none", severity=None), sequence_number=1)
        client.enqueue(_package("evt-low", severity=Severity.LOW), sequence_number=2)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-low", "evt-none"]

    def test_three_tier_ordering_end_to_end(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-low", severity=Severity.LOW), sequence_number=1)
        client.enqueue(_package("evt-high", severity=Severity.HIGH), sequence_number=2)
        client.enqueue(_package("evt-medium", severity=Severity.MEDIUM), sequence_number=3)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-high", "evt-medium", "evt-low"]


class TestMigration:
    def test_pre_v4_database_gets_severity_rank_column_added(self, tmp_path):
        """A sync_queue.db created before this change has no severity_rank
        column — instantiating SyncClient against it must migrate it in
        place, not fail or silently ignore priority ordering."""
        db_path = os.path.join(str(tmp_path), "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE sync_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence_number INTEGER NOT NULL UNIQUE,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'QUEUED',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt TEXT,
                error TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO sync_queue (sequence_number, event_id, payload_json, queued_at, status) "
            "VALUES (1, 'legacy-evt', '{}', ?, 'QUEUED')",
            (datetime.utcnow().isoformat(),),
        )
        conn.commit()
        conn.close()

        client = SyncClient(
            edge_device_id="edge-1", backend_url="http://localhost:9999",
            db_path=db_path, auth_token="",
        )
        cols = [row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(sync_queue)").fetchall()]
        assert "severity_rank" in cols

        # The pre-existing row must still be queryable via the new ordering.
        pending = client._fetch_pending()
        assert len(pending) == 1
        assert pending[0][2] == "legacy-evt"

    def test_migration_is_idempotent(self, tmp_path):
        """Instantiating SyncClient twice against the same db must not fail
        (ALTER TABLE ADD COLUMN on an already-migrated db would raise)."""
        db_path = os.path.join(str(tmp_path), "sync.db")
        SyncClient(edge_device_id="edge-1", backend_url="http://localhost:9999", db_path=db_path, auth_token="")
        SyncClient(edge_device_id="edge-1", backend_url="http://localhost:9999", db_path=db_path, auth_token="")
        # No exception raised — that's the test.


class TestQueueDepthUnaffected:
    def test_queue_depth_counts_regardless_of_severity(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-1", severity=Severity.HIGH), sequence_number=1)
        client.enqueue(_package("evt-2", severity=Severity.LOW), sequence_number=2)
        assert client.get_queue_depth() == 2
