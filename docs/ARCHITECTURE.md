# NETRAKSH — Architecture Document
# AI-Based Intelligent Video Analytics Platform for Border Surveillance
# SIH 2026, Problem Statement #187, Team SecureX
# This document is generated and maintained by the engineering agent.
# It is the living record of what was actually built vs. the original design.

## Phase 0 Environment Spike Results

| Check | Status | Detail |
|-------|--------|--------|
| Python 3.14.7 | ✅ CONFIRMED | `pip` 26.2.1 |
| pip install (full dependency list) | ✅ CONFIRMED | All packages installed successfully. See section below. |
| `import ultralytics` | ✅ CONFIRMED | ultralytics 8.4.137, YOLO import succeeds |
| `import cv2` | ✅ CONFIRMED | OpenCV 5.0.0.93 |
| `import easyocr` | ✅ CONFIRMED | easyocr 1.7.2 |
| `import retina_face` | ⚠️ PARTIAL | `retina-face` package installed but import path is `retina_face`. See note. |
| `import sklearn` | ✅ CONFIRMED | scikit-learn 1.9.0 |
| `import cryptography` | ✅ CONFIRMED | cryptography 42.x |
| `import fastapi`, `uvicorn` | ✅ CONFIRMED | fastapi 0.141.1, uvicorn 0.52.4 |
| `import sqlalchemy`, `alembic` | ✅ CONFIRMED | SQLAlchemy 2.0.52, Alembic 1.19.1 |
| `import psycopg2` | ✅ CONFIRMED | psycopg2-binary 2.9.12 |
| Node.js | ✅ CONFIRMED | Node.js 24.19.0 (LTS) |
| WSL2 | ❌ NOT INSTALLED | Not available on this machine |
| Docker Desktop | ❌ NOT AVAILABLE | Requires WSL2 — not installed |
| Hyperledger Fabric `test-network` | ❌ NOT POSSIBLE | Docker required |
| PostgreSQL | ⏳ INSTALLING | EDB installer running |

### Confirmed Package Versions
```
ultralytics       8.4.137
opencv-python     5.0.0.93
easyocr           1.7.2
scikit-learn      1.9.0
cryptography      42.x
fastapi           0.141.1
uvicorn           0.52.4
sqlalchemy        2.0.52
alembic           1.19.1
psycopg2-binary   2.9.12
httpx             0.28.1
torch             2.13.0
torchvision       0.28.0
pytest            9.1.1
pydantic          2.13.5
```

---

## DECISION POINT RESOLUTIONS

### DP-1: Docker / Hyperledger Fabric
**Outcome: MOCK ADAPTER committed for this build.**

Rationale:
- WSL2 is not installed on this machine.
- Docker Desktop requires WSL2 on Windows.
- Without Docker, Hyperledger Fabric `test-network` cannot run.
- Timebox: the Phase 0 half-day spike identified this immediately.

**What this means:**
- `blockchain/client/mock_adapter.py` is the active blockchain adapter.
- The `FabricCLIAdapter` class exists in `backend/services/blockchain.py` and implements the identical interface — switching to real Fabric requires setting `BLOCKCHAIN_MODE=fabric` in `.env` and ensuring `peer` CLI is on PATH.
- Every place the mock is used is clearly labelled: in code comments, in `docs/LIMITATIONS.md`, and in the dashboard UI (`BLOCKCHAIN_MOCK_LABEL` env var).

**What the mock does not claim:**
- It does NOT simulate Byzantine fault tolerance.
- It does NOT simulate cross-org consensus.
- It DOES implement the exact same interface contract (AlertIssued / AlertAcknowledged) that real Fabric chaincode would expose.

### DP-2: Python version
**Outcome: Python 3.14 confirmed working — no downgrade needed.**

All packages installed and imported successfully. PyTorch 2.13.0 and Ultralytics 8.4.137 both support Python 3.14.

### DP-3: RetinaFace
**Outcome: Installed. Used as secondary detector, Haar cascade as primary fallback.**

`retina-face==0.0.17` installed. The face detection module uses RetinaFace when available, with OpenCV Haar cascade as fallback. Face recognition (ArcFace) is explicitly NOT in MVP scope.

---

## System Architecture Summary

### 3-Gate Reliability Pipeline (LOCKED)

```
Camera Frame
    │
    ▼
Gate 1: Camera Health Monitor
    ├── OK     ──────────────────────────────────────────────┐
    ├── DEGRADED ─────────────────────────────────────────── │ continue
    └── FAILED  ─────────────────→ ABSTAIN (stop here)       │
                                                             │
    ▼                                                        │
Gate 2: Scene Condition Classifier                           │
    ├── CLEAR_DAY      → threshold_clear_day (0.45*)         │
    ├── LOW_LIGHT_NIGHT → threshold_night (0.30*)            │
    ├── FOG_RAIN       → threshold_fog (0.35*)               │
    └── GLARE          → threshold_glare (0.40*)            │
         * = prototype values, not calibrated                │
                                                             │
    ▼                                                        │
Gate 3: Calibrated Confidence                               │◄─────
    ├── confidence < threshold → UNCERTAIN                   │
    └── confidence ≥ threshold:                              │
        ├── health == DEGRADED → DETECTED (flagged)         │
        └── health == OK       → DETECTED                   │
```

### On-Chain vs Off-Chain Split (LOCKED)

**On-chain ONLY (AlertIssued transaction):**
- alert_id, evidence_package_hash, severity, zone_id
- issuing_command_id, timestamp

**On-chain ONLY (AlertAcknowledged transaction):**
- alert_id, receiving_command_id, ack_timestamp, status, signature

**Off-chain (PostgreSQL):**
- All video, all events, all health history
- All detection details, tracks, dashboard state
- Full evidence package metadata

**Never on-chain:**
- Video clips
- Continuous health data
- Raw detection confidences
- Camera streams

### Edge-Server Architecture

```
Edge Device (per camera)
├── Layer 1: Camera Adapter (OpenCV, file/RTSP/webcam)
├── Layer 2: Health Monitor (Gate 1) + Condition Classifier (Gate 2)
├── Layer 3: YOLO+ByteTrack Detector (Gate 3, calibrated threshold)
├── Layer 4: Task Modules (fence, loitering, ANPR, face detection)
├── Layer 4.5: Event Verifier — CANDIDATE → VERIFIED/ALERTED state machine
│             (edge/temporal/event_verifier.py — see §Event Verification below)
├── Layer 5: Reliability Decision (DETECTED/UNCERTAIN/ABSTAIN)
├── Layer 6: Evidence Packager (SHA-256, Ed25519, SQLite hash-chain)
└── Layer 7: Sync Client (store-and-forward, SIMULATE_OFFLINE mode)

Backend Server (FastAPI + PostgreSQL)
├── REST API (events, alerts, cameras, auth, system)
├── WebSocket (live dashboard push)
├── Verification Service (hash+sig+chain re-verification on demand)
├── Escalation Engine (severity+jurisdiction → AlertIssued)
├── Blockchain Client (mock adapter / Fabric CLI)
└── RBAC (ADMIN / OPERATOR / AUDITOR)

Frontend (React + Vite)
└── Dashboard (live feed, camera map, evidence viewer, alert board)
```

---

## Event Verification (added — architecture v4 §9, Priority 3)

**What changed:** task modules (fence, loitering, abandoned object, ANPR, face) no longer trigger
evidence packaging directly. A new `edge/temporal/event_verifier.py` sits between the task modules
and `EvidencePackager` in `edge/main.py`, implementing the state machine:

```
OBSERVED → CANDIDATE → [held while Reliability=UNCERTAIN] → VERIFIED → ALERTED → ACKNOWLEDGED → CLOSED
```

- A task module firing is a **CANDIDATE** only. No evidence is generated at this point.
- A candidate needs `N` confirmations (the *same* condition observed again on a later frame, with
  Gate 3's Reliability decision = DETECTED) before promotion to **VERIFIED/ALERTED**, where evidence
  packaging finally happens. `N` is 3 for `VIRTUAL_FENCE_CROSSING` (the event type most exposed to
  one-frame tracking jitter) and 1 for loitering/abandoned/ANPR/face, whose own task-module logic
  already requires sustained dwell/stationary time before ever firing a candidate.
- A frame where Reliability is UNCERTAIN **holds** the candidate (no progress lost, no promotion
  either) rather than discarding or force-confirming it.
- A candidate not reconfirmed within `max_gap_frames` (default 5) expires with **no evidence
  generated at all** — this is the concrete mechanism behind the "a single noisy frame cannot become
  an alert" claim in the pitch.
- A 30-second cooldown after ALERTED prevents a still-true condition from spamming duplicate alerts
  every frame.

**Why:** previously, `VirtualFenceModule.check()` firing once on a crossing transition went straight
to `EvidencePackager.package()` the same frame — a single-frame tracking-jitter crossing (track
briefly wobbles across a zone boundary and back) would have generated a real, signed, chained,
alerted piece of evidence. It now requires the track to remain on the new side of the boundary for
3 consecutive re-checks first.

**What did NOT change:** `VirtualFenceModule`, `BehaviorModule`, `ANPRModule`, `FaceDetectionModule`,
`CameraHealthMonitor`, `SceneConditionClassifier`, `DetectionTracker`, and `make_reliability_decision`
are all untouched. Loitering/abandoned/ANPR/face behavior is functionally unchanged (they auto-verify
on their first DETECTED observation, same as their previous immediate-alert behavior) — only fence
crossing gained the multi-frame confirmation requirement.

**Tests:** `tests/unit/test_event_verifier.py` (11 new tests: single- vs multi-frame confirmation,
UNCERTAIN-holds-without-resetting, stale-candidate expiry, cooldown, per-track key isolation). Full
suite: 37 pre-existing tests + 11 new = 48 passed, 0 failed, 0 broken.

---

## Performance Instrumentation (added — architecture v4 §15, MUST HAVE)

**What changed:** a new `edge/instrumentation/metrics.py` (`PipelineMetrics`) records real,
locally-clocked latency at every pipeline stage instead of asserting "real-time" without evidence:

- **Per-frame** (every frame, event or not): `health_condition_ms`, `detection_tracking_ms`,
  `event_processing_ms`, `total_frame_ms`, plus FPS measured over a rolling window of actual frame
  timestamps (not the declared/configured rate).
- **Per-event** (only frames where the Event Verifier — see above — actually promotes a candidate to
  VERIFIED/ALERTED): `snapshot_ms`, `hash_sign_ms`, `chain_store_ms`, `enqueue_ms`, `total_event_ms`.
  `EvidencePackager.package()` now records these three timings into a new `self.last_timing` dict
  attribute on every call — its `(package, seq_num)` return contract is unchanged.
- **Resource usage** (CPU%/RSS): sampled via `psutil` if installed (now a soft/optional line in
  `requirements.txt`); if not installed, these fields report `null`, never a fabricated number.

Every stage is `time.perf_counter()`-timed (monotonic, sub-millisecond) and kept in a bounded rolling
window (mean/P95/max/min via nearest-rank percentile) so memory stays flat during a long demo.
`EdgePipeline` logs a one-line summary and writes `edge/data/metrics_<camera_id>.json` every
`metrics_report_interval_seconds` (default 10s). `scripts/print_performance_report.py` prints a
formatted report from that JSON, and `docs/PERFORMANCE_REPORT.md` is the template to fill in with a
real run before the numbers go in the PPT — see that file for the exact procedure, including the
before/after test needed to back any false-positive-reduction percentage with real counts instead of
an estimate.

**What did NOT change:** no existing pipeline stage's behavior or output changed — this is
read-only instrumentation wrapped around calls that already happen. `EvidencePackager.package()`'s
return signature is untouched (timing is exposed via an extra instance attribute, not a return-value
change), so the one existing call site (`edge/main.py::_emit_event`) and any future caller are
unaffected if they don't read `last_timing`.

**Tests:** `tests/unit/test_metrics.py` (16 new tests: percentile math, rolling-window stats, FPS via
an injectable fake clock, frame/event recording, honest resource-sampling fallback, JSON dump). Full
suite: 48 pre-existing tests + 16 new = 64 passed, 0 failed, 0 broken.

---

## Evidence-at-Rest Encryption (added — architecture v4 §10, MUST HAVE)

**What changed:** `edge/evidence/packager.py` gained a new `EvidenceEncryptor` class (AES-256-GCM,
authenticated encryption — tamper on the ciphertext is detected on decrypt, no separate MAC needed).
`EvidencePackager._save_snapshot()` now JPEG-encodes the frame in memory, encrypts those bytes before
anything touches disk, and writes a `.jpg.enc` file instead of a plain `.jpg`. The AES-256 key is
generated once per edge device and stored alongside the existing Ed25519 identity key
(`certs/edge/<camera_id>.aes`), following the same generate-once-then-load pattern as
`EdgeKeyManager`.

**What did NOT change:** `EvidencePackager.package()`'s `(package, seq_num)` return contract is
identical — encryption is fully internal. The one existing call site (`edge/main.py::_emit_event`)
required no changes at all. Nothing on the backend or dashboard was reading `evidence_clip_ref` and
serving it as an image before this change (confirmed by inspection — `backend/main.py`'s
`FileResponse` usage is for the frontend SPA build, unrelated to evidence clips), so there was no
plaintext-serving path to break.

**What is still open:** a backend/dashboard endpoint that reads an encrypted clip and decrypts it for
an authorized, RBAC-gated viewer does not exist yet — see `docs/LIMITATIONS.md` §3.

**Tests:** `tests/unit/test_evidence.py` gained `TestEvidenceEncryptor` (7 tests: key generation,
deterministic reload, malformed-key rejection, encrypt/decrypt round-trip, nonce uniqueness, tamper
detection, wrong-key rejection) and `TestEvidencePackagerAtRestEncryption` (2 tests: the on-disk file
is verifiably not a readable JPEG and decrypts back to a valid one; the return contract is
unchanged). Full suite: 64 pre-existing tests + 9 new = 73 passed, 0 failed, 0 broken.

---

## Hybrid Reliability Engine (added — architecture v4 §8, MUST HAVE)

**What changed:** `edge/reliability/decision.py`'s Gate 3 (raw confidence vs. a single per-condition
threshold) is replaced by a weighted-sum Reliability score:

```
Gate 1 (unchanged, hard override): health == FAILED -> ABSTAIN, stop.
Else:  R = wD*D + wT*T + wS*S + wH*H
       R < RELIABILITY_R_THRESHOLD (0.75)  -> UNCERTAIN
       R >= RELIABILITY_R_THRESHOLD        -> DETECTED (flagged if health == DEGRADED)
```

- **D** = raw detector confidence (unchanged input).
- **T** = temporal consistency, computed by a new `edge/temporal/track_features.py`
  (`TrackFeatureTracker`) — Mode A per `docs/ADR-TEMPORAL.md`: a hand-weighted average of track age,
  path smoothness, and speed consistency, needing zero labeled training data. Defaults to a neutral
  `1.0` when no track context is available (e.g. an abandoned-object event whose track has already
  disappeared).
- **S** = scene quality, a new continuous score derived from `SceneConditionReport`'s existing raw
  brightness/contrast/glare signals (previously only their *categorical* bucket was used).
- **H** = camera health quality (`OK`→1.0, `DEGRADED`→0.5; `FAILED` never reaches this — Gate 1
  handles it exclusively).
- Weights (`RELIABILITY_WEIGHT_D=0.40`, `_T=0.20`, `_S=0.20`, `_H=0.20`) and
  `RELIABILITY_R_THRESHOLD=0.75` are hand-picked heuristic defaults, not calibrated — all five are
  environment-overridable. `calibration_threshold` (the per-condition value from
  `edge/detection/calibration.py`) is still passed in and still gates what confidence YOLO itself
  reports as a candidate detection, and is still echoed into `applied_threshold` for context — it no
  longer drives the DETECTED/UNCERTAIN split itself.

**Intentional behavior change — read this before assuming a regression:** under the old cascade, a
lower per-condition confidence threshold made night/fog detections *easier* to accept (a compensating
leniency). Under the hybrid formula, degraded scene quality instead *reduces* R (via S), so a night
detection now needs the **same** evidentiary bar as a clear-day one, not an easier one. This is
deliberate, not a bug: the project's own thesis is that the system should trust itself **less** under
degraded conditions, not accept weaker evidence as if it were normal. One existing test
(`test_night_condition_uses_lower_threshold`) tested exactly the retired leniency and was rewritten —
see `TestHybridEngineIntentionalNightBehaviorChange` in `tests/unit/test_reliability.py` for the
replacement, which locks in the new, intended behavior with a comment explaining why.

**What did NOT change:** Gate 1's FAILED-camera hard override is byte-for-byte the same logic as
before — a weighted sum cannot provide this guarantee on its own, which is exactly why it stays a
categorical check ahead of the formula. `make_reliability_decision()`'s existing four positional
arguments are unchanged; `temporal_score` is a new optional keyword defaulting to a neutral `1.0`, so
any caller not yet upgraded to compute it sees the same numeric behavior as passing `1.0` explicitly
(verified by `test_default_temporal_score_is_neutral_one`).

**Tests:** `tests/unit/test_reliability.py` — 19 pre-existing tests became 26 (one rewritten with a
documented rationale, six new: banding boundaries, the intentional night-behavior tests, T's real
effect on a borderline case, and the weight configuration itself). New
`tests/unit/test_track_features.py` (11 tests: track age, bounded output, straight-line vs. zigzag
smoothness — including a caught-and-fixed bug where variance-of-turning-angle wrongly scored a
*regular* zigzag as smooth, corrected to mean-turning-magnitude — stationary-track handling,
insufficient-data defaults, age saturation). Full suite: 73 pre-existing + 7 net new in
`test_reliability.py` + 11 new in `test_track_features.py` = 91 passed, 0 failed, 0 broken.

---

## Track Continuity Guard (added — architecture v4 §4, MUST HAVE, closes v3/v4 Risk #2)

**What changed:** two independent, additive layers mitigate ByteTrack ID fragmentation under brief
occlusion — no learned Re-ID, classical CV only, matching the same "hand-crafted over learned, for
this problem size" philosophy as `docs/ADR-TEMPORAL.md`:

1. **`edge/config/bytetrack_border.yaml`** — a copy of ultralytics' bundled tracker config with
   `track_buffer` raised from the default 30 frames (~1s) to 120 (~4s), so ByteTrack itself waits
   longer before giving up on a lost track. `edge/detection/detector.py::DetectionTracker` now
   resolves this path by default (with a two-level fallback: an explicit path if the caller passes
   one, then this border-tuned config, then ultralytics' own bundled default if even that file is
   somehow missing — never a hard crash over a missing config file).
2. **`edge/tracking/continuity_guard.py` (`TrackContinuityGuard`)** — a second layer that recovers
   identity even *after* ByteTrack has given up and assigned a brand-new ID. Every active track's HSV
   color histogram + centroid is snapshotted each frame (`edge/main.py`); when a track disappears, its
   snapshot moves into a short-lived "lost pool" (5s TTL); when a genuinely new track ID appears, it's
   checked against that pool by histogram similarity (`cv2.compareHist`, correlation method) and
   spatial proximity. Above both thresholds, the new detection's `track_id` **and** `trajectory` are
   rewritten in place to the recognized identity, and the merge is logged
   (`[Pipeline] Track X re-associated with recently-lost track Y`) — never applied silently.

**Where this is applied in the pipeline:** `EdgePipeline._apply_continuity_guard()` runs immediately
after `detect_and_track()`, before trajectory storage, T-feature age tracking, or any task module sees
the track. Because re-association happens this early, `VirtualFenceModule`'s zone-membership state,
`BehaviorModule`'s dwell/stationary tracking, and `TrackFeatureTracker`'s age tracking all resume
automatically from where the original track left off — none of those modules needed to change.

**What did NOT change:** `VirtualFenceModule`, `BehaviorModule`, `ANPRModule`, `FaceDetectionModule`,
the Hybrid Reliability Engine, and the Event Verifier are all untouched — the guard operates entirely
upstream of them, on track identity only.

**Tests:** `tests/unit/test_continuity_guard.py` (15 tests: histogram+proximity matching, pool
removal on match, dissimilar/far/expired/no-pool non-matches, best-of-multiple-candidates selection,
TTL expiry, `compute_histogram`'s bounds-clipping and degenerate-crop handling) and
`tests/unit/test_detector_tracker_config.py` (5 tests: default/explicit/fallback config resolution,
the shipped `track_buffer` value itself). Full suite: 91 pre-existing + 20 new = 111 passed, 0 failed,
0 broken.

---

## Line Crossing Event Type (added — architecture v4 §5, HIGH VALUE, near-free)

**What changed:** a new `edge/rules/modules.py::LineCrossingModule` detects a tracked object's
centroid crossing a configured 2-point line segment, exactly as v4 described it: "a line is just a
degenerate polygon edge with directional crossing logic." It reuses `ZoneType.BOUNDARY` — already
defined in `shared/constants.py` but unused by any module until now — for zones with exactly 2
polygon points. Side is determined by the sign of a 2D cross product; direction is reported as a new
`LineCrossingDirection` (`A_TO_B` / `B_TO_A`, relative to the order of the two configured points — a
line has no inherent inside/outside, so this doesn't presume one the way `FenceDirection` does).
`EventType.LINE_CROSSING` is a new enum value. It shares the fence module's exposure to single-frame
tracking jitter, so it shares the same 3-confirmation depth in the Event Verifier (the confirmation
count was already reserved there — `edge/temporal/event_verifier.py`'s
`DEFAULT_REQUIRED_CONFIRMATIONS["LINE_CROSSING"]` — before this module existed to use it) and the
same "pending re-check" wiring in `edge/main.py` as fence crossing, checking
`LineCrossingModule.get_track_side()` instead of `VirtualFenceModule.get_track_zone()`.

**A real cross-module bug caught and fixed along the way:** `EvidencePackage.direction`
(`shared/schemas.py`) was typed `Optional[FenceDirection]`. Constructing an evidence package for a
line-crossing event would have thrown a Pydantic `ValidationError` at the first real line crossing —
`LineCrossingDirection.A_TO_B` isn't a valid `FenceDirection` member. Fixed by widening the field to
`Optional[str]`, which matches how `backend/models/orm.py` already stores this column (`String(32)`)
and doesn't require touching the locked field *name*, only its type. Covered by a new regression test,
`test_line_crossing_direction_is_accepted_alongside_fence_direction` in `tests/unit/test_evidence.py`.

**Severity:** `determine_severity()` assigns `LINE_CROSSING` a flat `MEDIUM` — deliberately not tiered
by direction the way fence crossing is (`OUTSIDE_TO_RESTRICTED` → `HIGH`), because a line has no
zone-specific "the dangerous direction" configuration the way a fence polygon's inside does. Neither
`A_TO_B` nor `B_TO_A` can be assumed more severe without that context.

**Real gap found, not new to this change:** `demo/scripts/zones_config.json` is currently `{"zones":
[]}` — empty. This means **every** zone-scoped task module (fence, line crossing, ANPR checkpoint,
face verification) is dormant in the current demo config, not just the new one. Real zone coordinates
matching the actual demo camera's framing need to be added before any of these can be shown live —
see `docs/LIMITATIONS.md`.

**What did NOT change:** `VirtualFenceModule`, `BehaviorModule`, `ANPRModule`, `FaceDetectionModule`,
the Hybrid Reliability Engine, the Event Verifier's core logic, and the Track Continuity Guard are all
untouched.

**Tests:** `tests/unit/test_line_crossing.py` (12 tests: zone-type/point-count filtering, no-fire on
first observation or same-side movement, crossing detection both directions, on-the-line ambiguity
handling, per-track isolation, multi-line independence) plus one new test each in
`tests/unit/test_evidence.py` (the direction-type regression above) and
`tests/unit/test_event_verifier.py` (confirms the reserved 3-confirmation depth is actually exercised
end-to-end now). Full suite: 111 pre-existing + 14 new = 125 passed, 0 failed, 0 broken.

---

## Adaptive Compute Gate (added — architecture v4 §6, HIGH VALUE)

**What changed:** a new `edge/detection/adaptive_gate.py::AdaptiveComputeGate` skips full YOLO
inference on frames that are genuinely idle — no motion, no active track, no candidate event pending
in the Event Verifier — running it only once every `IDLE_INFERENCE_INTERVAL_FRAMES` (default 5)
frames during that state, and every frame otherwise. It reuses `CameraHealthMonitor`'s existing
frame-difference variance signal (`CameraHealthReport.frame_variance`) against a new, higher threshold
(`MOTION_GATE_VARIANCE_THRESHOLD = 15.0`, deliberately above `FROZEN_FRAME_VARIANCE_THRESHOLD = 5.0` —
a frame that reaches this gate is guaranteed not frozen, since Gate 1 already handled that case) — no
new expensive per-frame computation is added anywhere.

**Why gating on "no active tracks" is what makes this safe:** ByteTrack needs continuous per-frame
detection to maintain a track's identity and trajectory — skipping inference on a frame with an active
track would look identical to that track disappearing, incorrectly triggering the stale-track cleanup
and Track Continuity Guard handoff built in earlier turns. The gate's `has_active_tracks` check makes
this impossible by construction: it only ever enters IDLE (and only ever skips) when
`self._trajectories` is already empty, so there is nothing to lose. The moment a real object enters
frame, the next full-rate inference tick (at most `idle_interval_frames` away) detects it, creates a
track, and `has_active_tracks` permanently forces full-rate inference again until that track
naturally ends.

**Where it's applied:** `EdgePipeline._process_frame()`, between the (always-run) Gate 1/Gate 2
health/condition checks and the detector call. Skipped frames record `detection_tracking_ms=0.0` in
the existing performance instrumentation — a real, visible number proving the compute saving, not a
claim.  Gate stats (state, frames run/skipped, skip ratio) are logged every metrics-report interval
and persisted into the same `edge/data/metrics_<camera_id>.json` via `PipelineMetrics.dump_json()`'s
new optional `extra` merge parameter (added specifically for this, without `PipelineMetrics` needing
to know anything about the gate that produced the extra fields).

**Deliberately NOT implemented — scope reduction, recorded honestly:** v4 §6 describes four tiers
(idle / object-present / candidate-forming / verified), the last two adding a higher-resolution crop
and full-resolution processing. This implementation has exactly two tiers (IDLE / ACTIVE) and never
changes resolution at any tier — there is no resolution reduction to "restore." This is the core,
highest-value half of the idea (the actual compute saving during idle periods); the resolution-tiering
half is real future work, not something to claim as done. See `docs/LIMITATIONS.md`.

**What did NOT change:** the detector, ByteTrack, the Track Continuity Guard, the Hybrid Reliability
Engine, and the Event Verifier are all untouched — the gate only decides whether `detect_and_track()`
gets called at all this frame; everything downstream is unaware it was skipped.

**Tests:** `tests/unit/test_adaptive_gate.py` (12 tests: idle/active classification on all three
inputs, exact interval scheduling — including a hand-traced 9-call sequence — countdown reset on the
idle→active transition, and stats tracking) plus 2 new tests in `tests/unit/test_metrics.py` for
`dump_json()`'s new `extra` parameter. Full suite: 125 pre-existing + 14 new = 139 passed, 0 failed,
0 broken.

---

## CLAHE Preprocessing + Night-Motion Fallback Wiring (added — architecture v4 §3, HIGH VALUE)

**What changed — two independent pieces closing out the last open item from architecture v4 §3:**

1. **CLAHE preprocessing** (`edge/condition/preprocessing.py::enhance_for_detection`): before
   `detect_and_track()` runs on a frame classified `LOW_LIGHT_NIGHT` or `FOG_RAIN`, a CLAHE-enhanced
   *copy* of the frame (LAB color space, CLAHE on the L channel, hand-picked `clipLimit=2.0`,
   `tileGridSize=(8,8)`) is built and passed to the detector instead of the original. Camera health,
   scene condition classification, evidence snapshots, and ANPR/face crops all continue to use the
   original, unmodified frame — enhancing before classification would make a genuinely dark/foggy
   scene measure as better than it is, corrupting the Hybrid Reliability Engine's `S` signal, which
   depends on that measurement being honest.
2. **Night-motion fallback wired in** (`edge/main.py`): `NightMotionFallback` — real code that existed
   since the original MVP but was never called from anywhere, confirmed dead by inspection before this
   change — now runs when a frame is `LOW_LIGHT_NIGHT`, YOLO found zero tracks, and we actually ran
   inference this frame (skipping this check on an Adaptive-Compute-Gate-skipped frame would be
   redundant with that gate's own, different motion signal already having said "no motion"). On
   detected motion, it emits a `MOVEMENT_UNCLASSIFIED` evidence record via the already-existing
   `make_uncertain()` helper — honestly labeled `UNCERTAIN`, never `DETECTED` — throttled by a new
   `NIGHT_MOTION_COOLDOWN_SECONDS` (30s) so continuous motion doesn't flood evidence storage with a
   snapshot every frame.

**A real design question worked through, not glossed over:** should this route through the Event
Verifier (architecture v4 §9) like every other event type? No — deliberately not. The Event Verifier
only counts frames where the accompanying Reliability decision is `DETECTED` toward confirmation,
and `make_uncertain()` always returns `UNCERTAIN` by construction. Routing this through
`submit_candidate()` would create a `CANDIDATE` that can mathematically never be promoted, silently
producing zero evidence — exactly the outcome this feature exists to avoid. It's emitted directly via
`_emit_event()` instead, with its own simpler cooldown standing in for the verifier's confirmation
gate. This is documented inline in `edge/main.py` at the call site, not just here.

**What did NOT change:** the detector, ByteTrack, the Adaptive Compute Gate, the Track Continuity
Guard, the Hybrid Reliability Engine, and the Event Verifier's core logic are all untouched.

**Tests:** `tests/unit/test_preprocessing.py` (7 tests: per-condition gating, real contrast increase
on a synthetic dark frame, no in-place mutation, spatial-dimension preservation for bbox coordinate
validity) and `tests/unit/test_night_motion_fallback.py` (5 tests covering `NightMotionFallback`
itself for the first time — first-frame priming, no-motion-on-identical-frames, real motion detection,
the `min_area` threshold's actual effect, per-instance state isolation). Full suite: 139 pre-existing
+ 12 new = 151 passed, 0 failed, 0 broken.

---

## Priority-Ordered Offline Sync Queue (added — architecture v4 §10, FUTURE-tier item)

**What changed:** `edge/sync/sync_client.py`'s SQLite outbox gained a `severity_rank` column, populated
at `enqueue()` time from the `EvidencePackage.severity` field already being packaged (`HIGH`→3,
`MEDIUM`→2, `LOW`→1, missing/unrecognized→0). `_fetch_pending()`'s ordering changed from
`sequence_number ASC` to `severity_rank DESC, sequence_number ASC` — a HIGH-severity event queued
behind older LOW-severity ones now syncs first once bandwidth returns; same-severity events still
resolve FIFO by sequence number.

**Why this doesn't threaten chain integrity:** the hash-chain (`edge/evidence/packager.py`) is a
strictly sequential, append-only *local* ledger tied together by each record's embedded
`previous_hash` — verified independently of arrival order at the backend (confirmed by inspection:
`backend/api/events.py::ingest_event` stores each event keyed by its own fields, with no dependency on
receiving events in sequence order). Chain order and network delivery order are two different things;
only the former needs to be strictly sequential, and this change only ever touches the latter.

**A real migration bug caught before it shipped:** the first version added the new
`idx_queue_priority` index in the same schema script as the table creation — for a *pre-existing*
database (`CREATE TABLE IF NOT EXISTS` is a no-op against one), the index would be created against a
`severity_rank` column that didn't exist yet, since the ALTER TABLE migration ran *after* the schema
script. Fixed by splitting table creation and index creation into two separate scripts with the
migration guard run strictly between them.

**Validated against real, pre-existing data, not just synthetic tests:** `edge/data/sync.db` already
exists in this repository from an actual prior run (`edge/data/clips/` holds real captured JPEGs dated
2026-09-01) — and it has the *old* schema, no `severity_rank` column. Running the migration against a
copy of this real file confirmed it works cleanly: **8,578 queued (never-synced) events**, a real
backlog from that prior run. Two things worth the team's attention, found while verifying this, not
part of what this change fixes:
- That 8,578-deep backlog suggests sync to a backend never actually succeeded during that run — worth
  checking before assuming the store-and-forward path has been exercised against a live backend.
- The JPEGs in `edge/data/clips/` from that run predate the AES-256 encryption change (a few turns
  ago) and are plain, unencrypted files — evidence captured *before* that change is not retroactively
  encrypted, only evidence captured after it. Both noted in `docs/LIMITATIONS.md`.

**What did NOT change:** `sync_once()`'s "stop the batch on first upload failure" behavior is
unchanged — now applied to the priority-ordered result set (documented inline at the call site so a
future reader doesn't mistake the reordering for also having revisited that decision).
`EvidenceChainStore`, `EvidencePackager`, and the backend ingestion endpoint are all untouched.

**Tests:** `tests/unit/test_sync_client_priority.py` (11 tests: rank ordering, same-severity tie
breaking, missing-severity handling, migration against a hand-built legacy-schema database, migration
idempotency, queue-depth correctness). Full suite: 151 pre-existing + 11 new = 162 passed, 0 failed,
0 broken.

---

## Backend Decrypt-on-View for Encrypted Evidence (added — architecture v4 §10)

**What changed — four pieces:**

1. **`shared/crypto.py` (new)** — the AES-256-GCM primitives from `EvidenceEncryptor` (edge) were
   extracted here so the backend doesn't duplicate cipher logic. `EvidenceEncryptor.encrypt()`/
   `.decrypt()` now delegate to this module; its public API and behavior are unchanged (verified: all
   28 pre-existing `test_evidence.py` tests still pass unmodified).
2. **`backend/security/evidence_key_wrap.py` (new)** — wraps a camera's raw AES key with a
   server-derived key-encryption-key (KEK) before storage. The KEK is derived via HKDF from
   `settings.SECRET_KEY` with a domain-separation label — deliberately **not** `SECRET_KEY` reused
   directly, since reusing one secret for two different cryptographic purposes (JWT signing there,
   key-wrapping here) is a real anti-pattern this avoids.
3. **`PUT /cameras/{camera_id}/evidence-key`** (`backend/api/cameras.py`, ADMIN-gated, mirrors the
   existing `PUT /cameras/{id}/public-key` pattern exactly) — accepts a camera's raw AES key
   (base64), wraps it, stores it in a new `Camera.evidence_key_wrapped` column. The raw key is never
   persisted. `EvidenceEncryptor.get_raw_key_b64()` (new) and `scripts/upload_evidence_key.py` (new)
   make this actually usable, not just theoretical.
4. **`GET /events/{event_id}/evidence-image`** (`backend/api/events.py`, requires `require_any_role`)
   — reads the evidence file, decrypts it if it's a `.jpg.enc` (using the requesting event's camera's
   unwrapped key) or serves it as-is if it's a legacy plain `.jpg`, and returns it as an image
   response.

**The architectural constraint this is honest about, not silent on:** `Event.evidence_clip_ref`
(`shared/schemas.py`) has always been a local **file path string**, not the image bytes — edge sync
(`edge/sync/sync_client.py`) never transmits the actual snapshot to the backend, only this path. The
new endpoint can only read that path because, in this project's current single-machine deployment, the
backend and edge process share a filesystem. **A real distributed deployment, where the edge device
and backend run on different machines, would need the edge to actually upload the evidence bytes
during sync — that is a separate, larger change, not implemented here.** This is documented at the
call site in code and in `docs/LIMITATIONS.md`, not glossed over.

**Two real pre-existing databases needed a migration, found by inspecting actual repo state, not
assumed:**
- `D:\SIH\netraksh\netraksh.db` already has a `cameras` table (1 real row: `edge-001`/"Alpha Gate")
  from before this change — `Base.metadata.create_all()` never alters an existing table, so this
  column would silently not exist there. Fixed with a new `_migrate_add_missing_columns()` in
  `backend/database/session.py`, using SQLAlchemy's database-agnostic `inspect()` (not SQLite-only
  `PRAGMA`, since `DATABASE_URL` can point at Postgres or SQLite) — called from `init_db()` on every
  startup, a no-op once the column exists. **Verified against a copy of the real file**, not just a
  synthetic one: column added, the existing camera row preserved.
- `edge/data/sync.db` (already migrated last turn) has real, pre-existing legacy `.jpg` snapshots
  referenced by its queued events — exactly the "legacy plain JPEG" case `get_evidence_image()`
  explicitly handles, not a hypothetical.

**A real pre-existing gap noticed while doing this, not fixed here (out of scope):**
`GET /events/{event_id}` (`get_event`, just above the new endpoint) has **no auth dependency at
all** — currently readable by anyone unauthenticated. The new `get_evidence_image()` deliberately
requires `require_any_role` rather than silently matching that weaker pattern; the pre-existing gap on
`get_event` is called out in code and in `docs/LIMITATIONS.md` for the team to decide on, not silently
left undocumented.

**What did NOT change:** `EvidencePackager`, `EdgeKeyManager`, the edge sync client's transmission
format, and every other endpoint are untouched. `EvidenceEncryptor`'s external behavior is identical
pre/post-refactor.

**Tests:** `tests/unit/test_shared_crypto.py` (7 tests: round-trip, nonce uniqueness, tamper/wrong-key
detection — the same guarantees `test_evidence.py`'s `TestEvidenceEncryptor` already covered, now
verified at the shared-primitive level too), `tests/unit/test_evidence_key_wrap.py` (9 tests:
wrap/unwrap round-trip, tamper detection, and specifically that the KEK is a real HKDF derivation, not
`SECRET_KEY` reused naively), `tests/unit/test_db_migration.py` (4 tests against a hand-built
legacy-schema table: column added, rows preserved, idempotent, no-op on a brand-new database). Full
suite: 162 pre-existing + 20 new = 182 passed, 0 failed, 0 broken. Endpoint-level HTTP tests
(`PUT .../evidence-key`, `GET .../evidence-image`) are **not** covered by an automated test in this
pass — `tests/integration/` and `tests/e2e/` are empty for every existing endpoint in this codebase,
not just these two, and building a FastAPI `TestClient` + auth-fixture harness from scratch is a
separate, larger effort than this feature. The pure functions each endpoint depends on (crypto,
wrapping, migration) are fully covered; the HTTP wiring itself is not — noted honestly rather than
implied as tested.

---

## Zone Coordinate Normalization + Populated Demo Zones (added — real bug fix, not aspirational)

**The actual request was "populate zones_config.json with real coordinates."** No demo video file
exists anywhere in this repository, and the default video source is a live webcam
(`VIDEO_SOURCE=0`), not a file — so there was no real footage to derive genuine coordinates from, and
writing plausible-looking pixel values against a guessed resolution would have been exactly the kind
of invented number this project has been careful to avoid everywhere else. Checking why zone
coordinates even needed a specific resolution at all surfaced a real, separate bug worth fixing
first.

**The bug:** `VirtualFenceModule.check()` in `edge/rules/modules.py` carried a comment claiming zone
polygons use normalized 0-1 coordinates, but the code beneath it never normalized anything — it
compared a track's raw-pixel centroid directly against whatever units the config file's polygon
happened to be written in. A zone config authored for one camera's resolution would silently
misbehave (fire in the wrong place, or never fire) on any other resolution. This affected every
zone-matching module identically: `VirtualFenceModule`, `LineCrossingModule`, `BehaviorModule`
(loitering + abandoned-object's zone lookup), `ANPRModule`, and `FaceDetectionModule`.

**The fix:** a new `normalize_point()` helper divides a raw-pixel point by the current frame's real
`(width, height)` before every polygon test. `edge/main.py` computes `frame.shape[:2]` once per frame
and passes it to `behavior_module.update()`, `fence_module.check()`, and `line_module.check()`;
`ANPRModule.process()` and `FaceDetectionModule.detect()` already received the frame directly and now
derive the same dimensions from it. All five call sites' new parameters default to `1.0, 1.0` (a
no-op divide) when omitted — every one of the 17 existing call sites across `test_line_crossing.py`
required zero changes as a result; the default made them keep testing exactly what they tested before
(coordinates in an arbitrary, self-consistent unit), while the live pipeline in `edge/main.py` always
passes the real frame size.

**Consequence — zone config is now resolution-independent by design:** a polygon written once (by
clicking real points, see below) keeps working correctly regardless of what camera or resolution
actually ends up in the demo — this was the actual uncertainty behind the original request (webcam vs.
video file, unknown resolution), solved by removing the dependency on knowing it in advance, not by
guessing at it.

**`demo/scripts/zones_config.json` is now populated** with one zone of each type (fence, boundary/line,
checkpoint, verification) in normalized coordinates, explicitly labeled in a `_readme` field (a key
`load_zones()` already ignores) as illustrative placeholders, not measured against real footage.

**`scripts/define_zone.py` (new)** is how these become genuinely real: it grabs one frame from an
actual camera or video file, opens a click-to-place-points window, and writes the resulting polygon
into `zones_config.json` in the exact normalized format the pipeline expects — replacing a
placeholder zone by `zone_id` or adding a new one, leaving every other zone untouched. This is the
only way to get real coordinates without fabricating them.

**What did NOT change:** the point-in-polygon and line-side-test algorithms themselves, the Event
Verifier, the Hybrid Reliability Engine, and every other module downstream of these five call sites
are untouched — this is purely a "what unit are these numbers in" fix at the boundary.

**Tests:** `tests/unit/test_zone_normalization.py` (6 tests, including an end-to-end test proving a
zone fires correctly at 720p and 1080p from the *same* normalized config, and does NOT fire on the
same raw pixel region at the wrong resolution — the actual bug this fixes, demonstrated, not just
asserted) and `tests/unit/test_define_zone.py` (13 tests covering every pure function in the new
script — pixel-to-normalized conversion, zone-record construction, config upsert-by-id, point-count
validation — including one that round-trips the script's output through the real `load_zones()`, not
a mock). The interactive click-loop itself needs a real display and is not covered by an automated
test — noted rather than silently skipped. Full suite: 182 pre-existing + 6 new
(`test_zone_normalization.py`) + 13 new (`test_define_zone.py`) = 201 passed, 0 failed, 0 broken;
**zero existing tests required modification**.

---

## Real Before/After False-Positive Measurement (architecture v4 §11, run for real)

**What was done:** no demo video or staged scenario existed to test against, so
`demo/videos/vtest.avi` — OpenCV's own official sample pedestrian-tracking clip (768×576, 10fps,
795 frames), fetched from `github.com/opencv/opencv` — was downloaded as a stand-in and inspected
frame-by-frame to place a real fence zone over its actual visible walkway (not a placeholder). A new
`scripts/run_false_positive_benchmark.py` runs the real production classes (`CameraHealthMonitor`,
`SceneConditionClassifier`, `CalibrationModule`, `DetectionTracker`/YOLO, `VirtualFenceModule`,
`make_reliability_decision`, `EventVerifier`, `PipelineMetrics`) against this clip twice — once with
the Event Verifier's confirmation requirement relaxed to 1, once at the shipped default of 3 — and the
real counts and latencies were transcribed into `docs/PERFORMANCE_REPORT.md`.

**A real bug caught mid-run, not after:** the first version of the benchmark harness omitted the
"pending re-check" loop that `edge/main.py` uses to let a multi-confirmation fence-crossing candidate
accumulate confirmations across frames (`VirtualFenceModule.check()` only fires once, on the crossing
transition — subsequent confirmation requires separately polling `get_track_zone()`). Without it, no
candidate could mathematically ever reach 3 confirmations regardless of what was in the video — the
first run's "0 alerts" result was an artifact of an incomplete harness, not a finding about the
pipeline, and was corrected before being reported anywhere.

**The honest result, after the fix:** 52 raw fence-crossing candidates fired; 23 became alerts under
*both* policies (1-confirmation and the shipped 3-confirmation default) — identical. This is **not**
the "verification reduces false alarms" headline number a team might hope for, and `docs/
PERFORMANCE_REPORT.md` reports it exactly that plainly rather than reframing it. What the same run
does show, diagnosed rather than glossed over: the Hybrid Reliability Engine independently filtered
52→23 candidates (only 23 ever reached `R≥0.75` on any frame), and every one of those 23 stayed
reliably detected for 3+ consecutive frames — this specific clean daytime clip simply contains none of
the single-frame tracking jitter the Event Verifier exists to catch, so it cost nothing but also
proved nothing here. Real latency numbers (mean 44.6ms/frame, P95 49.2ms, ~21.8 FPS on CPU) and
resource usage (~410–430MB RSS; the CPU% reading was found not to be credible and is flagged as such,
not reported as if it were) are in the same file.

**What did NOT change:** no production code — this is a new, standalone, read-only measurement script
that does not touch `EvidencePackager`, `SyncClient`, or write any certs/DB files; `edge/main.py` and
every module it calls are untouched.

**Explicitly flagged as incomplete, not silently left out:** this run used a generic public test clip,
not the team's actual demo footage or a staged intrusion scenario, and does not cover night/fog/glare
conditions or event-level (evidence-packaging) latency. `docs/PERFORMANCE_REPORT.md` says exactly this
and lists re-running against real staged footage as an explicit open item, checked off as *not* done
in its own honesty checklist.

---

## Frontend Decrypt-on-View Wiring (architecture v4 §10, closes the last open piece)

**What changed:** `frontend/src/pages/Evidence.jsx`'s Media Card now fetches the real decrypted
evidence image from `GET /events/{event_id}/evidence-image` instead of only ever showing the static
`/mock-fence.jpg` placeholder. States handled: `loading`, `ready` (real image rendered), `no-evidence`
(404), `no-key` (409 — camera hasn't run `scripts/upload_evidence_key.py` yet), `auth-required`
(401/403), and `error` (backend unreachable) — each with a distinct, honestly-labeled on-screen state
rather than silently falling back to the mock image indistinguishably from a real one.

**A materially bigger finding than the task looked like:** this frontend had **zero auth
infrastructure** anywhere — no login, no token storage, not a single `Authorization` header sent
anywhere in the codebase (confirmed by inspection: the existing `/verify` call sends no credentials,
which only works because that endpoint has no auth dependency either — a pre-existing gap, not
introduced here, already noted in `docs/LIMITATIONS.md`). The new evidence-image endpoint deliberately
*does* require a valid token (`require_any_role`), so wiring it up required a minimal real login flow,
not just a fetch call:

- **`frontend/src/services/auth.js` (new):** `login()` (POSTs form-encoded credentials to the
  already-existing `POST /auth/token`, which the frontend had never called), `getToken()`/`isAuthenticated()`
  (localStorage), and `authFetch()` (attaches the Bearer token to any request). Kept deliberately
  minimal — no route guarding, no logout UI polish, no token refresh — proportionate to what this task
  needed, not a full auth system.
- An inline sign-in form appears directly in the Media Card the first time a viewer without a token
  tries to view evidence, using the backend's already-seeded default admin account
  (`scripts/init_db.py`) — no new backend code was needed, only a frontend caller for infrastructure
  that already existed.

**What did NOT change:** no backend code. `Evidence.jsx`'s existing `/verify` flow, event list, and
every other page are untouched.

**Tests:** no new automated tests — this is a frontend-only change and the project has no frontend
test suite yet (a pre-existing gap, not introduced here). Verified instead by an actual production
build (`vite build`, 1837 modules, zero errors) and a lint pass (`oxlint`, zero errors — pre-existing
warnings on unrelated lines untouched). The backend's 201 Python tests are unaffected and confirmed
still passing.

---

## Zones Grounded in Real Footage (partial progress on the last open item)

**What changed:** `demo/scripts/zones_config.json`'s four placeholder zones were replaced with
coordinates placed by visually inspecting three real frames (t=30, 200, 450) from
`demo/videos/vtest.avi` — the same clip already used for the real false-positive benchmark
(`docs/PERFORMANCE_REPORT.md`) — instead of arbitrary round-number rectangles. Each zone now
corresponds to something actually visible in the footage: the fence zone covers a real taped-off,
cone-marked area in the scene; the trip-line crosses a real pedestrian chokepoint by a lamppost;
the checkpoint zone covers the only vehicle-parking area in frame; the verification zone covers a
signpost pause-point multiple people are seen stopping near across all three inspected frames.

**Why this isn't the same as running `scripts/define_zone.py` for real, and the task wasn't silently
substituted:** that script requires a live GUI window and real mouse clicks from a human operator —
there is no way to drive that interactively from here. Rather than leave the zones as ungrounded
placeholders or silently do something different without saying so, the same "inspect a real frame,
place a zone against real visible content" principle the script encodes was applied by hand, using
the one real video available. This is a genuine improvement in grounding, not a substitute for the
real thing — see `docs/LIMITATIONS.md`.

**Verified as actually active, not just plausible-looking:** ran `scripts/run_false_positive_benchmark.py`
against the new `fence-perimeter-1` coordinates on the real clip — 36 real candidate crossings fired
across 795 frames (23 alerts after Reliability Gate filtering, matching the same pattern already
documented in `docs/PERFORMANCE_REPORT.md`). A zone that never fires would have been a silent dead
end; this one is confirmed live.

**What did NOT change:** no code — this is a data-file update only. `edge/rules/modules.py`,
`scripts/define_zone.py` itself, and every test are untouched; the full 201-test suite is unaffected
and confirmed still passing.

---

## Reliability Panel Wired to Real Backend Data

**What changed:** `frontend/src/pages/Dashboard.jsx`'s "Reliability Decision" panel previously showed
entirely hardcoded values (`STREAM ACTIVE`, `FPS 30.0 (STABLE)`, `NIGHT / LOW-LIGHT`, `AI CONFIDENCE
0.91` / `NIGHT THRESHOLD 0.82`) regardless of what — if anything — was actually happening, and the
`[DETECTED]` button at the bottom was static markup, not tied to `decision_state` at all. It now
parses the real `decision_reason` string `edge/reliability/decision.py` writes (already flowing over
the existing `/ws/dashboard` WebSocket via `EventResponse` — no backend change needed) and renders the
actual D/T/S/H factors, the real R score, the real 0.75 threshold, and a DEGRADED-camera flag exactly
when the backend actually set one. Gate 1 shows the real `camera_health_state`; Gate 2 shows the real
`scene_condition`. When no real event has arrived yet, every panel honestly shows "Waiting for a real
event…" instead of a plausible-looking fabricated number — matching this project's standing rule
against ever displaying a number that didn't come from somewhere real.

**A relabeling this required, and why it's not scope creep:** the old panel's third box was titled
"Calibrated Conf" with a hardcoded "NIGHT THRESHOLD" field — vocabulary from the pre-Hybrid-Engine
3-gate cascade this project moved away from several changes ago. Since this panel is the exact one
`docs/PERFORMANCE_REPORT.md`'s Field Guide script plans to show a judge (Demo Segment A), leaving
stale, inaccurate architecture language on it while wiring in real numbers next to it would have been
worse than the old fully-fake version. It's now labeled "Reliability Factors (R = 0.40·D + 0.20·T +
0.20·S + 0.20·H)" — the actual formula, not a description of the old design.

**Verified end-to-end against the real backend, not just visually inspected:** started the actual
`backend.main:app` (serving the real, already-built `frontend/dist/`) via a new `.claude/launch.json`,
confirmed the real database migration log line, then POSTed a realistic event through the real
`POST /events` ingestion endpoint with `decision_reason="R_ABOVE_THRESHOLD_DEGRADED_CAMERA:R=0.812
>=0.750 (D=0.80,T=0.85,S=0.63,H=0.50),health=excessive_blur"` and confirmed in a live screenshot that
the dashboard rendered exactly D=0.80/T=0.85/S=0.63/H=0.50, R=0.812, threshold=0.750, the DEGRADED
flag, and the DETECTED button — all parsed correctly from the real string, not hand-verified against
the regex alone. The synthetic test event was deleted from the real database afterward.

**What did NOT change:** no backend code — every field this panel now uses was already in
`EventResponse` and already being broadcast; this was a frontend-only rewiring.

**Tests:** no new automated tests (frontend has no test suite yet, a pre-existing gap). Verified via
a real `vite build` (zero errors), `oxlint` (only pre-existing warnings on lines not touched by this
change), and the live end-to-end POST-and-screenshot check above. Backend's 201 tests unaffected and
confirmed still passing.

---

## Pre-Deployment Hardening: Auth Gaps Closed + Route Collision Fixed

Prompted by the move toward putting a live instance in front of judges — this is a first pass at
closing gaps that were fine for a local single-user demo but not for anything public.

**What changed:**
- `GET /events/{event_id}` and `POST /events/{event_id}/verify` (`backend/api/events.py`) now require
  `require_any_role`, matching `GET /events/{id}/evidence-image`. Both had been documented as open
  gaps in `docs/LIMITATIONS.md` since the evidence-image endpoint was added.
- Fixing the `/verify` endpoint's auth surfaced two independent, pre-existing frontend bugs in the same
  `handleVerify()` function (`frontend/src/pages/Evidence.jsx`) — neither related to auth, both just
  never caught because nothing had exercised this path end-to-end before:
  1. It called the endpoint with a bare `fetch()` (defaults to `GET`); the real route is `POST`. Every
     click had been silently 405'ing straight into the `catch` block since this button was written.
  2. Even on a successful call, it read `data.is_valid`, a field `VerificationResponse` doesn't have
     (the real fields are `hash_valid`/`signature_valid`/`chain_valid`) — so a genuinely valid
     verification would still have displayed "failed".
  Fixed to `authFetch(..., { method: 'POST' })` and to check all three real boolean fields.
- The frontend's `/health` SPA route (Camera Health Matrix page) was renamed to `/camera-health`. It
  collided with the backend's `GET /health` liveness probe (`backend/api/system.py`) — a real hosting
  platform polls exactly that path for container health checks, and FastAPI's own route always wins
  over the SPA catch-all on a direct/hard navigation, so `/health` served raw liveness JSON instead of
  the page. The backend's `/health` route itself is untouched.

**What did NOT change:** `GET /events` (`list_events`) still has no auth dependency — left open
deliberately, see `docs/LIMITATIONS.md`, since the dashboard's live feed depending on it is a product
decision (should unauthenticated viewers see live events at all?), not a drive-by fix. No database
schema changes. No changes to the reliability/temporal/evidence pipeline.

**Verified:** full backend suite still 201/201 passing. Rebuilt frontend (zero errors), `oxlint` clean
(pre-existing warnings only). Verified live in-browser: hit `/evidence` unauthenticated → correctly
shown the "Sign in to view evidence" state (not a raw 401); logged in as the seeded `admin` account;
clicked "Verify Netraksh Integrity Chain" and confirmed via `read_network_requests` that the request is
now a `POST` (previously never fired as one) carrying the `Authorization` header, returning `404` for
the mock/placeholder event ID shown by the page's fallback display data (expected — that ID has no
real database row) rather than the old silent `catch`-block failure.

**Tests:** no new automated frontend tests (pre-existing gap, frontend has no test suite). Backend
auth enforcement on these two routes is exercised the same way `get_evidence_image`'s was — no
dedicated HTTP-level test yet (see `docs/LIMITATIONS.md` §2, "Endpoint-level HTTP tests... do not
exist").

---

## Pre-Deployment Hardening: Hardcoded `localhost:8443` Removed

**What changed:** every frontend file talked to the backend via a literal `http://localhost:8443` or
`ws://localhost:8443` string — 10 call sites across `services/auth.js`, `pages/Health.jsx`,
`pages/Evidence.jsx`, `pages/Dashboard.jsx`, `pages/Alerts.jsx`, `components/Header.jsx`, and
`components/DemoSidebar.jsx`. That's harmless while the app is only ever opened as
`http://localhost:8443` (the backend serves the built frontend from that same origin — see
`backend/main.py`'s `StaticFiles` mount), but it would silently break every fetch and the dashboard's
live WebSocket the moment the app is reached at any other origin (a deployed domain, a different port,
`https://`). `services/auth.js` now exports `BACKEND_URL = window.location.origin` and
`WS_URL` (protocol-aware: `wss://` under `https:`, `ws://` otherwise) computed from the page's own
location at runtime, and every call site imports one of the two instead of hardcoding a string. No
build-time environment variable needed — this resolves correctly under `localhost` today and under
whatever real domain the app is deployed to next, automatically.

**Also fixed while here:** `Header.jsx`'s periodic `/sync/status` poll was a bare `fetch()` with no
Authorization header, against an endpoint that requires `require_any_role` — it had always 401'd
silently (caught, ignored) for any viewer, logged in or not. Switched to `authFetch()`, so it now
actually succeeds once a viewer has signed in via the Evidence page's login form.

**Confirmed, not assumed, still real:** `DemoSidebar.jsx`'s "Demo Scenario Control" panel calls
`/demo/inject-condition`, `/demo/trigger-camera-failure`, `/demo/simulate-offline` — grepped the entire
backend and confirmed none of these routes exist anywhere. Every click has always silently fallen
through to the `catch` block's local-only UI state. This was already honestly disclosed in the UI
itself (each button carries a "Simulated" badge, visible in the live screenshots) — not a hidden gap,
just an unimplemented one, now called out explicitly here and in `docs/LIMITATIONS.md` rather than left
merely "not yet inspected."

**Verified:** full backend suite 201/201. Rebuilt frontend (zero errors), `oxlint` clean (pre-existing
warnings only). Verified live: reloaded the app from a fresh browser tab, confirmed via
`read_network_requests`/console that the relative `WS_URL` still connects, then POSTed a real
synthetic event through `POST /events` and confirmed via live screenshot that it arrived over the
WebSocket and rendered correctly (Gate 1 OK, Gate 2 Clear Day, Gate 3 D/T/S/H=0.90) — the URL change
did not silently break the live event path. Test event deleted from the real database afterward.

---

## Frontend Audit + Full Real-Data Wiring Pass

Prompted by "check each and everything, all the functions in the frontend fully working... or no?"
followed by "make the project more and more advanced and fully workable/functionable" — a systematic
audit of every page, button, and fetch call in the frontend, then a full pass fixing everything
unambiguous. This is the largest single change in the project's history in terms of files touched;
full detail is broken out by area below.

### 1. Camera Health Matrix — was 100% mock, now genuinely real end-to-end

This was the single biggest gap found. `GET /cameras` (`backend/api/cameras.py`) already existed and
returned real `health_state`/`fps_actual`/`drift_seconds` — but `frontend/src/pages/Health.jsx` never
called it, running instead on 3 hardcoded cameras (CAM-07/12/04) with a "82%" / "36 OK / 5 DEGRADED /
3 FAILED" summary that didn't even arithmetically match the 3 cameras shown below it. Investigating
further surfaced that **the gap went deeper than the frontend**: no backend code path had ever
written a single row to the `CameraHealth` table, despite `edge/health/camera_health.py`'s
`CameraHealthMonitor` computing real blur/exposure/FPS/drift values every frame. The reason: the
"periodic health heartbeat" `edge/main.py`'s own docstring described didn't exist — `last_health_report_time`
was threaded through `_process_frame()`'s signature every frame but never actually read there, a dead
timer implying behavior that was never implemented.

**What changed, end to end:**
- `edge/main.py`: added `_report_camera_health()`, called from the (now-live) 5-second timer in
  `_run_frame_loop()`. Best-effort POST of the real `CameraHealthReport` to the backend — never
  interrupts the frame loop on failure, same offline-tolerant posture as `SyncClient`. This is
  deliberately NOT routed through the offline sync queue: it's a heartbeat, not evidence — losing one
  is fine, the next is 5 seconds away.
- `backend/api/cameras.py`: new `POST /cameras/{id}/health` endpoint — writes the real `CameraHealth`
  row and broadcasts it over `/ws/dashboard` via `broadcast_camera_health()`, a function that has
  existed since early in this project but had never once been called by anything.
- `shared/schemas.py`: widened `CameraStatusResponse` with `fps_declared`/`blur_score`/
  `exposure_clip_fraction` — real fields `CameraHealth` already stored but never exposed via the API.
- **A real, previously-latent bug found and fixed in the same pass:** `_camera_to_response()` fell back
  to the literal string `"UNKNOWN"` for `health_state` when a camera had no health row yet — but
  `CameraHealthState` is a strict enum of only `OK`/`DEGRADED`/`FAILED`. This made `GET /cameras`
  **500 for every real camera in the database**, always, from the moment it was written, since no
  camera had ever had a health row before this change either. Fixed by making `health_state: Optional`
  and passing `None` instead of a fabricated enum value — caught only because this session was the
  first time anything actually called this endpoint end-to-end with real data.
- `frontend/src/pages/Health.jsx`: fully rewritten. Real `GET /cameras` fetch (auth-gated, same
  `LoginPrompt` pattern as Evidence.jsx — see below), live WS merge (now genuinely reachable), real
  "System Sight" percentage computed from the real fleet, working "All Sectors"/"Needs Attention"
  filters (previously two `<button>`s with no `onClick` at all), and an honest "NO DATA YET" state per
  camera instead of ever fabricating a reading. The "⟲ INITIATE REBOOT" button — no backend endpoint
  exists for it — is left visible but `disabled`, with a tooltip explaining why, rather than either
  removed or left silently doing nothing on click.

**Verified live, not just read:** POSTed a real health report via `POST /cameras/{id}/health` (hit the
500 bug first, fixed it, then confirmed 201 + real DB row), confirmed `GET /cameras` returns it,
logged into the page via the new `LoginPrompt`, confirmed the real FPS/blur/exposure/drift numbers
render, confirmed the "Needs Attention" filter actually hides the OK camera, then deleted the test row.

### 2. Evidence Vault — remaining fake bits closed out

- Extracted the inline login form (previously duplicated verbatim inline) into a shared
  `frontend/src/components/LoginPrompt.jsx`, now used by both Evidence.jsx and Health.jsx.
- Search box had no `onChange` at all — typing did nothing. Now filters the real event list by
  `event_id`/`hash`/`event_type`/`decision_state`. (Caught during live verification: an initial version
  matched only `event_id`/`hash`, literally what the placeholder text promises, but a real user typing
  "Perimeter" — visible right there in the list — reasonably expects a match; broadened accordingly.)
- The "Cryptographic Hash Verification" strip showed the literal hardcoded strings `"RAW: 1.4MB"` and
  `"A94F...72C1"` for every single event, real or not. Now shows the real decrypted-evidence byte size
  (captured from the actual fetched blob) and the real `EventResponse.hash`, truncated for display —
  or an honest `"NO FILE"`/`"PENDING"` when neither exists yet.
- The event-list "SIGNED" badge was a hardcoded label. Now reads the real `signature` field
  (`SIGNED`/`UNSIGNED`) — the mock placeholder events correctly now show `UNSIGNED`, since they aren't.

### 3. Cross-Command Alerts — was real WS data permanently polluted with fake alerts

`GET /alerts` (real, RBAC-gated) existed and was never called; the page ran only on live WS pushes
(`new_alert`), permanently concatenated with 2 hardcoded fake alerts ("Multiple Armed Intruders",
"Vehicle Ramming Attempt") rendered identically to real ones, with zero visual distinction.

**What changed:**
- `Alerts.jsx` now fetches `GET /alerts` on load and merges it with live WS pushes (deduped by
  `alert_id`) — same convention Evidence.jsx already used for its own mock fallback: the 2 demo alerts
  now only appear when there are zero real alerts, clearly labeled `DEMO`.
- `AlertResponse` (`shared/schemas.py`) had no camera/event-type/timing fields at all — only
  severity/jurisdiction/blockchain/ack fields. Widened with `camera_id`/`event_type`/`zone_id`/
  `created_at`, sourced from `Alert.event` (an ORM relationship that already existed) — this is what
  lets the page show a real derived title ("HIGH — Abandoned Object") and real camera/elapsed-time
  instead of nothing. `backend/services/escalation.py`'s live WS broadcast payload was widened the same
  way for parity between the REST and WS paths.
- The real `POST /alerts/{id}/acknowledge` endpoint existed with no UI control anywhere. Added an
  "Acknowledge" button, wired to the real endpoint, using the seeded admin's session.
- **A second `/health`-class route collision found and fixed:** the frontend's `/alerts` SPA route
  collided with the real backend route `GET /alerts` (`backend/api/alerts.py`) — a direct
  hard-navigation to `/alerts` returned `{"detail":"Not authenticated"}` JSON instead of the page, for
  the identical reason `/health` did two changes ago. Missed when fixing `/health`, because nothing
  had checked every other frontend route against every other backend prefix at the time. Renamed to
  `/cross-command-alerts`; this session then audited every remaining frontend route against every
  backend router prefix to confirm no others collide.
- The tactical map view remains intentionally decorative — there is no real-world lat/lon or geodata
  model anywhere in this project (zones are 0-1 normalized within one camera's own frame, not a map).
  Left as-is, now explicitly labeled "(illustrative)" rather than silently implying real geodata.

**Verified live:** logged in, hit `/cross-command-alerts` directly (confirmed the collision first,
then confirmed the fix), saw 9 real alerts render with real derived titles/cameras/elapsed-time,
clicked Acknowledge on one, confirmed via `read_network_requests` a real `200 OK` to
`POST /alerts/{id}/acknowledge`, and confirmed the header's alert-count badge dropped 09→08 live in
response — a real cross-page side effect, not a local-only UI change. Two orphaned test-artifact
alert rows (from earlier sessions' synthetic testing, confirmed to reference no existing event) were
found and deleted from the real database as part of this verification.

### 4. Dashboard video overlay — dead bbox branch removed

`VideoFeed.jsx` checked `eventData.bbox` to decide whether to show a real detection label — but
`EventResponse` (what actually crosses the WebSocket) has no `bbox` field at all; it exists only on
the edge-internal `EvidencePackage` schema and never reaches the frontend. This branch could never
fire for any real event, so the label always showed the hardcoded "PERSON #184 | 91% CONF" even while
a real `detection_class`/`track_id`/`confidence` sat right there in the same object. Fixed to use the
real fields for the label whenever a real event exists (the box's on-screen position stays a
placeholder — there's no real pixel coordinate to draw it at without an actual video stream, which
this project doesn't have). Verified live: POSTed a real event with `detection_class: 'vehicle'`,
`track_id: 888`, confirmed the overlay updated to "VEHICLE #888 | 88% CONF".

### 5. Header — real alert count

The "⚠ 04" badge was a hardcoded literal, never reflecting anything. `/system/status` already
returned a real `pending_acknowledgements` count; the header just never read it. Now polled every 5s
alongside the existing sync-status poll, shown as `--` (not `00`) before the first successful fetch so
"no data yet" is never confused with "zero alerts".

**What did NOT change:** `GET /events` (`list_events`) still has no auth dependency — this remains a
deliberate open gap, same reasoning as before (see `docs/LIMITATIONS.md`). No changes to the edge
detection/reliability/temporal/evidence pipeline. The "Demo Scenario Control" panel's four buttons
remain unimplemented (no backend routes exist for them) — already honestly labeled "Simulated" in the
UI; building real scenario injection is a modest but real separate feature, not attempted here.

**Tests:** backend suite 201/201 passing throughout every step of this pass. No new backend HTTP-level
tests were added for the new `POST /cameras/{id}/health` endpoint (same pre-existing gap as every other
endpoint in this codebase — see `docs/LIMITATIONS.md` §2); verified instead via live POST + real DB
read + live screenshot, the same method used throughout this project for exactly this kind of check.
Frontend has no test suite (pre-existing gap); verified via `vite build` (zero errors each time),
`oxlint` (36 warnings throughout, all pre-existing patterns already present elsewhere in the codebase —
no new warning class introduced), and extensive live browser verification of every single fix in this
pass, documented above per area.

---

## Render Deployment Prep

Prompted by "let's deploy it live." This is the concrete build/config work needed before a
real deploy — not the deploy itself, which needs the user's own GitHub/Render accounts (see
`docs/DEPLOYMENT.md` for the full walkthrough and what to do next).

**What changed:**
- `backend/config.py`: `DATABASE_URL` now normalizes the legacy `postgres://` scheme to
  `postgresql://` via a `field_validator`. Render (and Heroku-style platforms before it)
  hand out connection strings with the old scheme; SQLAlchemy 1.4+ rejects it outright.
  Without this, pasting Render's own connection string into the env var would crash at
  engine creation on first boot. New test: `tests/unit/test_backend_config.py`.
- `requirements-backend.txt` (new): a verified-minimal dependency set for the backend
  container. The original `requirements.txt` installs the full stack (edge's
  `ultralytics`/`opencv`/`easyocr`/`retina-face` included) because local dev runs
  everything from one Python environment — but the backend container only ever runs
  `backend.main:app`, which never imports edge code at all (confirmed by grepping every
  `from edge`/`import edge` in `backend/` — none exist). Verified, not assumed: built a
  throwaway venv, installed only `requirements-backend.txt`, successfully imported
  `backend.main`, then deleted the venv.
- `Dockerfile`: rewritten to use `requirements-backend.txt`, drop the `edge/` and
  `yolov8n.pt` copies (unused, per above), and drop the `libgl1`/`libglib2.0-0` system
  packages (were only needed for opencv/ultralytics, no longer installed in this image).
  The previous Dockerfile had never been built even once — Docker is unavailable on the
  dev machine this project was built on — so this rewrite is itself unverified by an
  actual `docker build`, same caveat as before, now on a smaller, more carefully-reasoned
  image.
- `render.yaml` (new): a Render Blueprint defining the web service (Docker, free plan,
  `healthCheckPath: /health`) and a managed Postgres database, wired together via
  `fromDatabase`. `SECRET_KEY`/`ADMIN_PASSWORD`/`INITIAL_OPERATOR_PASSWORD`/
  `INITIAL_AUDITOR_PASSWORD` use Render's `generateValue: true` — real random values
  generated at deploy time, never the `CHANGE_ME_*` placeholders this project defaults to
  locally, and never committed to source control.
- `docs/DEPLOYMENT.md` (new): the actual step-by-step walkthrough, including what this
  deployment deliberately does NOT include (the edge pipeline, a real blockchain network)
  and why.

**What did NOT change:** no application logic, no API behavior, no frontend code. This is
pure deployment configuration.

**Honestly unverified:** the Postgres code path itself (`psycopg2-binary`, the connection
pooling settings in `backend/database/session.py`, `init_db()`'s migration logic against a
real Postgres rather than SQLite) has never been exercised against a real running Postgres
server — every verification in this project to date has been against real SQLite, because
that's what's available locally. The schema/migration code is written to be
database-agnostic (SQLAlchemy's `inspect()`, not raw SQLite pragmas), but "written to be"
and "verified to be" are different claims, and this document tries never to blur them.

**Tests:** 204/204 passing (3 new, for the `DATABASE_URL` normalization). Confirmed the
running dev server still boots cleanly after the `backend/config.py` change.

---

## Assumptions and Limitations
See `docs/LIMITATIONS.md` for the full list. Key items:
1. Blockchain is MOCK MODE (WSL2/Docker unavailable on dev machine)
2. Demo runs on CPU (laptop), not Jetson-class edge hardware
3. Detection thresholds are prototype values, not calibrated from labeled data
4. Face recognition is NOT attempted in MVP — detection only
5. ANPR scoped to checkpoint-angle cameras only
6. Clock drift check uses NTP-synchronized system clock (opportunistic)
