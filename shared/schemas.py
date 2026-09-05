"""
NETRAKSH — Shared Pydantic schemas.
These are the EXACT locked field sets from the architecture document (§1.2, §1.4).
Both edge and backend import from here; do not duplicate definitions elsewhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

from shared.constants import (
    BlockchainStatus,
    CameraHealthState,
    DecisionState,
    DetectionClass,
    EventType,
    HealthReason,
    SceneCondition,
    Severity,
    SyncStatus,
    UserRole,
    ZoneType,
)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

class Point(BaseModel):
    x: float
    y: float


class Polygon(BaseModel):
    points: List[Point]


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def centroid(self) -> Point:
        return Point(x=(self.x1 + self.x2) / 2, y=(self.y1 + self.y2) / 2)

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1


# ---------------------------------------------------------------------------
# Zone (§2 correction — required for fence/checkpoint/verification gating)
# ---------------------------------------------------------------------------

class ZoneSchema(BaseModel):
    """
    A configured zone in the camera's field of view.
    zone_type determines which task module is activated for objects entering it.
    adjacent_command_id being non-null means crossing this zone boundary is
    eligible for cross-command escalation (§1.3).
    """
    zone_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    name: str
    zone_type: ZoneType
    polygon: Polygon
    owning_command_id: str
    adjacent_command_id: Optional[str] = None  # Non-null → boundary zone → escalation eligible

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Camera Health (Gate 1 output)
# ---------------------------------------------------------------------------

class CameraHealthReport(BaseModel):
    """Output of the Camera Health Monitor (Gate 1). All fields required."""
    camera_id: str
    health_state: CameraHealthState
    health_reason: HealthReason
    health_timestamp: datetime = Field(default_factory=datetime.utcnow)
    fps_actual: Optional[float] = None
    fps_declared: Optional[float] = None
    drift_seconds: Optional[float] = None
    blur_score: Optional[float] = None
    exposure_clip_fraction: Optional[float] = None
    frame_variance: Optional[float] = None

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Scene Condition (Gate 2 output)
# ---------------------------------------------------------------------------

class SceneConditionReport(BaseModel):
    """Output of the Scene Condition Classifier (Gate 2)."""
    camera_id: str
    condition: SceneCondition
    brightness_mean: float
    contrast_std: float
    glare_fraction: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Detection track
# ---------------------------------------------------------------------------

class TrackData(BaseModel):
    """Per-object track from YOLO + ByteTrack."""
    track_id: int
    detection_class: DetectionClass
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trajectory: List[Point] = Field(default_factory=list)

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Reliability decision (Gate 3 output)
# ---------------------------------------------------------------------------

class ReliabilityDecision(BaseModel):
    """
    Output of the 3-gate reliability layer.
    decision_state is the public-facing result: DETECTED / UNCERTAIN / ABSTAIN.
    decision_reason stores the internal explanation string (always logged).
    """
    decision_state: DecisionState
    decision_reason: str
    camera_health: CameraHealthState
    scene_condition: SceneCondition
    detector_confidence: float = Field(ge=0.0, le=1.0)
    applied_threshold: float = Field(ge=0.0, le=1.0)

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Evidence Package — EXACT locked field set from architecture §1.4
# ---------------------------------------------------------------------------

class EvidencePackage(BaseModel):
    """
    Locked evidence package. Every field name here is specified in the
    architecture document and must not be renamed or removed.
    Additional optional fields are appended after the mandatory set.
    """
    # --- Mandatory locked fields (§1.4) ---
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    timestamp: datetime
    zone_id: str
    detection_class: DetectionClass
    confidence: float = Field(ge=0.0, le=1.0)
    scene_condition: SceneCondition
    camera_health_state: CameraHealthState
    decision_state: DecisionState
    evidence_clip_ref: Optional[str] = None  # path to snapshot/clip on edge storage
    # Cryptographic fields (set by evidence layer, empty until signed)
    hash: Optional[str] = None          # SHA-256 of serialized mandatory fields
    signature: Optional[str] = None     # Ed25519 signature over hash
    previous_hash: Optional[str] = None  # hash of previous record in chain

    # --- Optional contextual fields (appended per architecture §15) ---
    event_type: Optional[EventType] = None
    decision_reason: Optional[str] = None
    track_id: Optional[int] = None
    severity: Optional[Severity] = None
    # Deliberately `str`, not `FenceDirection`: this field is now shared by
    # multiple task modules with their own direction vocabularies
    # (FenceDirection for zone crossing, LineCrossingDirection for line
    # crossing — architecture v4 §5). Both are str-Enums, so existing values
    # pass through unchanged; a plain string here matches how the backend
    # already stores this column (backend/models/orm.py: String(32)).
    direction: Optional[str] = None
    rule: Optional[str] = None           # rule name that fired, e.g. "dwell_time_exceeded"
    rule_value: Optional[float] = None   # measured value, e.g. dwell seconds
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    face_bbox: Optional[BoundingBox] = None
    face_confidence: Optional[float] = None

    class Config:
        use_enum_values = True

    def get_signable_fields(self) -> dict:
        """
        Returns only the mandatory locked fields for hashing.
        Cryptographic fields (hash/signature/previous_hash) are excluded
        from their own hash computation to avoid circular dependency.
        """
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat(),
            "zone_id": self.zone_id,
            "detection_class": str(self.detection_class),
            "confidence": self.confidence,
            "scene_condition": str(self.scene_condition),
            "camera_health_state": str(self.camera_health_state),
            "decision_state": str(self.decision_state),
            "evidence_clip_ref": self.evidence_clip_ref or "",
            "previous_hash": self.previous_hash or "",
        }


# ---------------------------------------------------------------------------
# On-chain transaction schemas — EXACT locked field set from architecture §1.2
# ---------------------------------------------------------------------------

class AlertIssuedTransaction(BaseModel):
    """
    Only these fields ever go on-chain (§1.2). Nothing else.
    Populated by the escalation engine in backend/services/escalation.py.
    """
    alert_id: str
    evidence_package_hash: str          # SHA-256 of the evidence package
    severity: Severity
    zone_id: str
    issuing_command_id: str
    timestamp: datetime

    class Config:
        use_enum_values = True


class AlertAcknowledgedTransaction(BaseModel):
    """On-chain acknowledgement record (§1.2). Nothing else goes on-chain."""
    alert_id: str
    receiving_command_id: str
    ack_timestamp: datetime
    status: str                         # "ACKNOWLEDGED" | "DISMISSED"
    signature: str                      # Command B org signature

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# API request/response schemas
# ---------------------------------------------------------------------------

class EventCreateRequest(BaseModel):
    """Posted by the edge sync client to POST /events."""
    evidence_package: EvidencePackage
    edge_device_id: str
    sequence_number: int                # position in edge hash-chain


class EventResponse(BaseModel):
    event_id: str
    camera_id: str
    timestamp: datetime
    event_type: Optional[EventType]
    detection_class: DetectionClass
    confidence: float
    scene_condition: SceneCondition
    camera_health_state: CameraHealthState
    decision_state: DecisionState
    decision_reason: Optional[str]
    zone_id: str
    track_id: Optional[int]
    severity: Optional[Severity]
    hash: Optional[str]
    signature: Optional[str]
    verified_ok: Optional[bool]

    class Config:
        use_enum_values = True
        from_attributes = True


class VerificationResponse(BaseModel):
    event_id: str
    hash_valid: bool
    signature_valid: bool
    chain_valid: bool
    detail: str
    verified_at: datetime = Field(default_factory=datetime.utcnow)


class AlertResponse(BaseModel):
    alert_id: str
    event_id: str
    severity: Severity
    crosses_jurisdiction_boundary: bool
    command_id_issuing: str
    command_id_receiving: Optional[str]
    blockchain_status: BlockchainStatus
    blockchain_tx_id: Optional[str]
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[str]
    created_at: Optional[datetime] = None
    # Sourced from the related Event (Alert.event, already a real ORM
    # relationship) — widened so the frontend's Alerts page can show real
    # camera/timing/type info instead of the placeholder title/description
    # text it used to always show for every alert, real or not.
    camera_id: Optional[str] = None
    event_type: Optional[str] = None
    zone_id: Optional[str] = None

    class Config:
        use_enum_values = True
        from_attributes = True


class AlertAcknowledgeRequest(BaseModel):
    receiving_command_id: str
    status: str = "ACKNOWLEDGED"
    notes: Optional[str] = None


class CameraStatusResponse(BaseModel):
    camera_id: str
    name: str
    location: str
    # Optional, not CameraHealthState — a camera that has never reported
    # health (no CameraHealth row yet) has no state to report. This used to
    # be a bare CameraHealthState with the endpoint passing the literal
    # string "UNKNOWN" as a fallback — an enum value that doesn't exist
    # (CameraHealthState is only OK/DEGRADED/FAILED) — which made
    # GET /cameras 500 for every real camera before any health had ever
    # been ingested for it, i.e. always, before POST /cameras/{id}/health
    # existed. Now: None means "no data yet", handled explicitly by the
    # frontend rather than crashing the endpoint.
    health_state: Optional[CameraHealthState]
    health_reason: Optional[HealthReason]
    last_health_check: Optional[datetime]
    fps_actual: Optional[float]
    fps_declared: Optional[float]
    drift_seconds: Optional[float]
    # blur_score / exposure_clip_fraction have always been computed and stored
    # on CameraHealth (edge/health/camera_health.py) but never exposed here —
    # widened so the frontend's Camera Health Matrix can show real values
    # instead of the mock BLUR INDEX / EXPOSURE fields it had before.
    blur_score: Optional[float]
    exposure_clip_fraction: Optional[float]

    class Config:
        use_enum_values = True
        from_attributes = True


class SyncStatusResponse(BaseModel):
    edge_device_id: str
    is_online: bool
    queued_events: int
    last_sync_at: Optional[datetime]
    last_event_at: Optional[datetime]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    username: str

    class Config:
        use_enum_values = True


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.OPERATOR

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# WebSocket push message
# ---------------------------------------------------------------------------

class WSAlertMessage(BaseModel):
    """Pushed over WebSocket to dashboard on new alert."""
    type: str = "new_alert"
    alert: AlertResponse
