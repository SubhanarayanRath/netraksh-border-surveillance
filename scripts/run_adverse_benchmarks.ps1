$env:PYTHONPATH = "."

Write-Host "Running LOW_LIGHT Baseline (SIMULATE_NIGHT=true, ADVERSE_PROCESSING=disabled) on vtest.avi"
$env:SIMULATE_NIGHT_CONDITION="true"
$env:ADVERSE_PROCESSING="disabled"
venv\Scripts\python -m edge.benchmark_runner --video demo/videos/vtest.avi
Rename-Item -Path docs/benchmark_raw.json -NewName night_baseline.json -Force

Write-Host "Running LOW_LIGHT Candidate (SIMULATE_NIGHT=true, ADVERSE_PROCESSING=adaptive) on vtest.avi"
$env:SIMULATE_NIGHT_CONDITION="true"
$env:ADVERSE_PROCESSING="adaptive"
venv\Scripts\python -m edge.benchmark_runner --video demo/videos/vtest.avi
Rename-Item -Path docs/benchmark_raw.json -NewName night_candidate.json -Force

Write-Host "All benchmarks completed."
