"""
NETRAKSH — Server-side integrity verification service.
Verifies:
  1. SHA-256 hash validity
  2. Ed25519 signature validity
  3. Hash-chain continuity

This is the REAL cryptographic verification — not cosmetic.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from sqlalchemy.orm import Session

from backend.models.orm import EvidenceChain
from shared.schemas import EvidencePackage, VerificationResponse

logger = logging.getLogger(__name__)


def compute_sha256(fields: dict) -> str:
    """Deterministic SHA-256 of a sorted JSON serialization of the fields dict."""
    serialized = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_hash(evidence_package: EvidencePackage) -> bool:
    """Recompute SHA-256 and check against stored hash."""
    if not evidence_package.hash:
        return False
    expected = compute_sha256(evidence_package.get_signable_fields())
    return expected == evidence_package.hash


def verify_signature(evidence_package: EvidencePackage, public_key_pem: Optional[str]) -> bool:
    """Verify Ed25519 signature against the stored hash."""
    if not evidence_package.hash or not evidence_package.signature:
        logger.warning("Missing hash or signature — cannot verify signature")
        return False
    if not public_key_pem:
        logger.warning(f"No public key for camera {evidence_package.camera_id} — signature unverifiable")
        return False  # Cannot verify without public key

    try:
        pub_key_bytes = public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else public_key_pem
        pub_key = serialization.load_pem_public_key(pub_key_bytes)
        sig_bytes = bytes.fromhex(evidence_package.signature)
        hash_bytes = evidence_package.hash.encode("utf-8")
        pub_key.verify(sig_bytes, hash_bytes)  # Ed25519 verify (no separate hash param)
        return True
    except InvalidSignature:
        logger.warning(f"Signature INVALID for event {evidence_package.event_id}")
        return False
    except Exception as exc:
        logger.error(f"Signature verification error for event {evidence_package.event_id}: {exc}")
        return False


def verify_chain_continuity(
    db: Session,
    edge_device_id: str,
    sequence_number: int,
    current_hash: str,
    previous_hash: Optional[str],
) -> bool:
    """
    Verify that this event's previous_hash matches the hash stored for the
    previous sequence number in our server-side chain tracking table.
    """
    if sequence_number == 0:
        # First event in chain — no previous to check
        return True

    prev_chain = (
        db.query(EvidenceChain)
        .filter(
            EvidenceChain.edge_device_id == edge_device_id,
            EvidenceChain.sequence_number == sequence_number - 1,
        )
        .first()
    )
    if prev_chain is None:
        logger.warning(
            f"Chain gap: expected sequence {sequence_number - 1} for device {edge_device_id}, "
            f"not found in server chain table. Chain continuity CANNOT be confirmed."
        )
        return False

    chain_ok = prev_chain.current_hash == previous_hash
    if not chain_ok:
        logger.warning(
            f"CHAIN BREAK at sequence {sequence_number} for device {edge_device_id}. "
            f"Expected previous_hash={prev_chain.current_hash}, got {previous_hash}"
        )
    return chain_ok


def verify_event_integrity(
    evidence_package: EvidencePackage,
    public_key_pem: Optional[str],
    db: Session,
    edge_device_id: str,
    sequence_number: int,
) -> VerificationResponse:
    """
    Run all three verification checks and return a structured result.
    This is called both on ingest and when the dashboard 'verify integrity' button is clicked.
    """
    hash_valid = verify_hash(evidence_package)
    sig_valid = verify_signature(evidence_package, public_key_pem)
    chain_valid = verify_chain_continuity(
        db, edge_device_id, sequence_number,
        evidence_package.hash or "",
        evidence_package.previous_hash,
    )

    # Record in server-side chain table
    existing = (
        db.query(EvidenceChain)
        .filter(
            EvidenceChain.edge_device_id == edge_device_id,
            EvidenceChain.sequence_number == sequence_number,
        )
        .first()
    )
    if existing is None:
        chain_record = EvidenceChain(
            edge_device_id=edge_device_id,
            sequence_number=sequence_number,
            event_id=evidence_package.event_id,
            previous_hash=evidence_package.previous_hash,
            current_hash=evidence_package.hash or "",
            signature=evidence_package.signature or "",
            verified_at=datetime.utcnow(),
            chain_valid=chain_valid,
        )
        db.add(chain_record)
        db.flush()

    detail_parts = []
    detail_parts.append(f"HASH: {'VALID' if hash_valid else 'FAILED'}")
    detail_parts.append(f"SIGNATURE: {'VALID' if sig_valid else 'FAILED (no key)' if not public_key_pem else 'FAILED'}")
    detail_parts.append(f"CHAIN: {'VALID' if chain_valid else 'BROKEN'}")

    logger.info(
        f"Verification for event {evidence_package.event_id}: "
        f"hash={hash_valid}, sig={sig_valid}, chain={chain_valid}"
    )

    return VerificationResponse(
        event_id=evidence_package.event_id,
        hash_valid=hash_valid,
        signature_valid=sig_valid,
        chain_valid=chain_valid,
        detail=" | ".join(detail_parts),
        verified_at=datetime.utcnow(),
    )
