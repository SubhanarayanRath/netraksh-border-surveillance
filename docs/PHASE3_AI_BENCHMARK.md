# NETRAKSH Phase 3 AI Benchmark

*Generated on: Sun Sep 20 15:49:49 2026*

## 1. Environment
- **OS**: win32
- **Python**: 3.11.7
- **Hardware**: NOT MEASURED

## 2. Input Data
- **Resolution**: 768x576
- **Source FPS**: 10.0
- **Frames Processed**: 90 (excl. 10 warmup)

## 3. Current Baseline Configuration
- **Detector**: yolov8n.pt
- **Tracker**: default

## 4. Detection Metrics
- **Mean Detector+Tracker Latency**: 77.14 ms (p95: 163.21 ms)
- **Effective FPS**: 13.0
- **Total Objects Detected**: 625
- **Pixel-Area Categories**: Small (<32x32): 21 | Medium: 604 | Large (>96x96): 0
- **Precision/Recall**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 5. Tracking Metrics
- **Tracker Used**: bytetrack
- **Continuity Guard Enabled**: True
- **Tracks Created**: 24
- **Tracks Terminated**: 20
- **Continuity Guard Interventions (Fragmentation Proxy)**: 11
- **Average Track Lifetime**: 48.1 frames
- **Median Track Lifetime**: 39.0 frames
- **Peak Active Tracks**: 9
- **IDF1/MOTA/ID Switches**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 6. Face Metrics
- **Face Processing Latency**: Included in Orchestrator
- **Matches/Unknowns**: 0
- **ROC/Accuracy**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 7. ANPR Metrics
- **OCR Latency**: Included in Orchestrator
- **OCR Attempts**: 180
- **Exact-Match Rate**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 7.5 Behavioral Intelligence
- **Behavior Correlation Latency**: 0.00 ms
- **Events Generated**: NOT TRACKED IN BENCHMARK HARNESS YET

## 8. Reliability Metrics
- **Mean Processing Latency**: 0.03 ms
- **R (Final Score) Mean**: 0.00

## 9. Scene-Condition Metrics
- **Mean Latency**: 6.32 ms

## 10. End-to-End Metrics
- **Mean Latency**: 83.55 ms (p95: 173.15 ms)
- **Mean Effective Throughput**: 12.0 FPS

## 11. Memory Metrics
- **RSS Before**: 635.26 MB
- **RSS Peak During**: 723.16 MB
- **RSS After**: 719.66 MB

## 12. Ground-Truth Availability
NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 13. Metrics that are NOT MEASURABLE
- Precision, Recall, mAP, IDF1, MOTA, ID Switches, True OCR Accuracy, Face Recognition ROC are all **NOT MEASURABLE** at this time due to lack of ground truth labels for the evaluated videos.

## 14. Known Benchmark Limitations
- Face and ANPR latencies are grouped under Orchestrator latency due to current architecture coupling.
- No ground truth datasets currently exist in the repository to measure True Positives vs False Positives.

## 15. Reproduction Command
```bash
python -m edge.benchmark_runner --video <path_to_video>
```
