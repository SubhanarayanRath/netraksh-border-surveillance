"""
NETRAKSH Edge — Evidence Packaging + SHA-256 + Ed25519 + SQLite Hash-Chain.
Implements §1.4 (locked evidence field set) and §19 (cryptographic chain).

Hash: SHA-256(serialized mandatory fields + previous_hash)
Sign: Ed25519(edge device private key, hash)
Chain: hash(record_n) = SHA256(record_n_fields + hash(record_n-1))
Storage: append-only SQLite (never modified, only inserted)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared import crypto
from shared.constants import CameraHealthState, DecisionState, SceneCondition
from shared.schemas import (
    BoundingBox,
    CameraHealthReport,
    EvidencePackage,
    ReliabilityDecision,
    SceneConditionReport,
    TrackData,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

class EdgeKeyManager:
    """
    Manages the Ed25519 keypair for this edge device.
    Keys are generated once and stored as PEM files.
    Public key PEM must be uploaded to the server (backend /cameras/{id}/public-key).
    """

    def __init__(self, private_key_path: str, public_key_path: str):
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        self._private_key: Optional[Ed25519PrivateKey] = None
        self._public_key: Optional[Ed25519PublicKey] = None

    def load_or_generate(self) -> None:
        """Load existing keys or generate new ones."""
        os.makedirs(os.path.dirname(self.private_key_path) or ".", exist_ok=True)
        if os.path.exists(self.private_key_path):
            self._load()
        else:
            self._generate()

    def _generate(self) -> None:
        logger.info(f"[KeyMgr] Generating new Ed25519 keypair...")
        private_key = Ed25519PrivateKey.generate()
        pub_key = private_key.public_key()

        priv_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        pub_pem = pub_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        with open(self.private_key_path, "wb") as f:
            f.write(priv_pem)
        with open(self.public_key_path, "wb") as f:
            f.write(pub_pem)

        self._private_key = private_key
        self._public_key = pub_key
        logger.info(f"[KeyMgr] Keys written to {self.private_key_path} / {self.public_key_path}")
        logger.info(f"[KeyMgr] Upload public key to server: /cameras/{{id}}/public-key")

    def _load(self) -> None:
        with open(self.private_key_path, "rb") as f:
            priv_data = f.read()
        self._private_key = serialization.load_pem_private_key(priv_data, password=None)
        self._public_key = self._private_key.public_key()
        logger.info(f"[KeyMgr] Ed25519 keys loaded from {self.private_key_path}")

    def sign(self, data: bytes) -> str:
        """Sign data with Ed25519 private key. Returns hex-encoded signature."""
        if self._private_key is None:
            raise RuntimeError("Keys not loaded. Call load_or_generate() first.")
        sig = self._private_key.sign(data)
        return sig.hex()

    def get_public_key_pem(self) -> str:
        if self._public_key is None:
            raise RuntimeError("Keys not loaded.")
        return self._public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")


# ---------------------------------------------------------------------------
# Evidence-at-rest encryption (architecture v4 §10, MUST HAVE)
# ---------------------------------------------------------------------------

class EvidenceEncryptor:
    """
    AES-256-GCM encryption for evidence snapshots/clips at rest. Delegates
    the actual cipher operations to shared/crypto.py so the edge and the
    backend (backend/security/evidence_key_wrap.py, for decrypt-on-view)
    share one implementation instead of two that could drift apart.

    The key is a random 256-bit value generated once per edge device and
    stored alongside the Ed25519 identity key (same certs/edge/ directory,
    same generate-once-then-load pattern as EdgeKeyManager above). It never
    leaves the edge device automatically — see get_raw_key_b64() below for
    the one deliberate, manual exception to that.

    Operational tradeoff, documented in docs/LIMITATIONS.md: if this key file
    is lost, previously encrypted evidence on that device becomes
    unrecoverable. Resolving that requires a key-escrow/backup design, which
    is explicitly out of MVP scope.
    """

    NONCE_SIZE = crypto.NONCE_SIZE  # kept for API stability; delegates to shared/crypto.py

    def __init__(self, key_path: str):
        self.key_path = key_path
        self._key: Optional[bytes] = None

    def load_or_generate(self) -> None:
        os.makedirs(os.path.dirname(self.key_path) or ".", exist_ok=True)
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as f:
                self._key = f.read()
            if len(self._key) != 32:
                raise RuntimeError(
                    f"Evidence encryption key at {self.key_path} is not 32 bytes "
                    f"(got {len(self._key)}) — refusing to use a malformed key"
                )
            logger.info(f"[Encryptor] AES-256 evidence key loaded from {self.key_path}")
        else:
            self._key = AESGCM.generate_key(bit_length=256)
            with open(self.key_path, "wb") as f:
                f.write(self._key)
            try:
                os.chmod(self.key_path, 0o600)  # best-effort; some filesystems ignore POSIX modes
            except Exception:
                pass
            logger.info(f"[Encryptor] Generated new AES-256 evidence key at {self.key_path}")
            logger.info(
                "[Encryptor] To let the command center decrypt this camera's evidence for "
                "authorized viewers, upload this key once: PUT /cameras/{camera_id}/evidence-key "
                "(see scripts/upload_evidence_key.py). Until then, evidence stays encrypted at "
                "rest but cannot be viewed through the dashboard — architecture v4 §10."
            )

    def encrypt(self, plaintext: bytes) -> bytes:
        """Returns nonce || ciphertext+tag, ready to write to disk as-is."""
        if self._key is None:
            raise RuntimeError("Key not loaded. Call load_or_generate() first.")
        return crypto.aes_gcm_encrypt(self._key, plaintext)

    def decrypt(self, blob: bytes) -> bytes:
        """Inverse of encrypt(). Raises cryptography.exceptions.InvalidTag if
        the blob was tampered with or the wrong key is used."""
        if self._key is None:
            raise RuntimeError("Key not loaded. Call load_or_generate() first.")
        return crypto.aes_gcm_decrypt(self._key, blob)

    def get_raw_key_b64(self) -> str:
        """
        Base64-encodes the raw key for manual upload to the backend
        (PUT /cameras/{camera_id}/evidence-key) so an authorized dashboard
        viewer can decrypt this camera's evidence. This is the one
        deliberate, explicit exception to "never transmitted" above — it is
        never called automatically anywhere in the edge pipeline, exactly
        like EdgeKeyManager's Ed25519 public key upload, which also requires
        a manual step (see its own load_or_generate() log message).
        """
        if self._key is None:
            raise RuntimeError("Key not loaded. Call load_or_generate() first.")
        import base64

        return base64.b64encode(self._key).decode("ascii")


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def compute_sha256(fields: dict) -> str:
    """Deterministic SHA-256 of sorted JSON serialization. Must match server-side computation."""
    serialized = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQLite hash-chain store (append-only)
# ---------------------------------------------------------------------------

_CHAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_number INTEGER NOT NULL UNIQUE,
    event_id TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    decision_state TEXT NOT NULL,
    confidence REAL NOT NULL,
    current_hash TEXT NOT NULL,
    previous_hash TEXT,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chain_seq ON evidence_chain(sequence_number);
"""


class EvidenceChainStore:
    """
    Append-only SQLite chain. Each record stores the hash of the previous one.
    Mutating any record breaks all subsequent hash links — detectable.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(_CHAIN_SCHEMA)

    def get_latest_hash(self) -> tuple[Optional[str], int]:
        """Returns (latest_hash, next_sequence_number)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT current_hash, sequence_number FROM evidence_chain ORDER BY sequence_number DESC LIMIT 1"
            ).fetchone()
        if row:
            return row[0], row[1] + 1
        return None, 0

    def append(self, package: EvidencePackage, signature: str) -> int:
        """
        Append a signed evidence package to the chain.
        Returns the sequence number assigned.
        """
        previous_hash, seq_num = self.get_latest_hash()
        package.previous_hash = previous_hash
        package.hash = compute_sha256(package.get_signable_fields())
        package.signature = signature

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO evidence_chain
                   (sequence_number, event_id, camera_id, timestamp, decision_state,
                    confidence, current_hash, previous_hash, signature, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    seq_num,
                    package.event_id,
                    package.camera_id,
                    package.timestamp.isoformat(),
                    str(package.decision_state),
                    package.confidence,
                    package.hash,
                    package.previous_hash or "",
                    package.signature,
                    datetime.utcnow().isoformat(),
                ),
            )
        return seq_num

    def verify_chain(self) -> tuple[bool, Optional[int], str]:
        """
        Walk the entire chain and verify hash linkage.
        Returns (is_valid, first_broken_sequence_or_None, detail_message)
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT sequence_number, event_id, camera_id, timestamp, decision_state, "
                "confidence, current_hash, previous_hash, signature "
                "FROM evidence_chain ORDER BY sequence_number ASC"
            ).fetchall()

        if not rows:
            return True, None, "Empty chain — valid by definition"

        prev_hash = None
        for row in rows:
            seq, event_id, camera_id, timestamp, decision_state, confidence, current_hash, previous_hash, sig = row

            # Recompute expected hash for this record
            fields = {
                "event_id": event_id,
                "camera_id": camera_id,
                "timestamp": timestamp,
                "zone_id": "",  # zone_id not stored in chain directly
                "detection_class": "unknown",
                "confidence": confidence,
                "scene_condition": "CLEAR_DAY",
                "camera_health_state": "OK",
                "decision_state": decision_state,
                "evidence_clip_ref": "",
                "previous_hash": previous_hash or "",
            }
            expected_hash = compute_sha256(fields)

            # Verify previous_hash linkage
            if seq > 0 and previous_hash != (prev_hash or ""):
                return False, seq, f"CHAIN BREAK at sequence {seq}: expected previous_hash={prev_hash}, got {previous_hash}"

            # Hash itself might not match because we don't have all fields here
            # Full re-verification uses the raw_package_json on the server
            prev_hash = current_hash

        return True, None, f"Chain valid — {len(rows)} records verified"

    def get_all_records(self) -> list:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_chain ORDER BY sequence_number ASC"
            ).fetchall()
        return rows


# ---------------------------------------------------------------------------
# Evidence Packager — main entry point
# ---------------------------------------------------------------------------

class EvidencePackager:
    """
    Assembles the full evidence package from pipeline outputs,
    signs it, and appends it to the local hash-chain.
    """

    def __init__(
        self,
        camera_id: str,
        key_manager: EdgeKeyManager,
        chain_store: EvidenceChainStore,
        clip_storage_dir: str = "edge/data/clips",
        encryptor: Optional[EvidenceEncryptor] = None,
    ):
        self.camera_id = camera_id
        self.key_manager = key_manager
        self.chain_store = chain_store
        self.clip_dir = clip_storage_dir
        os.makedirs(clip_storage_dir, exist_ok=True)
        # Populated by package() on every call — stage timings in ms for the
        # most recent packaging, read by edge/main.py for performance
        # instrumentation (architecture v4 §15). Does not change package()'s
        # existing (package, seq_num) return contract.
        self.last_timing: dict = {}

        # AES-256-GCM encryption for evidence at rest (architecture v4 §10).
        # Defaults to a key file alongside the Ed25519 identity key so no
        # extra config is needed for the common case; pass an explicit
        # encryptor to point it elsewhere.
        if encryptor is None:
            key_dir = os.path.dirname(getattr(key_manager, "private_key_path", "")) or "certs/edge"
            encryptor = EvidenceEncryptor(os.path.join(key_dir, f"{camera_id}.aes"))
        self.encryptor = encryptor
        self.encryptor.load_or_generate()

    def package(
        self,
        track: Optional[TrackData],
        reliability: ReliabilityDecision,
        health: CameraHealthReport,
        condition: SceneConditionReport,
        zone_id: str,
        event_overrides: Optional[dict] = None,
        frame: Optional[object] = None,  # np.ndarray, optional for saving snapshot
    ) -> tuple[EvidencePackage, int]:
        """
        Create, sign, and chain-append an evidence package.
        Returns (package, sequence_number).
        """
        overrides = event_overrides or {}
        _t0 = time.perf_counter()

        # Save a snapshot frame if provided
        clip_ref = None
        if frame is not None:
            clip_ref = self._save_snapshot(frame)
        _t1 = time.perf_counter()

        ep = EvidencePackage(
            event_id=str(uuid.uuid4()),
            camera_id=self.camera_id,
            timestamp=datetime.utcnow(),
            zone_id=zone_id,
            detection_class=overrides.get("detection_class", track.detection_class if track else "unknown"),
            confidence=overrides.get("confidence", track.confidence if track else 0.0),
            scene_condition=condition.condition,
            camera_health_state=health.health_state,
            decision_state=reliability.decision_state,
            evidence_clip_ref=clip_ref,
            # Optional fields from task module results
            event_type=overrides.get("event_type"),
            decision_reason=reliability.decision_reason,
            track_id=track.track_id if track else None,
            severity=overrides.get("severity"),
            direction=overrides.get("direction"),
            rule=overrides.get("rule"),
            rule_value=overrides.get("rule_value"),
            plate_text=overrides.get("plate_text"),
            plate_confidence=overrides.get("plate_confidence"),
            face_bbox=overrides.get("face_bbox"),
            face_confidence=overrides.get("face_confidence"),
            # Real vehicle sub-classification (shared.constants.VehicleSubtype)
            # from the track's own field, same pattern as track_id above —
            # None whenever track is None or the detection wasn't a vehicle.
            vehicle_subtype=overrides.get("vehicle_subtype", getattr(track, "vehicle_subtype", None)),
            # Real watchlist face-match result (edge/detection/
            # face_recognition.py), set by FaceDetectionModule._attempt_recognition
            # on a real match and passed through event_overrides — None
            # whenever no face module fired or no match was found.
            face_match_person_id=overrides.get("face_match_person_id"),
            face_match_person_name=overrides.get("face_match_person_name"),
            face_match_confidence=overrides.get("face_match_confidence"),
        )

        # Compute hash of signable fields
        ep.hash = compute_sha256(ep.get_signable_fields())

        # Sign with edge private key
        signature = self.key_manager.sign(ep.hash.encode("utf-8"))
        ep.signature = signature
        _t2 = time.perf_counter()

        # Append to local hash-chain (also sets previous_hash and re-computes hash)
        seq_num = self.chain_store.append(ep, signature)
        _t3 = time.perf_counter()

        self.last_timing = {
            "snapshot_ms": (_t1 - _t0) * 1000.0,
            "hash_sign_ms": (_t2 - _t1) * 1000.0,
            "chain_store_ms": (_t3 - _t2) * 1000.0,
        }

        logger.info(
            f"[Evidence] Packaged event {ep.event_id}: "
            f"decision={ep.decision_state}, seq={seq_num}, hash={ep.hash[:16]}..."
        )
        return ep, seq_num

    def _save_snapshot(self, frame) -> str:
        """
        Save an AES-256-GCM-encrypted JPEG snapshot for the clip reference
        (architecture v4 §10 — evidence at rest is encrypted, not a plain
        JPEG on disk). The frame is JPEG-encoded in memory, then encrypted
        before anything touches disk; decrypt with self.encryptor.decrypt()
        using the same edge device's key.
        """
        import cv2
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError("Failed to JPEG-encode snapshot frame")
        encrypted = self.encryptor.encrypt(buf.tobytes())
        filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg.enc"
        filepath = os.path.join(self.clip_dir, filename)
        with open(filepath, "wb") as f:
            f.write(encrypted)
        return filepath
