"""
NETRAKSH — Demo Scenario API (local prototype only).

GET  /demo/scenario  — return current active scenario
POST /demo/scenario  — set active scenario

No authentication required — this endpoint exists exclusively for the
local SIH prototype demo.  It MUST NOT be included in any non-local
deployment (see docs/LIMITATIONS.md).

Scenario values (matching the frontend DemoSidebar):
  'normal'  — full-pipeline nominal operation
  'fog'     — simulated FOG_RAIN scene condition (natural image degradation)
  'failure' — simulated camera failure → Gate 1 FAILED → ABSTAIN
  'offline' — simulated network loss → sync client queues locally

The edge pipeline polls GET /demo/scenario every 5 s and reacts:
  * failure → CameraAdapter simulate_frozen=True → CameraHealthMonitor
              detects frozen stream → health_state=FAILED → Gate 1
              hard-override → decision_state=ABSTAIN
  * fog     → CameraAdapter applies Gaussian blur + contrast reduction
              so SceneConditionClassifier naturally classifies FOG_RAIN
              and S drops; R is not hardcoded
  * offline → SyncClient pauses its outbound POST loop; events continue
              to accumulate in the local SQLite queue (existing behaviour)
  * normal  → no modifications; all simulation flags cleared
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/demo", tags=["demo"])

# ---------------------------------------------------------------------------
# In-memory scenario state — a plain dict so any import of this module
# shares the same object.  Resets to 'normal' on each server restart.
# ---------------------------------------------------------------------------
_state: dict = {"scenario": "normal"}

_VALID_SCENARIOS = frozenset({"normal", "fog", "failure", "offline"})


@router.get("/scenario")
async def get_scenario():
    """Return the currently active demo scenario."""
    return {"scenario": _state["scenario"]}


@router.post("/scenario")
async def set_scenario(payload: dict):
    """
    Set the active demo scenario.  Accepts { "scenario": "<value>" }.
    Unknown values are silently ignored (scenario stays unchanged) so a
    stale frontend tab cannot break a running demo.
    """
    requested = payload.get("scenario", "normal")
    if requested in _VALID_SCENARIOS:
        _state["scenario"] = requested
    return {"scenario": _state["scenario"]}
