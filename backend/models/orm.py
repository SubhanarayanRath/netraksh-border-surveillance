"""
NETRAKSH Backend — SQLAlchemy ORM models.
All models correspond 1:1 to the data schema in the architecture document (§25).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str] = mapped_column(String(256), nullable=False)
    rtsp_url: Mapped[Optional[str]] = mapped_column(String(512))
    public_key_pem: Mapped[Optional[str]] = mapped_column(Text)   # Ed25519 public key PEM
    # AES-256 evidence-encryption key (architecture v4 §10), wrapped via
    # backend/security/evidence_key_wrap.py before storage — never the raw key.
    evidence_key_wrapped: Mapped[Optional[str]] = mapped_column(Text)
    owning_command_id: Mapped[str] = mapped_column(String(64), nullable=False, default="COMMAND_A")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    health_records: Mapped[List["CameraHealth"]] = relationship(
        "CameraHealth", back_populates="camera", cascade="all, delete-orphan"
    )
    events: Mapped[List["Event"]] = relationship(
        "Event", back_populates="camera", cascade="all, delete-orphan"
    )
    zones: Mapped[List["Zone"]] = relationship(
        "Zone", back_populates="camera", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# CameraHealth
# ---------------------------------------------------------------------------

class CameraHealth(Base):
    __tablename__ = "camera_health"
    __table_args__ = (
        Index("ix_camera_health_camera_id_ts", "camera_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    health_state: Mapped[str] = mapped_column(String(16), nullable=False)   # OK/DEGRADED/FAILED
    health_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fps_actual: Mapped[Optional[float]] = mapped_column(Float)
    fps_declared: Mapped[Optional[float]] = mapped_column(Float)
    drift_seconds: Mapped[Optional[float]] = mapped_column(Float)
    blur_score: Mapped[Optional[float]] = mapped_column(Float)
    exposure_clip_fraction: Mapped[Optional[float]] = mapped_column(Float)
    frame_variance: Mapped[Optional[float]] = mapped_column(Float)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="health_records")


# ---------------------------------------------------------------------------
# Zone (§2 correction)
# ---------------------------------------------------------------------------

class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(32), nullable=False)  # fence/checkpoint/verification/boundary
    polygon_json: Mapped[str] = mapped_column(Text, nullable=False)     # JSON list of {x,y} points
    owning_command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    adjacent_command_id: Mapped[Optional[str]] = mapped_column(String(64))  # non-null = boundary zone
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    camera: Mapped["Camera"] = relationship("Camera", back_populates="zones")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="zone")


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_camera_id_ts", "camera_id", "timestamp"),
        Index("ix_events_decision_state", "decision_state"),
        Index("ix_events_severity", "severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    zone_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("zones.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    event_type: Mapped[Optional[str]] = mapped_column(String(64))
    detection_class: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    scene_condition: Mapped[str] = mapped_column(String(32), nullable=False)
    camera_health_state: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(256))
    track_id: Mapped[Optional[int]] = mapped_column(Integer)
    severity: Mapped[Optional[str]] = mapped_column(String(16))
    direction: Mapped[Optional[str]] = mapped_column(String(32))
    rule: Mapped[Optional[str]] = mapped_column(String(64))
    rule_value: Mapped[Optional[float]] = mapped_column(Float)
    plate_text: Mapped[Optional[str]] = mapped_column(String(32))
    plate_confidence: Mapped[Optional[float]] = mapped_column(Float)
    evidence_clip_ref: Mapped[Optional[str]] = mapped_column(String(512))
    edge_device_id: Mapped[Optional[str]] = mapped_column(String(64))
    sequence_number: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    synced_from_edge: Mapped[bool] = mapped_column(Boolean, default=False)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="events")
    zone: Mapped[Optional["Zone"]] = relationship("Zone", back_populates="events")
    evidence_package: Mapped[Optional["EvidencePackage"]] = relationship(
        "EvidencePackage", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    alert: Mapped[Optional["Alert"]] = relationship(
        "Alert", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# EvidencePackage
# ---------------------------------------------------------------------------

class EvidencePackage(Base):
    __tablename__ = "evidence_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    digital_signature: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(64))
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    verified_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    hash_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    signature_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    chain_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    raw_package_json: Mapped[Optional[str]] = mapped_column(Text)   # full evidence package JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    event: Mapped["Event"] = relationship("Event", back_populates="evidence_package")


# ---------------------------------------------------------------------------
# EvidenceChain — server-side chain tracking
# ---------------------------------------------------------------------------

class EvidenceChain(Base):
    __tablename__ = "evidence_chain"
    __table_args__ = (
        Index("ix_evidence_chain_edge_seq", "edge_device_id", "sequence_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    edge_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(64))
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    chain_valid: Mapped[Optional[bool]] = mapped_column(Boolean)


# ---------------------------------------------------------------------------
# Alert — with escalation eligibility fields (§2 correction)
# ---------------------------------------------------------------------------

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_event_id", "event_id"),
        Index("ix_alerts_blockchain_status", "blockchain_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), unique=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    # Escalation eligibility (§1.3 — both must be true for blockchain submission)
    crosses_jurisdiction_boundary: Mapped[bool] = mapped_column(Boolean, default=False)
    command_id_issuing: Mapped[str] = mapped_column(String(64), nullable=False)
    command_id_receiving: Mapped[Optional[str]] = mapped_column(String(64))
    # Blockchain fields
    blockchain_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    blockchain_tx_id: Mapped[Optional[str]] = mapped_column(String(256))
    blockchain_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Acknowledgement
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(64))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    event: Mapped["Event"] = relationship("Event", back_populates="alert")
    acknowledgements: Mapped[List["AlertAcknowledgement"]] = relationship(
        "AlertAcknowledgement", back_populates="alert", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# AlertAcknowledgement
# ---------------------------------------------------------------------------

class AlertAcknowledgement(Base):
    __tablename__ = "alert_acknowledgements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    alert_id: Mapped[str] = mapped_column(String(36), ForeignKey("alerts.id"), nullable=False)
    receiving_command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ack_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)    # ACKNOWLEDGED/DISMISSED
    blockchain_tx_id: Mapped[Optional[str]] = mapped_column(String(256))
    blockchain_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alert: Mapped["Alert"] = relationship("Alert", back_populates="acknowledgements")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)    # ADMIN/OPERATOR/AUDITOR
    command_id: Mapped[str] = mapped_column(String(64), default="COMMAND_A")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# SyncQueue — server-side view of edge sync state
# ---------------------------------------------------------------------------

class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    edge_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    queued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_ts", "user_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")
