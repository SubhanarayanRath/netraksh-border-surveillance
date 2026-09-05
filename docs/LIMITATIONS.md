# NETRAKSH — Known Limitations

This file is the single source of truth for "is X actually real, or a placeholder" — referenced
from `docs/ARCHITECTURE.md`, `edge/detection/calibration.py`, and `edge/rules/modules.py`. If a
claim in the PPT or a demo script isn't backed by a line in this file (or isn't flatly true of the
code), don't make the claim. Update this file in the same change that closes or introduces a
limitation — an out-of-date limitations file is worse than none.

## 1. Fundamental limitations (not fixable by more engineering time alone)

- **Detection model is COCO-pretrained YOLOv8n, not fine-tuned on a border-surveillance dataset.**
  Night, fog, rain, and unusual terrain/viewpoint accuracy is a *data* problem, not an architecture
  problem — no amount of pipeline engineering around it changes what the underlying detector was
  trained to recognize. `edge/condition/scene_condition.py`'s CLAHE preprocessing (once wired, see
  §3 below) and the calibration module's per-condition thresholds are mitigations, not fixes.
- **Hybrid Reliability Engine weights and threshold are hand-picked, not calibrated — and a real
  attempt to calibrate them found this project's available real footage cannot supply what
  calibration needs.** `RELIABILITY_WEIGHT_D/T/S/H` and `RELIABILITY_R_THRESHOLD`
  (`edge/reliability/decision.py`) are shipped defaults chosen to preserve the qualitative behavior
  of the original 3-gate cascade on its own test cases. Architecture v4 §8's suggested upgrade path
  — fitting the weights via `LogisticRegression` over real labeled data — was actually attempted:
  `scripts/collect_calibration_data.py` ran the real production pipeline (real YOLOv8n detection,
  real `TrackFeatureTracker`, and the real `_scene_quality_score`/`_health_quality_score` functions
  imported directly from `edge/reliability/decision.py`, not reimplemented) against the same real
  video and zone already used for `docs/PERFORMANCE_REPORT.md`
  (`demo/videos/vtest.avi`, `(0.456,0.260)`–`(1.0,0.521)`), producing the same 52 real raw
  fence-crossing candidates that report already documents — each with its real `D`/`T`/`S`/`H`
  feature values and a labelable snapshot image (`scripts/calibration_data/`). A single reviewer then
  manually looked at every one of the 52 snapshots and labeled it by hand
  (`scripts/calibration_data/manifest.json`). The real, honest result: **all 52 are genuine detections
  of real people genuinely at or crossing the marked zone (label=1) — zero false positives.**
  `scripts/fit_reliability_weights.py` detects this single-class case explicitly and refuses to
  produce a fit, rather than printing meaningless coefficients from a dataset with no negative
  examples. This is a real, useful negative result, not a shortcut: it shows this project's one
  available real video (a generic public daytime pedestrian clip) is the wrong kind of dataset for
  this specific calibration — an actual false-positive-producing dataset (night/fog/glare footage,
  animals, wind-blown foliage, sensor noise) would be needed, and none of that currently exists as
  real footage anywhere in this project (see the "No custom border-surveillance dataset exists" item
  below). The current hand-picked defaults are therefore left in place, unchanged, pending such a
  dataset — not because they're proven correct, but because no real labeled data exists yet that
  could prove them wrong. The scene-quality (`S`) and health-quality (`H`) scoring functions remain
  hand-picked heuristics for the same reason.
  **Follow-up that found a real, more actionable problem than the fit itself:** the same collection
  script was re-run with `--synthetic-condition night` and `--synthetic-condition fog` — an honest,
  disclosed OpenCV brightness/contrast/haze transform applied to the same real footage (the people and
  motion are unchanged and real; only the lighting is synthetic — see the script's docstring). Both
  transforms genuinely triggered the real `SceneConditionClassifier` into `LOW_LIGHT_NIGHT`/`FOG_RAIN`
  on every frame (measured, not asserted), and manual review again found zero false positives — so the
  weight-fitting refusal above holds under degraded conditions too. But checking the CURRENT hand-picked
  weights against these genuine crossings (`scripts/analyze_reliability_under_conditions.py`) surfaced
  a real, severe, previously-unmeasured failure mode: **under the synthetic fog condition, 0 of 52
  genuine crossings cleared `RELIABILITY_R_THRESHOLD` — every single one was marked UNCERTAIN, not
  DETECTED.** Under synthetic night, 59% were missed. Diagnosis: a double penalty, not two independent
  ones — fog genuinely reduces contrast, which `S` already measures directly, and the same blur used to
  simulate fog haze also genuinely trips the Camera Health Monitor's Laplacian blur detector, which used
  to *also* halve `H` for the exact same real cause. **This has since been fixed**:
  `edge/reliability/decision.py::_health_quality_score` now scores `H` as healthy (1.0), not 0.5, when
  health is DEGRADED specifically for `EXCESSIVE_BLUR` *and* the scene is already independently
  classified `FOG_RAIN` or `LOW_LIGHT_NIGHT` — any other DEGRADED reason, or blur during `CLEAR_DAY`,
  still fully penalizes `H` exactly as before (locked in by
  `tests/unit/test_reliability.py::TestWeatherExplainedBlurDoesNotDoublePenalize`, 4 new tests, all
  passing; full suite 211/211). Re-measuring the same real labeled fog candidates against the fixed
  formula raised DETECTED from 0/52 (0%) to 37/52 (71%) — real, substantial, and honestly re-measured,
  not just claimed. Night's numbers are genuinely unchanged (21/51 both before and after) because the
  night transform never happened to trip `EXCESSIVE_BLUR` in this dataset.
  **Second follow-up fix, same real diagnosis pattern:** 71% still left 29% of genuine fog crossings
  UNCERTAIN, traced to `_scene_quality_score`'s `contrast_score` judging every FOG_RAIN frame against
  `_SCENE_CONTRAST_GOOD` (60.0) — a clear-day ideal a scene classified FOG_RAIN can never meet, since
  `contrast_std < FOG_CONTRAST_THRESHOLD` (30.0) is literally the real rule
  `edge/condition/scene_condition.py`'s `SceneConditionClassifier` already uses to call a scene foggy
  in the first place. The fix reuses that same, already-existing `FOG_CONTRAST_THRESHOLD` constant as
  FOG_RAIN's own contrast reference, instead of inventing a new number — a frame right at the real
  classification boundary now scores full contrast marks; one meaningfully foggier than that still
  scores proportionally lower, so this isn't a blanket free pass (locked in by
  `tests/unit/test_reliability.py::TestSceneQualityFogContrastReference`, 4 more new tests; full suite
  215/215). `LOW_LIGHT_NIGHT`/`CLEAR_DAY`/`GLARE` are untouched — night's real measured driver is
  brightness, not contrast (confirmed unchanged: 21/51 before and after this fix too). Re-measured
  result: fog rose further, from 71% to 87% DETECTED (45/52). **This remains a partial fix, not a
  solved problem** — 13% of genuine crossings under this specific fog intensity are still marked
  UNCERTAIN, and no further fix has been applied pending real fog footage to calibrate against. See
  `docs/PERFORMANCE_REPORT.md`'s "Reliability Engine behavior under real night/fog conditions" section
  for the full numbers and both fixes' before/after comparison.
- **Temporal Evidence Intelligence (Mode A) implements 3 of the 5 originally-specified features.**
  `edge/temporal/track_features.py` computes track age, path smoothness, and speed consistency.
  Dwell-time-in-zone and revisit-count (the other two features named in architecture v4 §7) are not
  yet integrated into `T` — they exist as separate, zone-scoped bookkeeping inside
  `edge/rules/modules.py::BehaviorModule` today, not exposed to the Reliability Engine. Mode B (a
  `LogisticRegression` over labeled data) is not implemented — see `docs/ADR-TEMPORAL.md`.
- **Detection thresholds are prototype values, not calibrated from labeled data.** The isotonic/Platt
  calibration engineering in `edge/detection/calibration.py` is real and functional
  (`CalibrationModule.fit()`), but no labeled dataset has been run through it yet — the thresholds
  currently in force (`THRESHOLD_CLEAR_DAY` etc.) are hand-picked, conservative defaults, explicitly
  logged as such at runtime. **Do not present these as calibrated in the PPT until `fit()` has
  actually been run and `docs/PERFORMANCE_REPORT.md` reflects it.**
- **No custom border-surveillance dataset exists.** A future dataset covering night/fog/rain/terrain
  could be collected and used to fine-tune the detector — this is documented as future work, not
  claimed as already done anywhere in this codebase.
- **Hardware target is intentionally generic, not a named board.** Per architecture v4 §2, no
  specific hardware (Jetson or otherwise) is claimed because the team has not benchmarked on one.
  Every FPS/latency number in `docs/PERFORMANCE_REPORT.md` is only valid for the machine it was
  actually measured on — see that file's metadata section.
- **AES-256 evidence encryption key is stored on the edge device's local disk**
  (`certs/edge/<camera_id>.aes`), not in a TPM/HSM. It protects evidence at rest from casual disk
  access or exfiltration of the storage medium, but **not** from an attacker who has already
  compromised the edge device itself. Hardware-backed key storage is future work.
- **`demo/scripts/zones_config.json`'s four zones are grounded in real footage (`demo/videos/vtest.avi`)
  but are still NOT the team's actual demo camera.** They were placed by visually inspecting real
  frames and matching each zone to something actually visible (a taped restricted area, a real
  pedestrian chokepoint, the only vehicle-parking area in frame, a signpost pause-point) — confirmed
  live by running the real benchmark against the fence zone (36 real candidate crossings fired) — not
  hand-picked round numbers with no visual basis, which is what they were before. This is a genuine
  improvement, but `scripts/define_zone.py` itself was never run interactively: that requires a live
  GUI window and real mouse clicks from a human operator, which isn't something that can be driven
  from here. Run it for real against your actual camera or video before a live demo — see
  `docs/ARCHITECTURE.md`'s changelog entry for exact usage.
- **A real, pre-existing `edge/data/sync.db` in this repository has an 8,578-deep never-synced queue**
  from an actual prior run (`edge/data/clips/` holds real JPEGs dated 2026-09-01). This suggests sync
  to a backend never actually succeeded during that run — worth checking directly (is a backend
  running? reachable? was `SIMULATE_OFFLINE` left on?) rather than assuming the store-and-forward path
  has been exercised end-to-end against a live server just because the code is tested.
- **Evidence captured before the AES-256 encryption change is not retroactively encrypted.** The real
  JPEGs in `edge/data/clips/` from that same prior run are plain, unencrypted files, because they
  predate `EvidenceEncryptor` (`edge/evidence/packager.py`) existing at all. Only evidence captured
  after that change is encrypted at rest. If demoing tamper-evidence or at-rest encryption specifically,
  use a freshly-generated event, not one of these historical files.
- **CLAHE's parameters and the night-motion fallback's cooldown are hand-picked, not calibrated.**
  `clipLimit=2.0` and `tileGridSize=(8,8)` (`edge/condition/preprocessing.py`) are the commonly-cited
  starting point for CLAHE on natural images, not values tuned against this project's own night/fog
  footage. `NIGHT_MOTION_COOLDOWN_SECONDS=30.0` (`shared/constants.py`) is similarly a starting guess
  at a reasonable debounce window. CLAHE is explicitly a mitigation for the detector's existing
  COCO-trained weights, not a fix for the underlying training-data gap (see the first bullet in this
  section) — it improves local contrast; it does not add information the sensor didn't capture.
- **Adaptive Compute Gate's thresholds are hand-picked, not calibrated.**
  `MOTION_GATE_VARIANCE_THRESHOLD` (15.0) and `IDLE_INFERENCE_INTERVAL_FRAMES` (5) in
  `shared/constants.py` are starting points chosen for plausibility relative to the existing frozen-
  frame threshold (5.0), not fit against real footage of an actually-idle border scene. A threshold
  set too low risks treating genuine slow motion as idle and briefly delaying detection; set too high,
  it saves little compute. This has not been measured on real footage — `docs/PERFORMANCE_REPORT.md`'s
  skip-ratio field, once populated from a real run, is exactly the number that would validate or
  correct this choice.
- **Track Continuity Guard's thresholds are hand-picked, not calibrated.** The border-tuned
  `track_buffer: 120` (`edge/config/bytetrack_border.yaml`), the histogram-similarity threshold
  (0.7), and the max centroid distance (150px) in `edge/tracking/continuity_guard.py` are starting
  points chosen for plausibility, not fit against real occlusion footage. Ultralytics' own comment on
  `track_buffer` is an honest tradeoff to repeat here: a higher value handles occlusion better but
  increases the risk of two different objects being wrongly merged into one identity. This has not
  been measured on real footage.
- **The one real false-positive measurement so far used a generic public test video, not the team's
  own footage, and found no measurable effect from temporal verification.** `docs/
  PERFORMANCE_REPORT.md` records this precisely: on `demo/videos/vtest.avi` (OpenCV's own sample
  clip), 23 of 52 raw fence-crossing candidates became alerts under *both* the 1-confirmation and the
  shipped 3-confirmation policy — the Event Verifier cost nothing but also proved nothing on this
  clip, because it contained no single-frame tracking jitter for it to catch. The Hybrid Reliability
  Engine's own filtering (52→23) is real and measured; the Event Verifier's specific benefit is not
  demonstrated by this run and needs footage with actual tracking instability to measure honestly. Do
  not claim a false-positive reduction number from temporal verification without re-running this
  against footage that actually exercises it.
- **That same run's CPU% reading (0.0) is not credible and must not be quoted.** A single end-of-run
  `psutil` sample doesn't capture sustained usage from a CPU-bound YOLO inference workload the way a
  periodic sampler would — `docs/PERFORMANCE_REPORT.md` flags this explicitly rather than reporting it
  as a real "0% CPU" result. The RSS memory reading (~410–430MB) from the same run is plausible and is
  reported normally.

## 2. Implemented, but scoped narrower than it might sound

- **This project has no Tailwind compiler — only a small hand-written CSS subset
  (`frontend/src/index.css`) — and several class names that look like Tailwind utilities
  throughout the frontend do nothing at all**, because they were never defined in that
  file. Confirmed (not assumed) via `getComputedStyle`: `.grid`, every `grid-cols-*`, and
  every responsive breakpoint prefix (`md:`, `lg:`, `xl:` — there are no `@media` rules in
  this file at all) silently collapsed every such layout to a single column. Found while
  building the real geospatial map (`docs/ARCHITECTURE.md`'s "Real Geospatial Map" entry)
  and fixed everywhere an exhaustive grep found it: `Alerts.jsx`, `Health.jsx` (twice),
  `Evidence.jsx`, `Dashboard.jsx` (twice), `Performance.jsx` — 7 total, all now real CSS
  Grid via inline `style`. The identical root cause as the earlier `text-center` bug
  (`Sidebar.jsx`, see the "Sidebar Logo Label Overflow Fix" entry). **Not investigated**:
  whether other class families beyond `grid`/`grid-cols-*`/breakpoint prefixes and the one
  `text-center` case have the same "looks real, isn't" problem — `gap-*` was checked and
  confirmed genuinely defined, but the rest of the class list in this codebase has not been
  systematically audited against `index.css`. Treat any layout that looks visually "off" as
  worth checking this way before assuming it's a different bug.
- **The header's Sync Status panel now honestly calls the real `GET /system/verify-chain`
  for its "Chain Integrity" line** (previously a hardcoded "Chain Integrity OK" regardless
  of any real state) — this means it shows "N block(s) failed integrity verification. Chain
  compromised." in red for any event whose `EvidencePackage` doesn't carry a real,
  verifiable Ed25519 signature. `scripts/seed_demo_events.py` generates a real keypair per
  demo camera and signs every event properly. The live Render deployment's demo events are
  all real-signed as of this writing (`GET /system/verify-chain` reports
  `"Successfully verified 6 blocks across all edge hash chains."`) — an earlier batch of 8
  unsigned demo events was found, identified precisely by `event_id`, and removed directly
  from the live database (with the user's own credentials, in FK-safe order:
  `alerts` → `evidence_packages` → `events`) once discovered.
- **Every backend-generated timestamp is stored and returned as a naive datetime with no
  UTC marker** (`SQLAlchemy`'s `DateTime` columns, populated via `datetime.utcnow()`
  throughout the codebase — the same call this project's own test suite already flags as
  deprecated Python). This was fixed at the frontend (`frontend/src/utils/time.js`'s
  `parseUtc()`), not at the source: every `DateTime` column would need to become
  `DateTime(timezone=True)` for the backend itself to emit correctly-marked timestamps,
  which is a real schema migration across every timestamped table, not a one-line fix. The
  frontend fix is complete and verified for every timestamp this app currently displays,
  but any *new* timestamp display added later must remember to route through `parseUtc()` —
  the underlying naive-storage gap has not been closed, only worked around at its one
  actual point of failure (parsing in the browser). See `docs/ARCHITECTURE.md`'s "Real Data
  on the Live Deployment + a Timezone Bug Found While Seeding It" for how this was found.
- **ANPR is a simplified, non-production heuristic**, not a real license-plate detector. It crops a
  fixed lower-middle-third region of the *vehicle* bounding box (a rough heuristic for typical plate
  location) and runs EasyOCR directly on that crop — there is no dedicated plate-detection model
  ahead of OCR. This is fragile at odd angles, occluded plates, or non-standard vehicle proportions.
  It is scoped to checkpoint-angle cameras only (`ZoneType.CHECKPOINT`) and is intentionally kept out
  of the primary demo narrative — mention it only if directly asked, and describe it exactly this
  honestly.
- **Face detection is detection-only, no recognition** — this is a deliberate, correct scope decision
  (not a limitation to apologize for), using OpenCV Haar cascade with RetinaFace as an optional
  higher-accuracy fallback when installed. No ArcFace or any face-recognition/matching capability
  exists anywhere in this codebase.
- **Blockchain is MOCK mode.** `MockBlockchainAdapter` is the active adapter because WSL2/Docker are
  unavailable on the development machine, so Hyperledger Fabric's `test-network` cannot run. The
  `FabricCLIAdapter` class implements the identical interface and is a one-line config swap
  (`BLOCKCHAIN_MODE=fabric`) away from being live, but it has never actually been exercised against a
  real Fabric network. On-chain scope is intentionally narrow either way — only `AlertIssued` /
  `AlertAcknowledged` transactions, never raw video or continuous health data.
- **RBAC has 3 roles (ADMIN/OPERATOR/AUDITOR)** with no granular per-zone or per-camera permission
  model. A richer Authorization & Context module (person/vehicle database, zone/time permissions) is
  explicitly Phase 2 per the architecture roadmap, not an MVP gap.
- **Clock drift detection is opportunistic**, comparing the edge device's system clock to frame
  timestamps — there is no hard NTP dependency or verification that the system clock itself is
  accurate, only that it is internally consistent with the frame stream.
- **`GET /events/{event_id}/evidence-image` only works because the backend and edge process share a
  filesystem in this project's current single-machine deployment.** `Event.evidence_clip_ref` has
  always been a local file path string, not the image bytes — `edge/sync/sync_client.py` never
  transmits the actual snapshot during sync, only this path. A real distributed deployment (edge and
  backend on different machines) would need the edge to upload the evidence bytes themselves during
  sync — a separate, larger change, not implemented.
- **The evidence-key KEK is derived from `settings.SECRET_KEY`, an application secret, not a
  dedicated secrets manager or HSM.** Anyone who has `SECRET_KEY` (already sensitive — it also signs
  every JWT) can derive the KEK (`backend/security/evidence_key_wrap.py`) and unwrap every camera's
  evidence key. HKDF with a domain-separation label at least prevents that derivation from also
  compromising anything else `SECRET_KEY` is used for, but this is a proportionate MVP tradeoff, not
  production-grade key management.
- **~~`GET /events/{event_id}` had no auth dependency at all~~ — FIXED.** As part of the pre-deployment
  hardening pass, both `GET /events/{event_id}` and `POST /events/{event_id}/verify`
  (`backend/api/events.py`) now require `require_any_role`, matching `GET /events/{id}/evidence-image`.
  Fixing this also surfaced two independent, unrelated frontend bugs in `Evidence.jsx`'s "Verify
  Netraksh Integrity Chain" button, both now fixed too: (1) it called the endpoint with a bare
  `fetch()`, which defaults to `GET` — the real route is `POST`, so this button had been silently
  405'ing (caught by the `catch` block) on every click since it was written; (2) even on a successful
  call it read a `data.is_valid` field that doesn't exist on `VerificationResponse` (the real fields are
  `hash_valid`/`signature_valid`/`chain_valid`), so it would have always reported "failed" regardless of
  the actual verification result. `list_events` (`GET /events`) still has no auth dependency — left as
  an open gap below, since making the dashboard's own live event feed require auth is a larger,
  deliberate call for the team, not a drive-by fix.
- **`GET /events` (`list_events`) still has no auth dependency.** Unlike the three endpoints above, this
  one is left open deliberately: the dashboard's live WebSocket feed and REST fallback both depend on
  reading events without a login gate today, and closing it means deciding whether unauthenticated
  viewers should see live event data at all — a product decision, not a one-line fix.
- **The frontend's `/health` SPA route (Camera Health Matrix) was renamed to `/camera-health`** — it
  collided with the backend's `GET /health` liveness probe (`backend/api/system.py`), which a real
  hosting platform (Render, Railway, Fly.io, etc.) will poll at that exact path for container health
  checks. Hitting `/health` directly (not via in-app client-side navigation) returned the backend's raw
  JSON instead of the page, since FastAPI's own route wins over the SPA catch-all. The backend's
  `/health` endpoint itself is untouched — it's the conventional liveness-check path and should stay
  there.
- **Every hardcoded `http://localhost:8443` / `ws://localhost:8443` string in the frontend (10 call
  sites) was replaced with a runtime-derived `BACKEND_URL`/`WS_URL` (`frontend/src/services/auth.js`,
  from `window.location`).** They worked only by coincidence, since the backend has always served the
  built frontend from that exact origin — deploying to any real domain would have silently broken
  every fetch and the live WebSocket. No config needed going forward; it resolves correctly under any
  origin automatically.
- **The "Demo Scenario Control" panel's four buttons (`frontend/src/components/DemoSidebar.jsx`) call
  backend routes that do not exist** — `/demo/inject-condition`, `/demo/trigger-camera-failure`,
  `/demo/simulate-offline`. Confirmed by grepping the entire backend; there is no `demo` router at all.
  Every click always falls through to the local-only "Simulated" UI state. This was already disclosed
  honestly in the UI (each button carries a "Simulated" badge) — not a hidden gap — but is recorded
  here explicitly now that it's been confirmed rather than merely flagged as unchecked. Implementing
  real scenario injection (forcing a camera's health/scene-condition state server-side for a live demo)
  is a real, if modest, feature — not attempted here.
- **`Header.jsx`'s periodic `GET /sync/status` poll (every 5s) requires `require_any_role`
  (`backend/api/system.py`) but nothing in the header ever prompts for login** — it 401s for the
  duration of any session that never visits the Evidence page's login form (which is the only place a
  viewer can sign in). Switched the call to `authFetch()` so it succeeds once a viewer is logged in,
  but the underlying design question — should sync status require auth at all, given the rest of the
  dashboard is viewable without logging in? — is left open, same category as `GET /events` below.
- **Pre-live-deployment checklist, not yet actioned (all require an explicit decision, not a drive-by
  fix):**
  - `SECRET_KEY` (`backend/config.py`) defaults to the literal string `"CHANGE_ME_USE_openssl_rand_hex_32"`
    when not set via environment/`.env`. It signs every JWT and (via HKDF) derives the evidence-key KEK
    — a real deployment MUST set a real, random `SECRET_KEY` via the hosting platform's environment
    variables, never commit one to source control.
  - `ADMIN_PASSWORD`/`INITIAL_OPERATOR_PASSWORD`/`INITIAL_AUDITOR_PASSWORD` default to
    `CHANGE_ME_*_password` placeholders, used only to bootstrap the three seed accounts on a first boot
    against an empty database — a fresh deployment MUST override these via environment variables before
    first boot, or anyone can look up the default in this repo and log in as admin.
  - `DATABASE_URL` defaults to SQLite locally (`sqlite:///./netraksh.db`, currently a 3.5MB real file
    with real seeded data in this repo). Most container-hosting platforms' filesystems are ephemeral —
    the database would be silently wiped on every redeploy/restart. `psycopg2-binary` is already in
    `requirements.txt` for exactly this reason; a real deployment needs an actual Postgres instance
    (managed or self-hosted) and `DATABASE_URL` pointed at it, not the SQLite default.
  - This repository is not a git repository at all (`git status` fails with "not a git repository") —
    there is no version history and nothing to push to a platform that deploys from a git remote.
  - No `Dockerfile` exists yet for a containerized deploy target.
- **Endpoint-level HTTP tests for the two new evidence-image/evidence-key routes do not exist.**
  `tests/integration/` and `tests/e2e/` are empty for every endpoint in this codebase already, not
  just these two — the crypto/wrapping/migration logic each endpoint depends on is fully unit-tested,
  but the HTTP wiring itself (auth enforcement, status codes, request/response shape) is not covered
  by an automated test yet.

## 3. Designed in architecture v4, not yet implemented in code

These are real, open gaps — tracked here so nothing is silently assumed to exist. Each links to the
architecture section that specifies it.

| Item | Architecture ref | Status |
|---|---|---|
| Adaptive compute gating's resolution tiers (higher-res crop on candidate-forming, full-res on verified) | v4 §6 | **Not implemented.** Only the idle/active inference-*rate* gating is built (`edge/detection/adaptive_gate.py`) — see §1 below. No tier changes resolution; there's nothing to "restore" resolution from. |
| Edge transmitting evidence bytes (not just a path) during sync, for a real distributed deployment | v4 §10 | **Not implemented.** `Event.evidence_clip_ref` is a local file path string; `edge/sync/sync_client.py` never uploads the actual snapshot. `GET /events/{event_id}/evidence-image` only works when the backend and edge share a filesystem, as they do in this project's current deployment — see §1 above. |
| Re-running the false-positive measurement against real staged demo footage | v4 §11, `docs/PERFORMANCE_REPORT.md` | **Not run.** The one real run so far used a generic public test clip (`demo/videos/vtest.avi`, OpenCV's own sample), not the team's actual demo footage or a staged intrusion scenario, and doesn't cover night/fog/glare conditions — see §1 below. |

## 4. What IS real and measured (as of this writing)

- Camera health (frozen-frame, blur, exposure, FPS ratio, clock drift) and scene condition
  (brightness/contrast/glare) are computed from real OpenCV/numpy signal processing on every frame —
  not simulated.
- YOLOv8n + ByteTrack detection/tracking is real, running via `ultralytics`.
- The Event Verifier state machine (CANDIDATE → VERIFIED/ALERTED, confirmation-gated) is implemented
  and unit-tested (`tests/unit/test_event_verifier.py`).
- The Hybrid Reliability Engine (Gate-1 hard override + weighted-sum `R = wD·D+wT·T+wS·S+wH·H`) is
  implemented and unit-tested (`tests/unit/test_reliability.py`), including a deliberate, documented
  behavior change from the original cascade (see `docs/ARCHITECTURE.md`). Its weights are real code,
  not a slide — but see §1 above for their calibration status.
- Temporal Evidence Intelligence Mode A (track age, path smoothness, speed consistency →
  `T`) is implemented and unit-tested (`tests/unit/test_track_features.py`), per the no-SSM decision
  recorded in `docs/ADR-TEMPORAL.md`.
- The Track Continuity Guard (border-tuned ByteTrack `track_buffer` + classical-CV color-histogram
  re-association) is implemented and unit-tested (`tests/unit/test_continuity_guard.py`,
  `tests/unit/test_detector_tracker_config.py`) — but see §1 above for its threshold-calibration
  status.
- Line crossing (`edge/rules/modules.py::LineCrossingModule`) is implemented and unit-tested
  (`tests/unit/test_line_crossing.py`), routed through the same Event Verifier confirmation logic as
  fence crossing — but see §1 above: it has no configured zones to actually fire against yet.
- The Adaptive Compute Gate (idle/active inference-rate scheduling) is implemented and unit-tested
  (`tests/unit/test_adaptive_gate.py`), with its skip ratio logged and persisted alongside the rest of
  the real performance instrumentation — but see §1 above for its threshold-calibration status, and
  see §3 above for the resolution-tiering half of v4 §6 that isn't built.
- CLAHE preprocessing and the night-motion fallback are both implemented and unit-tested
  (`tests/unit/test_preprocessing.py`, `tests/unit/test_night_motion_fallback.py`) — the latter
  closing out real, previously-dead code, not new logic from scratch. Both are mitigations with
  hand-picked parameters; see §1 above for exactly what that does and doesn't claim.
- The offline sync queue is priority-ordered (`severity DESC, sequence_number ASC`) and unit-tested
  (`tests/unit/test_sync_client_priority.py`), including a migration path verified against the actual
  pre-existing `edge/data/sync.db` in this repo, not just a synthetic test database.
- Backend decrypt-on-view for encrypted evidence is implemented (`shared/crypto.py`,
  `backend/security/evidence_key_wrap.py`, `PUT /cameras/{id}/evidence-key`,
  `GET /events/{id}/evidence-image`) and its crypto/wrapping/migration logic is unit-tested — but see
  §1 above for the single-machine deployment constraint, the KEK's security tradeoff, and the
  untested HTTP layer.
- The frontend now actually calls that endpoint (`frontend/src/pages/Evidence.jsx`, via the new
  `frontend/src/services/auth.js`) instead of it only proving itself over curl — including the
  minimal login flow this required, since the frontend previously had no auth infrastructure at all.
  Verified via a real `vite build` and lint pass, not an automated test — this project has no frontend
  test suite yet, a pre-existing gap.
- The Dashboard's Reliability Decision panel (`frontend/src/pages/Dashboard.jsx`) now shows the real
  D/T/S/H factors, R score, and threshold parsed from the real `decision_reason` string, instead of
  hardcoded placeholder values — verified end-to-end by POSTing a real event through the real
  ingestion endpoint and confirming the rendered numbers in a live screenshot, not just reading the
  code. The dashboard's "Demo Scenario Control" panel (Normal Ops / Dense Fog / Sensor Failure /
  Offline buttons) was later confirmed (not just left unverified) to call backend routes that don't
  exist at all — see the frontend audit entry below.
- **Camera Health Matrix, Cross-Command Alerts, and the Dashboard's video overlay label are now wired
  to real backend data** (a full audit + fix pass — see `docs/ARCHITECTURE.md`'s "Frontend Audit + Full
  Real-Data Wiring Pass" for complete detail on each). Summary: `GET /cameras` is now actually called
  (it never was); a real `POST /cameras/{id}/health` ingestion endpoint was added because the backend
  had never once written a `CameraHealth` row despite the edge computing real values every frame;
  `GET /alerts` is now actually called and the 2 hardcoded fake alerts that used to be permanently
  mixed into the real WS feed are now a true empty-state fallback only; the video overlay's detection
  label now uses the real event's `detection_class`/`track_id`/`confidence` instead of a hardcoded
  placeholder that could never be replaced (the dead `eventData.bbox` check it depended on can never
  be true — `EventResponse` has no `bbox` field). The header's "⚠ 04" alert badge is now a real count
  from `/system/status`'s `pending_acknowledgements`.
- **A second `/health`-class route collision was found and fixed:** the frontend's `/alerts` SPA route
  collided with the real backend route `GET /alerts`, identically to the earlier `/health` collision.
  Renamed to `/cross-command-alerts`. Every remaining frontend route was then checked against every
  backend router prefix to confirm no further collisions exist.
- **A real, previously-latent 500 error in `GET /cameras` was found and fixed:** `_camera_to_response()`
  passed the literal string `"UNKNOWN"` as a `CameraHealthState` for any camera with no health row yet
  — but that enum only has `OK`/`DEGRADED`/`FAILED`. This endpoint would 500 for every real camera in
  the database until its very first health report, which (see above) had never happened for any camera
  before this pass, meaning this endpoint had never once returned successfully for real camera data.
  Fixed by making `CameraStatusResponse.health_state` `Optional`.
- Zone matching (`edge/rules/modules.py::normalize_point`) is now resolution-independent and
  unit-tested end-to-end at two different frame sizes from the same config
  (`tests/unit/test_zone_normalization.py`) — closing a real bug where raw-pixel comparisons against
  an undefined coordinate unit would silently misbehave on any camera resolution other than whatever
  one the config happened to be authored against.
- The Hybrid Reliability Engine's filtering effect is measured, not just designed: on a real 795-frame
  test clip, it independently reduced 52 raw fence-crossing candidates to 23 (`docs/
  PERFORMANCE_REPORT.md`) — but see §1 above for what that same run does and does not show about the
  Event Verifier specifically.
- Evidence hashing (SHA-256), signing (Ed25519), and hash-chaining (append-only SQLite) are real
  cryptography, not placeholders — including tamper detection on chain verification.
- Evidence-at-rest encryption (AES-256-GCM) is real and active for every snapshot written to disk.
- Offline store-and-forward uses a real, durable SQLite queue with ordered, retry-on-failure upload —
  not an in-memory structure that would be lost on restart.
- Pipeline performance instrumentation (`edge/instrumentation/metrics.py`) measures real
  `time.perf_counter()` latency at every stage and real FPS from actual frame timestamps — CPU/RAM
  are real `psutil` readings when installed, `null` otherwise, never fabricated. No number in
  `docs/PERFORMANCE_REPORT.md` should ever be filled in by hand; only paste what this instrumentation
  actually printed.
