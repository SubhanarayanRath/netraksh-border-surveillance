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
| Synthetic night (real video, real Gaussian-darkened frames) | 51 | 21 (41%) | 30 (59%) |
| Synthetic fog (real video, real haze-blended + blurred frames) | 52 | 37 (71%) | 15 (29%) |

**These fog numbers are AFTER a real fix** (see `docs/LIMITATIONS.md`'s Hybrid Reliability Engine
entry and `edge/reliability/decision.py::_health_quality_score`) — the original, first-measured result
was 0/52 (0%) DETECTED under fog, i.e. every single genuine crossing marked UNCERTAIN. Diagnosis: two
supposedly-independent factors were actually double-counting the same real signal — `S` (scene
quality) genuinely drops because fog reduces contrast, **and** `H` (health quality) was *also* dropping
to 0.5 because the same real blur that simulates fog haze genuinely trips the Camera Health Monitor's
Laplacian blur detector into a DEGRADED reading. That reading is correct in isolation (the frame really
is blurrier), but H's actual purpose is to flag a broken/dirty/defocused *camera* — not weather the
scene classifier already has its own dedicated signal for. The fix: `_health_quality_score` now scores
H as healthy (1.0) specifically when health is DEGRADED for `EXCESSIVE_BLUR` *and* the scene is already
independently classified `FOG_RAIN` or `LOW_LIGHT_NIGHT` — any other DEGRADED reason (frozen stream,
abnormal exposure, FPS drop, clock drift, stream unavailable), or blur during `CLEAR_DAY`, still fully
penalizes H exactly as before (see `tests/unit/test_reliability.py::TestWeatherExplainedBlurDoesNotDoublePenalize`
for the four cases this locks in). Re-running the same real collection + labeling on this fixed formula
raised fog from 0% to 71% DETECTED — real, substantial, honestly measured. Night's numbers are
unchanged (21/51 both before and after) because the night transform never happened to trip
`EXCESSIVE_BLUR` in this dataset, so there was nothing for this specific fix to change there.

**What this does NOT mean:** it does not mean fog detection is now "solved" — 29% of genuine crossings
under this specific fog intensity are still marked UNCERTAIN, which is a real, honest, remaining gap
(this fix removed a proven double-penalty; it did not lower the bar for the genuinely-still-present
single penalty from `S`). It also does not mean the fog transform's specific intensity
(`cv2.addWeighted` at 0.42/0.58 plus a 7×7 Gaussian blur) is representative of every real fog condition
NETRAKSH might face — a lighter haze would show a better result, a heavier one worse, and this project
has no real fog footage to calibrate the transform's intensity against either (see
`docs/LIMITATIONS.md`). This is real, open, partially-addressed work, not a fully solved one.

## Honesty checklist before this goes in the PPT

- [x] Every number above came from a JSON file this run actually produced (`docs/PERFORMANCE_REPORT_MEASURED.json`), not estimated
- [x] The machine/hardware is stated exactly, and no number is presented as if measured on different hardware
- [x] The false-positive-reduction claim is NOT asserted — the honest result (no measured reduction on this clip) is reported instead of a more convenient-sounding number
- [x] The video source is disclosed as a generic public test clip, not the team's actual demo footage — do not imply otherwise in the deck
- [ ] Re-run against real staged demo footage before final submission, and update this file from that run
