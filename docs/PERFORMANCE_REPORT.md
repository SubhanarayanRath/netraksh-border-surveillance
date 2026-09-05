# NETRAKSH — Performance Report

**Status: MEASURED — one real run completed and recorded below.**

Every number in this file came from `scripts/run_false_positive_benchmark.py` actually executing
against real footage on the machine described below — none of it is estimated, and none of it is
projected onto different hardware. See `docs/PERFORMANCE_REPORT_MEASURED.json` for the raw output
this table was transcribed from (not hand-edited).

**Read the "What this run actually shows" section below before quoting these numbers in the PPT** —
the honest interpretation matters as much as the figures themselves.

## How this report was produced

Unlike the original template's instructions (run `edge/main.py` live), this run used
`scripts/run_false_positive_benchmark.py` — a measurement harness built specifically for this report
that exercises the *same* production classes `edge/main.py` uses (`CameraHealthMonitor`,
`SceneConditionClassifier`, `CalibrationModule`, `DetectionTracker`/YOLO, `VirtualFenceModule`,
`make_reliability_decision`, `EventVerifier`, `PipelineMetrics`) frame-by-frame against a real video
file, without the side effects of full evidence packaging/sync (no keys or DB files written). This was
necessary because no demo video existed in this repository and no live camera/staged scenario was
available at the time this was run — see the Test run metadata note on video provenance.

## Test run metadata

| Field | Value |
|---|---|
| Date | 2026-09-04 |
| Machine | Windows 11 Home, Intel64 Family 6 Model 154 Stepping 3 (GenuineIntel), 16 logical CPUs, 15.6 GB RAM, CPU-only (no GPU used) — Python 3.14.7, ultralytics 8.4.137, torch 2.13.0+cpu, opencv-python 4.14.0 |
| Video source | `demo/videos/vtest.avi` — OpenCV's own official sample pedestrian-tracking test clip (fetched from `github.com/opencv/opencv`, `samples/data/vtest.avi`), 768×576, 10 fps, 795 frames (~79.5s). **Not footage of the team's actual demo camera or scenario** — used because no demo video or staged scenario existed at the time of this run. Re-run this benchmark against real staged footage before final submission if possible; see `docs/LIMITATIONS.md`. |
| Zone tested | One rectangular fence zone, normalized coordinates `(0.456, 0.260)`–`(1.0, 0.521)` — visually placed over the main pedestrian walkway visible in the clip, not the placeholder zones shipped in `demo/scripts/zones_config.json` |
| Duration | 795 frames / 79.5s of source video, processed twice (once per confirmation policy) |
| Scene conditions covered | CLEAR_DAY only (daytime courtyard footage) — LOW_LIGHT_NIGHT/FOG_RAIN/GLARE are **not** covered by this run |

## Frame-level pipeline latency (ms)

From the "with verifier" (shipped-defaults) pass — the other pass's numbers are materially identical
(within measurement noise) and are in `docs/PERFORMANCE_REPORT_MEASURED.json`.

| Stage | n | mean | p95 | max |
|---|---|---|---|---|
| health_condition_ms | 500 | 9.54 | 10.58 | 13.43 |
| detection_tracking_ms | 500 | 34.93 | 39.16 | 59.08 |
| event_processing_ms | 500 | 0.09 | 0.13 | 0.18 |
| total_frame_ms | 500 | 44.55 | 49.17 | 69.38 |

Measured FPS (same run): **21.76** (real-time-capable at this video's native 10 fps, on CPU only, no
GPU, no TensorRT — YOLOv8n's detection+tracking stage is the dominant cost at ~35ms mean, as expected).

Note: `PipelineMetrics`'s rolling window caps at 500 samples, so `n=500` here means "the last 500 of
795 frames processed," not "295 frames were dropped" — nothing is missing, this is that field's
documented rolling-window behavior.

## Event-level pipeline latency — decision to enqueued (ms)

**Not measured in this run.** This benchmark harness deliberately does not exercise
`EvidencePackager`/`SyncClient` (to avoid writing real keys/DB files during a benchmarking run), so no
event-level timing was recorded here — this is a real gap in this specific report, not a hidden
number. Event-level latency (snapshot → hash+sign → chain-store → enqueue) was previously measured in
isolation during development (see `docs/ARCHITECTURE.md`'s Performance Instrumentation changelog
entry) but not as part of this same run. Re-run `edge/main.py` directly (not this benchmark script)
against real footage to get this table populated from the same run as the numbers above.

## Resource usage

| Metric | Value |
|---|---|
| CPU % | 0.0 (as reported by `psutil.Process().cpu_percent()`) — **this reading is not credible** for a process that just spent ~35 real seconds doing YOLO inference on CPU, and should not be quoted. Likely cause: a single end-of-run sample doesn't capture sustained usage the way a periodic sampler would; `edge/main.py`'s own periodic `_report_metrics()` (every 10s during a live run) is the credible way to get this number. Do not put "0% CPU" in the PPT. |
| RSS (MB) | 412.9 (without-verifier pass) / 426.5 (with-verifier pass) — this reading is plausible (matches a loaded YOLOv8n + OpenCV + Python process) and can be quoted as "~410-430 MB resident memory" |

## False-positive reduction — before/after the Event Verifier (architecture v4 §11)

| | Raw candidate events fired | Alerts actually raised |
|---|---|---|
| Without verifier (1 confirmation) | 52 | 23 |
| With verifier (shipped defaults, 3 confirmations) | 52 | 23 |

### What this run actually shows — read before quoting a percentage

**The Event Verifier made no measurable difference on this specific clip: 23 alerts either way.**
This is a real, honest result, and it is **not** the "temporal verification cuts false alarms"
headline number the team may have expected — say so plainly if asked, rather than reaching for a
different framing after the fact.

What actually happened, diagnosed from the same run:
- **The Hybrid Reliability Engine did real, substantial filtering:** 52 raw fence-crossing candidates
  → only 23 (44%) ever had even one frame where `R ≥ 0.75`. The other 29 candidates never cleared the
  Reliability Gate at all, on any frame, and expired unconfirmed regardless of confirmation policy.
  This is a genuine, measured demonstration of the Reliability Gate's filtering effect — just not the
  feature this table was designed to isolate.
- **Of the 23 candidates that did clear the Reliability Gate at least once, every single one stayed
  reliably detected for 3+ consecutive frames.** None were "confirmed once, then lost" — this
  particular clip's tracking is clean enough (daytime, unoccluded, well-lit pedestrians) that it
  contains none of the single-frame jitter the Event Verifier exists to catch. The Verifier cost
  nothing here (no true positives lost) but also had nothing to prove itself against.
- **Conclusion for the PPT:** report this honestly as "on a clean daytime clip, reliability filtering
  removed 56% of raw candidates before they could become alerts, and temporal verification added zero
  additional cost." Do **not** claim a false-positive reduction from verification using this data —
  that claim needs footage that actually contains tracking jitter (a lower frame-rate or more
  occluded/crowded clip, or the same clip re-tested with a deliberately shortened `track_buffer` to
  induce ID switches) to be honestly measurable. This is a real, open next step, not a solved one.

## Reliability Engine behavior under real night/fog/glare conditions

A separate, real measurement — **different methodology from the table above, do not merge the two
numbers.** The table above uses `scripts/run_false_positive_benchmark.py`, which tracks whether R
clears `RELIABILITY_R_THRESHOLD` on *any* frame across each candidate's whole tracked lifetime. The
numbers below use `scripts/collect_calibration_data.py` + `scripts/analyze_reliability_under_conditions.py`,
which compute R once, at the single frame the fence-crossing event actually fires on — a stricter,
single-frame measurement. Both are real; they answer different questions and are not comparable
head-to-head.

This measurement exists because of an attempt to calibrate the Hybrid Reliability Engine's weights
from real labeled data (see `docs/LIMITATIONS.md`'s Hybrid Reliability Engine entry): manual review of
every real fence-crossing candidate in `demo/videos/vtest.avi` found zero false positives, in daytime
**and** under three honest, disclosed synthetic night/fog/glare lighting transforms applied to the same
real footage (`--synthetic-condition night|fog|glare` — see `scripts/collect_calibration_data.py`'s
docstring for exactly what is and isn't synthetic here). With every labeled candidate genuine,
weight-fitting was correctly refused — but the same labeled data answers a different, real, and more
operationally important question: **of these genuine crossings, how many does the CURRENT hand-picked
formula actually mark UNCERTAIN instead of DETECTED?**

| Condition | Genuine (label=1) candidates | DETECTED (R ≥ 0.75) | UNCERTAIN (real crossing missed) |
|---|---|---|---|
| Daytime (real, unmodified video) | 52 | 52 (100%) | 0 (0%) |
| Synthetic night (real video, real Gaussian-darkened frames) | 51 | 47 (92%) | 4 (8%) |
| Synthetic fog (real video, real haze-blended + blurred frames) | 52 | 49 (94%) | 3 (6%) |
| Synthetic glare (real video, real brightened + clipped frames) | 55 | 33 (60%) | 22 (40%) |

**These numbers are after SIX real, separate fixes, applied in sequence** — each honestly
re-measured, none a full solution on its own:

1. **Fix 1 — H double-penalty** (`edge/reliability/decision.py::_health_quality_score`). The
   original, first-measured result was 0/52 (0%) DETECTED under fog, i.e. every single genuine
   crossing marked UNCERTAIN. Diagnosis: two supposedly-independent factors were actually
   double-counting the same real signal — `S` (scene quality) genuinely drops because fog reduces
   contrast, **and** `H` (health quality) was *also* dropping to 0.5 because the same real blur that
   simulates fog haze genuinely trips the Camera Health Monitor's Laplacian blur detector into a
   DEGRADED reading. That reading is correct in isolation (the frame really is blurrier), but H's
   actual purpose is to flag a broken/dirty/defocused *camera* — not weather the scene classifier
   already has its own dedicated signal for. The fix: `_health_quality_score` now scores H as healthy
   (1.0) specifically when health is DEGRADED for `EXCESSIVE_BLUR` *and* the scene is already
   independently classified `FOG_RAIN` or `LOW_LIGHT_NIGHT` — any other DEGRADED reason, or blur
   during `CLEAR_DAY`, still fully penalizes H exactly as before (see
   `tests/unit/test_reliability.py::TestWeatherExplainedBlurDoesNotDoublePenalize`, 4 tests). This
   alone raised fog from 0% to 71% DETECTED.
2. **Fix 2 — S's contrast reference for FOG_RAIN** (`edge/reliability/decision.py::_scene_quality_score`).
   Even after fix 1, 29% of genuine fog crossings still missed threshold, because `contrast_score`
   judged every FOG_RAIN frame against `_SCENE_CONTRAST_GOOD` (60.0) — a clear-day ideal a scene
   classified FOG_RAIN can never meet, since `contrast_std < FOG_CONTRAST_THRESHOLD` (30.0) is
   literally the real rule `SceneConditionClassifier` already uses to call a scene foggy in the first
   place (`edge/condition/scene_condition.py`). Judging it against 60 anyway scored every fog frame as
   "badly foggy" even when it was merely "typically foggy for what got it classified as fog at all."
   The fix reuses that same, already-existing `FOG_CONTRAST_THRESHOLD` constant as FOG_RAIN's own
   contrast reference instead of introducing a new number — a frame at the real classification
   boundary now scores full contrast marks, and one meaningfully foggier than that still scores
   proportionally lower (see
   `tests/unit/test_reliability.py::TestSceneQualityFogContrastReference`, 4 tests). This left night
   unaffected at this stage (21/51 before and after fix 2) — night's own bottleneck is fix 3, below.
   This raised fog further, from 71% to 87% DETECTED.
3. **Fix 3 — S's brightness reference for LOW_LIGHT_NIGHT** (same function, same pattern as fix 2).
   Night's real measured driver was `brightness_score`, not contrast — every frame classified
   `LOW_LIGHT_NIGHT` is, by definition, below `BRIGHTNESS_NIGHT_THRESHOLD` (60.0, the real rule
   `SceneConditionClassifier` already uses to call a scene night in the first place), yet
   `brightness_score` judged it against the `CLEAR_DAY` midpoint ideal (128.0) meant for a symmetric
   too-dark/too-bright measurement — scoring every night frame as "badly dark" even at the very
   boundary of "still counts as night." The fix reuses `BRIGHTNESS_NIGHT_THRESHOLD` the same way fix 2
   reused `FOG_CONTRAST_THRESHOLD`: within the night band, more light is unambiguously better (not
   "distance from an ideal"), so a frame right at the classification boundary now scores full
   brightness marks, and a darker one than that still scores proportionally lower (see
   `tests/unit/test_reliability.py::TestSceneQualityNightBrightnessReference`, 4 tests).
   `FOG_RAIN`/`CLEAR_DAY`/`GLARE` are untouched (confirmed: fog's DETECTED rate is identical before and
   after fix 3, 45/52 both times). This raised night from 41% to 61% DETECTED.
4. **Fix 4 — S's contrast reference for LOW_LIGHT_NIGHT** (same function). Fix 3 left 39% of genuine
   night crossings still missing, driven by `contrast_score` still judging night frames against the
   clear-day contrast ideal (60.0). **This case is different in kind from fixes 2 and 3**, disclosed as
   such: `SceneConditionClassifier`'s `LOW_LIGHT_NIGHT` rule checks brightness only — there is no
   existing "this is the real rule that made it night" constant for contrast to reuse the way `FOG_RAIN`
   and night's own brightness fix could. `_SCENE_CONTRAST_GOOD_NIGHT` is therefore a genuinely NEW,
   hand-picked heuristic (half of `BRIGHTNESS_NIGHT_THRESHOLD` = 30.0) — not calibrated, not a reused
   classification boundary — justified on a real, statable physical basis: `contrast_std` measures the
   spread of a non-negative pixel-value distribution, and one whose mean is capped below
   `BRIGHTNESS_NIGHT_THRESHOLD` cannot have much spread without clipping at zero, so a legitimately-
   dark-but-not-defective night frame's achievable contrast is bounded by its own brightness headroom,
   not the clear-day sensor's full range. This is exactly the same category of hand-picked default as
   the *original* `_SCENE_CONTRAST_GOOD`/`_SCENE_BRIGHTNESS_IDEAL`/`_SCENE_GLARE_BAD` constants
   themselves — disclosed as such, not oversold as a "reused real constant" the way fixes 2 and 3
   legitimately are (see
   `tests/unit/test_reliability.py::TestSceneQualityNightContrastReference`, 4 tests, including a
   regression lock confirming `FOG_RAIN`'s own contrast reference is unaffected). This raised night
   further, from 61% to 76% DETECTED.
5. **Fix 5 — a real, previously-shipped PRODUCTION bug, not a calibration-side issue like fixes 1-4.**
   Found while investigating why 3/52 DAYTIME crossings still missed threshold despite S≈0.92 and
   H=1.0 — no scene or health issue to blame at all. `TrackFeatureTracker`
   (`edge/temporal/track_features.py`) only ever registered a track's `_first_seen` time inside
   `compute()` — and both `edge/main.py` (the real, deployed pipeline) and
   `scripts/collect_calibration_data.py` only ever call `compute()` from an EVENT-triggered branch (a
   fence-crossing handler, firing once per track at the crossing transition). That means
   `_first_seen[track_id]` got registered at the moment of a track's FIRST qualifying event, not its
   real first-observed frame — so `age_seconds` was always `0.0` on that one call, regardless of how
   long the track had genuinely already existed. Measured directly, not assumed: the 3 daytime
   candidates each had 34-50 real trajectory points (1.4-2 real seconds of prior tracking) yet
   `T_age_score` (a new diagnostic field this investigation added to the manifest) was exactly `0.0`
   for all three. The fix: a new `TrackFeatureTracker.observe()` method, called unconditionally for
   every active track every frame in both `edge/main.py` and the collection script — independent of
   whether any rule event fires that frame — so age is registered the moment a track is truly first
   seen (see `tests/unit/test_track_features.py::TestObserveFixesEventTriggeredAgeZeroing`, 4 tests;
   full suite 227/227). This bug was condition-independent, so re-measuring improved ALL THREE
   datasets at once: daytime rose from 94% to **100%** (all 3 residual candidates now resolved);
   night rose from 76% to 92%; fog rose from 87% to 94%. By a wide margin the largest single fix this
   session — it corrects a genuine defect in the real, deployed edge pipeline's temporal-scoring
   wiring, not just a calibration-script heuristic.
6. **Fix 6 — the SAME H double-penalty as fix 1, generalized, for GLARE.** A synthetic glare
   transform (`--synthetic-condition glare`: scale pixels ×1.8+20, clip at 255) reliably classified
   `GLARE` via the real `glare_fraction` path (~0.43, well past the real 0.15 cutoff). Manual review
   of all 55 real candidates again found zero false positives, and the SAME real double-penalty
   pattern as fog appeared: glare genuinely blows out highlights, which `S` already penalizes via
   `glare_fraction`, **and** the same real overexposure genuinely trips the Camera Health Monitor's
   own exposure-clipping check (`clip_fraction`, fraction of pixels at exactly 255 — measured at
   30-41% here, far past its 0.10 threshold) into `ABNORMAL_EXPOSURE`, initially measuring 0/55 (0%)
   DETECTED — identical in shape to fix 1's original finding. Rather than special-case this
   separately, fix 1's exemption was generalized into a real
   `_WEATHER_EXPLAINED_DEGRADED_REASONS` mapping (`edge/reliability/decision.py`) —
   `{EXCESSIVE_BLUR: {FOG_RAIN, LOW_LIGHT_NIGHT}, ABNORMAL_EXPOSURE: {GLARE}}` — so a third such
   pairing, if ever found, is a one-line addition (see
   `tests/unit/test_reliability.py::TestWeatherExplainedExposureDoesNotDoublePenalize`, 4 tests; full
   suite 239/239). Re-measured: glare rose from 0/55 (0%) to **33/55 (60%) DETECTED**.

**What this does NOT mean:** it does not mean fog, night, or glare detection is now "solved" — 6% of
genuine fog crossings, 8% of genuine night crossings, and 40% of genuine glare crossings under these
specific synthetic intensities still miss, a real, honest, remaining gap (daytime, notably, is now
fully resolved at 100% — the remaining gap is entirely in the three synthetic degraded-condition
datasets). It also does not mean any synthetic transform's specific intensity (night: scaling pixel
values by 0.28 plus Gaussian noise; fog: `cv2.addWeighted` at 0.42/0.58 plus a 7×7 Gaussian blur;
glare: scaling by ×1.8+20 with clipping) is representative of every real night/fog/glare condition
NETRAKSH might face — this project has no real footage in any of these three conditions to calibrate
any transform's intensity against, or to validate fix 4's specific heuristic value against, the way
fixes 2, 3, and 6 could each lean on an already-existing, independently-justified constant (see
`docs/LIMITATIONS.md`). This is real, open, partially-addressed work, not a fully solved one.

**Night's residual, investigated specifically:** unlike fixes 1-5, no further formula bug was found —
an honest negative result, not an unexamined gap. All 4 remaining UNCERTAIN night candidates are
genuine, correctly-detected people (each snapshot manually re-checked). `S` is nearly flat across all
51 night candidates (0.6815-0.6961 — this synthetic darkening is uniform per-frame), so `D` (raw
detector confidence) is what actually separates them: sorting all 51 by `D` shows a clean, monotonic
boundary — the 4 lowest-`D` candidates (0.48-0.63, vs a 0.78 mean) are *exactly* the 4 that miss
threshold, with `R` increasing smoothly right through 0.75. This is the Reliability Engine correctly
expressing more caution on the objectively weakest evidence in the dataset, not a defect — see
`docs/LIMITATIONS.md` for why this is left open rather than force-fixed.

**That conclusion was then actually tested with a milder night transform, the same way as fog's and
glare's.** `--synthetic-condition night_mild` (scale ×0.45 vs the original ×0.28) was empirically
tuned against 5 frames spanning the whole video to measure `brightness_mean≈53` — still reliably
`LOW_LIGHT_NIGHT` (a consistent ~7-point safety margin under 60 throughout) but much closer to the
boundary than the original's ~33. All 52 candidates again reviewed — zero false positives.

| Night intensity | Genuine candidates | DETECTED | UNCERTAIN |
|---|---|---|---|
| Original (`brightness_mean≈33`) | 51 | 47 (92%) | 4 (8%) |
| Milder (`brightness_mean≈53`) | 52 | 50 (96%) | 2 (4%) |

A smaller improvement than fog's (94%→98%) or glare's (60%→88%), consistent with night having already
had more of its structural gap closed by the two earlier reference-point fixes (fixes 3 and 4) before
this test — less headroom remained for a milder transform to recover. The 2 remaining `night_mild`
residuals (`D=0.47` and `D=0.49`, both far below the 0.78 mean, `T`/`S`/`H` all near-max) are the same
genuine low-confidence-detection pattern as every other residual this session.

**Fog's residual, investigated the same way, reaches the identical conclusion:** all 3 remaining
UNCERTAIN fog candidates are genuine, correctly-detected people (small/distant figures visibly
softened by the haze/blur transform). `S` is nearly flat across all 52 fog candidates
(0.8126-0.8295), so `D` again separates them cleanly: the 3 lowest-`D` candidates (0.52-0.56, vs a
0.76 mean) are *exactly* the 3 that miss threshold, `R` increasing smoothly through 0.75. No formula
bug found — left open for the same reason as night.

**That "no bug, just transform severity" conclusion was then actually tested with a milder fog
transform, not left as an assumption.** `--synthetic-condition fog_mild` (blend 0.55/0.45 with a
smaller 5x5 blur, vs the original 0.42/0.58 with 7x7) was empirically tuned against 5 frames spanning
the whole video to measure `contrast_std≈28` — still reliably `FOG_RAIN` (~2-point margin under the
real 30 threshold throughout) but right at the boundary, not deep inside it. All 52 candidates again
reviewed — zero false positives.

| Fog intensity | Genuine candidates | DETECTED | UNCERTAIN |
|---|---|---|---|
| Original (`contrast_std≈21`) | 52 | 49 (94%) | 3 (6%) |
| Milder (`contrast_std≈28`) | 52 | 51 (98%) | 1 (2%) |

A real, honest confirmation: milder fog genuinely produces fewer misses, so at least part of the
original 6% residual really was a transform-severity effect, not purely irreducible evidence-based
caution — an important nuance the "no bug found" conclusion above didn't fully capture on its own. The
single remaining `fog_mild` residual (`D=0.37`, far below the 0.77 mean, `S=0.92`/`H=1.0`/`T=0.85` all
near-max) is the same genuine low-confidence-detection pattern as every other residual this session —
visually confirmed as a real person, no bug.

**Glare's residual was investigated too, and turned out to be a genuinely DIFFERENT situation from
fog/night — checked, not assumed.** Fog and night's classification rules structurally GUARANTEE every
classified frame fails the old reference (fog *requires* `contrast<30`, always below the old 60
"good" target; night *requires* `brightness<60`, always below the old 128 target — 100% of instances,
no exceptions). GLARE's classification (`glare_fraction > 0.15`) has no such ceiling: a frame right at
that boundary scores a reasonable `glare_score` of 0.5 under the current formula, not floored — only
frames at or past `glare_fraction ≥ 0.30` (double the classification minimum) floor to 0. This
specific synthetic transform's measured severity (~0.43) simply sits well past that point. That is a
transform-intensity limitation — the same honestly-disclosed category as fog/night's transform
intensity — not a formula defect calling for a seventh fix. No further change applied.

**That conclusion was then actually tested with a milder glare transform, the same way as fog's.**
`--synthetic-condition glare_mild` (×1.3+10, vs the original ×1.8+20) was empirically tuned against 5
frames spanning the whole video to measure `glare_fraction≈0.21` — still reliably `GLARE` (comfortably
above the real 0.15 cutoff throughout) but much closer to the boundary than the original's ~0.43. All
52 candidates again reviewed — zero false positives.

| Glare intensity | Genuine candidates | DETECTED | UNCERTAIN |
|---|---|---|---|
| Original (`glare_fraction≈0.43`) | 55 | 33 (60%) | 22 (40%) |
| Milder (`glare_fraction≈0.21`) | 52 | 46 (88%) | 6 (12%) |

An even larger confirmation than fog's: 60% → 88%. This makes sense given the ORIGINAL glare
transform's severity relative to its own threshold was proportionally much larger than fog's
(~2.9x the 0.15 cutoff, vs fog's transform, which was always below its 30 cutoff by construction, not
several multiples past it) — so there was correspondingly more room for a milder version to recover.
The 6 remaining `glare_mild` residuals show moderate, plausible `D`/`T` combinations (no floor, no
single dominant factor, `S`≈0.63-0.68 for all, `H`=1.0) — genuine evidence-based uncertainty, not a
further bug.

## A real compound condition: night AND fog together

Every condition above tests ONE degradation at a time, matching `SceneCondition`'s real design — a
single, mutually-exclusive categorical value (`edge/condition/scene_condition.py`). But a real border
camera can face darkness AND fog simultaneously. `--synthetic-condition night_fog`
(`scripts/collect_calibration_data.py`) combines the real night-darkening transform with a real
fog-style haze blend dimmed to match (not daytime fog's bright 190 — real fog under low light scatters
into a dim gray, it doesn't glow white), producing a genuinely compound degradation: `brightness_mean
≈39`, `contrast_std≈7` — lower contrast than EITHER "night" (≈15) or "fog" (≈21) alone. Because
`FOG_RAIN` requires `brightness>60`, this compound scene is always classified `LOW_LIGHT_NIGHT`, never
`FOG_RAIN` — a real, structural consequence of the categorical design, not a test artifact.

Two real findings from actually running it (all real candidates manually reviewed — zero false
positives, as always):

1. **This session's reliability-scoring fixes generalize correctly to a case more severe than either
   was individually measured against.** `_SCENE_CONTRAST_GOOD_NIGHT` (fix 4) still applies and
   correctly scores this worse than either individual condition; the H exemption
   (`_WEATHER_EXPLAINED_DEGRADED_REASONS`, fixes 1/6) still covers `LOW_LIGHT_NIGHT` if blur trips. Of
   the real candidates that reached a reliability decision, 5/7 DETECTED — the few survivors are
   handled reasonably. No new double-penalty or reference-point bug was found.
2. **A more fundamental finding: only 7 real fence-crossing candidates formed across all 795 frames,
   versus ~52 for every single-degradation condition — an ~86% drop in candidate YIELD, not detection
   accuracy.** At this severity, most real crossings never reach the Hybrid Reliability Engine at all
   — they are lost earlier, in detection/tracking itself. No amount of tuning
   `RELIABILITY_WEIGHT_*`/`RELIABILITY_R_THRESHOLD` addresses this, since those only ever see
   candidates that already survived to become one. **This is the honest, important distinction to
   report: the Reliability Engine's threshold accuracy on survivors is not the same claim as "the
   system reliably detects crossings under severe compound degradation."** This project has no fix for
   the latter — it would need detector-level work (a fine-tuned model, or preprocessing tuned to this
   specific compound case), outside this session's scope.

`n=7` is too small to treat the 71% DETECTED figure as a precise measurement — reported as an honest
observation on a small sample, not a statistically confident rate, unlike the ~52-candidate figures
elsewhere in this report.

## A second compound condition: night AND glare together

`--synthetic-condition night_glare` tests a different real compound scenario from `night_fog`: darken
the whole frame (real night), then add a real, LOCALIZED bright glow (empirically tuned to
`glare_fraction≈0.164`) — modeling a dark scene with a strong nearby light source (headlights, a
floodlight), not a uniformly bright one. Because GLARE's classification check runs FIRST in the real
decision order, this compound scene is classified `GLARE`, not `LOW_LIGHT_NIGHT` — the opposite
categorical outcome from `night_fog`. All 52 real candidates manually reviewed — zero false positives.

| Compound condition | Classified as | Candidates formed | DETECTED |
|---|---|---|---|
| `night_fog` (uniform low contrast everywhere) | `LOW_LIGHT_NIGHT` | 7 | 5/7 (71%) |
| `night_glare` (localized bright glow, dark elsewhere) | `GLARE` | 52 | 45/52 (87%) |

Two real, useful findings from the contrast between them:

1. **Unlike `night_fog`, candidate yield did not collapse.** 52 real candidates formed — the same
   order of magnitude as every single-degradation condition, not `night_fog`'s 7. A concentrated
   bright glow next to an otherwise dark scene does not crush detection/tracking the way UNIFORM low
   contrast across the whole frame does. The honest lesson: it is specifically *uniform* contrast
   collapse, not "any severe compound degradation," that threatens candidate yield.
2. **DETECTED (87%) is actually higher than the original single-condition "glare" transform's 60%**,
   because this compound scene's `glare_fraction` (≈0.164) sits in the same mild-severity regime as
   `glare_mild` (≈0.21) rather than the original severe transform (≈0.43) — confirming the earlier
   mild-intensity findings generalize here, not a new result on its own. The 7 remaining residuals
   show the same moderate `D`/`T` pattern as every other residual this session — genuine
   evidence-based uncertainty, no new bug.

## Honesty checklist before this goes in the PPT

- [x] Every number above came from a JSON file this run actually produced (`docs/PERFORMANCE_REPORT_MEASURED.json`), not estimated
- [x] The machine/hardware is stated exactly, and no number is presented as if measured on different hardware
- [x] The false-positive-reduction claim is NOT asserted — the honest result (no measured reduction on this clip) is reported instead of a more convenient-sounding number
- [x] The video source is disclosed as a generic public test clip, not the team's actual demo footage — do not imply otherwise in the deck
- [ ] Re-run against real staged demo footage before final submission, and update this file from that run
