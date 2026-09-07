"""
NETRAKSH Edge — Store-and-Forward Sync Client.
Implements offline-first operation: buffers events locally in SQLite,
uploads them in priority order on reconnection.

Key properties:
  - Events are NEVER lost even if backend is unreachable.
  - On reconnect: events are synced in (severity DESC, sequence_number ASC)
    order (architecture v4 §10) — a HIGH-severity event queued behind older
    LOW-severity ones syncs first once bandwidth returns. This does NOT
    affect hash-chain integrity: the chain (edge/evidence/packager.py) is
    a strictly sequential, append-only local ledger tied together by each
    record's embedded `previous_hash`, verified independently of arrival
    order at the backend — chain order and network delivery order are two
    different things, and only the former needs to be strictly sequential.
  - SIMULATE_OFFLINE=true env var forces offline mode for demo.
  - Batch size is configurable (SYNC_BATCH_SIZE env var).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Optional

import httpx

from shared.schemas import EvidencePackage, EventCreateRequest

logger = logging.getLogger(__name__)

_QUEUE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_number INTEGER NOT NULL UNIQUE,
    event_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,
    error TEXT,
    severity_rank INTEGER NOT NULL DEFAULT 0
);
"""

# Split from table creation: the priority index references severity_rank,
# which must exist BEFORE this runs — for a pre-v4 database, that column is
# added by _migrate_add_severity_rank_if_missing() between the table script
# and this one, not before it (CREATE TABLE IF NOT EXISTS is a no-op against
# an existing table, so the column would otherwise not exist yet here).
_QUEUE_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_queue_status ON sync_queue(status, sequence_number);
CREATE INDEX IF NOT EXISTS idx_queue_priority ON sync_queue(status, severity_rank, sequence_number);
"""

# HIGH syncs before MEDIUM before LOW; an unset/unrecognized severity sorts
# last of all — hand-picked ordering, not itself a calibrated value (there's
# nothing to calibrate here, it's a strict ranking, not a threshold).
_SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def severity_rank(severity) -> int:
    """Maps a Severity enum, its string value, or None to a sortable rank.
    Unrecognized/missing severity ranks below every known level (0)."""
    if severity is None:
        return 0
    key = severity.value if hasattr(severity, "value") else str(severity)
    return _SEVERITY_RANK.get(key, 0)


class SyncClient:
    """
    Edge-side sync client.
    Handles offline buffering and ordered reconnect upload.
    """

    def __init__(
        self,
        edge_device_id: str,
        backend_url: str,
        db_path: str,
        auth_token: str,
        batch_size: int = 50,
        retry_interval_seconds: float = 30.0,
        ca_cert_path: Optional[str] = None,
        client_cert_path: Optional[str] = None,
        client_key_path: Optional[str] = None,
    ):
        self.edge_device_id = edge_device_id
        self.backend_url = backend_url.rstrip("/")
        self.db_path = db_path
        self.auth_token = auth_token
        self.batch_size = int(os.environ.get("SYNC_BATCH_SIZE", str(batch_size)))
        self.retry_interval = float(os.environ.get("SYNC_INTERVAL_SECONDS", str(retry_interval_seconds)))
        self.simulate_offline = os.environ.get("SIMULATE_OFFLINE", "").lower() == "true"
        self._ca_cert = ca_cert_path
        self._client_cert = (client_cert_path, client_key_path) if client_cert_path else None

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()
        self._is_online = False

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(_QUEUE_TABLE_SCHEMA)
            self._migrate_add_severity_rank_if_missing(conn)
            conn.executescript(_QUEUE_INDEX_SCHEMA)

    @staticmethod
    def _migrate_add_severity_rank_if_missing(conn: sqlite3.Connection) -> None:
        """
        A sync_queue.db created before architecture v4 §10 won't have the
        severity_rank column — CREATE TABLE IF NOT EXISTS is a no-op against
        an existing table, so this ALTER TABLE guard is what actually adds
        it to a pre-existing database rather than silently failing to order
        by a column that doesn't exist there.
        """
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sync_queue)").fetchall()]
        if "severity_rank" not in cols:
            logger.info("[Sync] Migrating sync_queue: adding severity_rank column")
            conn.execute("ALTER TABLE sync_queue ADD COLUMN severity_rank INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def enqueue(self, package: EvidencePackage, sequence_number: int) -> None:
        """Add a packaged event to the local outbox (thread-safe)."""
        request = EventCreateRequest(
            evidence_package=package,
            edge_device_id=self.edge_device_id,
            sequence_number=sequence_number,
        )
        payload = request.model_dump_json()
        rank = severity_rank(package.severity)
        with self._get_conn() as conn:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO sync_queue
                       (sequence_number, event_id, payload_json, queued_at, status, severity_rank)
                       VALUES (?,?,?,?,?,?)""",
                    (sequence_number, package.event_id, payload, datetime.utcnow().isoformat(), "QUEUED", rank),
                )
            except Exception as exc:
                logger.error(f"[Sync] Enqueue failed for seq={sequence_number}: {exc}")

        logger.debug(f"[Sync] Enqueued event {package.event_id} (seq={sequence_number}, severity_rank={rank})")

    def get_queue_depth(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status='QUEUED'").fetchone()
        return row[0] if row else 0

    def sync_once(self) -> dict:
        """
        Attempt one sync cycle: fetch pending, upload in order.
        Returns a status dict.
        """
        if self.simulate_offline:
            logger.info("[Sync] SIMULATE_OFFLINE=true — skipping upload")
            return {"status": "simulated_offline", "queued": self.get_queue_depth()}

        pending = self._fetch_pending()
        if not pending:
            return {"status": "nothing_to_sync", "queued": 0}

        logger.info(f"[Sync] Uploading {len(pending)} queued events to {self.backend_url}")
        successes = 0
        failures = 0

        for row_id, seq_num, event_id, payload_json in pending:
            success, error = self._upload(payload_json, seq_num)
            self._mark(row_id, success, error)
            if success:
                successes += 1
            else:
                failures += 1
                # Stop batch on first failure — unchanged behavior, now
                # applied to the priority-ordered result set: if the
                # highest-priority pending event fails, lower-priority ones
                # behind it in this batch are retried next cycle rather than
                # skipped ahead of. This is a deliberately conservative,
                # inherited tradeoff, not something this change re-decided.
                logger.warning(f"[Sync] Upload failed at seq={seq_num} — stopping batch")
                break

        self._is_online = failures == 0
        return {
            "status": "synced" if failures == 0 else "partial",
            "uploaded": successes,
            "failed": failures,
            "remaining": self.get_queue_depth(),
        }

    def run_sync_loop(self) -> None:
        """Background sync loop — runs indefinitely."""
        logger.info(f"[Sync] Background sync loop started (interval={self.retry_interval}s)")
        while True:
            try:
                result = self.sync_once()
                if result.get("uploaded", 0) > 0:
                    logger.info(f"[Sync] Result: {result}")
            except Exception as exc:
                logger.error(f"[Sync] Unexpected error in sync loop: {exc}")
            time.sleep(self.retry_interval)

    def _fetch_pending(self) -> list:
        """
        Priority-ordered (architecture v4 §10): severity_rank DESC first, so
        a HIGH-severity event queued behind older LOW-severity ones syncs
        first once bandwidth returns; sequence_number ASC breaks ties within
        the same severity, preserving FIFO order among equal-priority events.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id, sequence_number, event_id, payload_json
                   FROM sync_queue
                   WHERE status='QUEUED'
                   ORDER BY severity_rank DESC, sequence_number ASC
                   LIMIT ?""",
                (self.batch_size,),
            ).fetchall()
        return rows

    def _upload(self, payload_json: str, seq_num: int) -> tuple[bool, Optional[str]]:
        """Upload a single event to the backend. Returns (success, error_message)."""
        try:
            verify: object = self._ca_cert or True
            cert = self._client_cert
            headers = {"Content-Type": "application/json"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
            with httpx.Client(verify=verify, cert=cert, timeout=30.0) as client:
                response = client.post(
                    f"{self.backend_url}/events",
                    content=payload_json,
                    headers=headers,
                )
            if response.status_code in (200, 201):
                return True, None
            else:
                return False, f"HTTP {response.status_code}: {response.text[:200]}"
        except httpx.ConnectError as exc:
            return False, f"Connection refused — backend may be offline: {exc}"
        except Exception as exc:
            return False, str(exc)

    def _mark(self, row_id: int, success: bool, error: Optional[str]) -> None:
        status = "SYNCED" if success else "QUEUED"  # Keep QUEUED so it retries
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE sync_queue
                   SET status=?, attempts=attempts+1, last_attempt=?, error=?
                   WHERE id=?""",
                (status, datetime.utcnow().isoformat(), error, row_id),
            )

    @property
    def is_online(self) -> bool:
        return self._is_online and not self.simulate_offline

    def set_simulate_offline(self, value: bool) -> None:
        """Allow demo script to toggle offline mode at runtime."""
        self.simulate_offline = value
        logger.info(f"[Sync] simulate_offline set to {value}")
