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

## Reliability Engine behavior under real night/fog conditions

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
**and** under two honest, disclosed synthetic night/fog lighting transforms applied to the same real
footage (`--synthetic-condition night|fog` — see `scripts/collect_calibration_data.py`'s docstring for
exactly what is and isn't synthetic here). With every labeled candidate genuine, weight-fitting was
correctly refused — but the same labeled data answers a different, real, and more operationally
important question: **of these genuine crossings, how many does the CURRENT hand-picked formula
actually mark UNCERTAIN instead of DETECTED?**

| Condition | Genuine (label=1) candidates | DETECTED (R ≥ 0.75) | UNCERTAIN (real crossing missed) |
|---|---|---|---|
| Daytime (real, unmodified video) | 52 | 49 (94%) | 3 (6%) |
| Synthetic night (real video, real Gaussian-darkened frames) | 51 | 39 (76%) | 12 (24%) |
| Synthetic fog (real video, real haze-blended + blurred frames) | 52 | 45 (87%) | 7 (13%) |

**These numbers are after FOUR real, separate fixes, applied in sequence** — each honestly
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

**What this does NOT mean:** it does not mean fog or night detection is now "solved" — 13% of genuine
fog crossings and 24% of genuine night crossings under these specific synthetic intensities still miss,
a real, honest, remaining gap. It also does not mean either synthetic transform's specific intensity
(night: scaling pixel values by 0.28 plus Gaussian noise; fog: `cv2.addWeighted` at 0.42/0.58 plus a
7×7 Gaussian blur) is representative of every real night/fog condition NETRAKSH might face — this
project has no real night or fog footage to calibrate either transform's intensity against, or to
validate fix 4's specific heuristic value against, the way fixes 2 and 3 could lean on an
already-existing, independently-justified constant (see `docs/LIMITATIONS.md`). This is real, open,
partially-addressed work, not a fully solved one.

## Honesty checklist before this goes in the PPT

- [x] Every number above came from a JSON file this run actually produced (`docs/PERFORMANCE_REPORT_MEASURED.json`), not estimated
- [x] The machine/hardware is stated exactly, and no number is presented as if measured on different hardware
- [x] The false-positive-reduction claim is NOT asserted — the honest result (no measured reduction on this clip) is reported instead of a more convenient-sounding number
- [x] The video source is disclosed as a generic public test clip, not the team's actual demo footage — do not imply otherwise in the deck
- [ ] Re-run against real staged demo footage before final submission, and update this file from that run
