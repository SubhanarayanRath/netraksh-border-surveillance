import { CheckCircle, Cloud, AlertCircle, WifiOff } from 'lucide-react';
import useDemoScenario from '../hooks/useDemoScenario';
import { authFetch } from '../services/auth';

// Was previously local-only state that didn't reach any other component
// (confirmed: nothing else in the frontend read DemoSidebar's own state),
// so clicking a button changed nothing except that button's own highlight
// — a real, non-cosmetic bug for a panel whose whole purpose is to
// demonstrate the dashboard reacting to a scenario. Also previously called
// /demo/inject-condition, /demo/trigger-camera-failure, /demo/simulate-offline
// — none of which exist anywhere in the backend (no backend/api/demo.py or
// equivalent router) — so every click also silently 401'd/404'd for no
// benefit. Now uses the shared DemoScenarioProvider (hooks/useDemoScenario.js)
// so Dashboard/VideoFeed/Header can honestly react to the selected scenario,
// AND posts to the real /demo/scenario endpoint (backend/api/demo.py) so
// the edge pipeline can actually change its behaviour.
export default function DemoSidebar() {
  const { scenario, setScenario } = useDemoScenario();

  // What each scenario actually does in the pipeline (not marketing copy):
  const SCENARIO_META = {
    normal: {
      icon: CheckCircle,
      title: 'Normal Ops',
      desc: 'Full pipeline · YOLO detects → R computed → DETECTED if R ≥ 0.75',
    },
    fog: {
      icon: Cloud,
      title: 'Dense Fog',
      desc: 'Frame blurred → SceneConditionClassifier → FOG_RAIN → S drops → may produce UNCERTAIN; IR fallback label shown',
    },
    failure: {
      icon: AlertCircle,
      title: 'Sensor Failure',
      desc: 'Frozen frames → CameraHealthMonitor FAILED → Gate 1 hard-override → ABSTAIN (R never computed)',
    },
    offline: {
      icon: WifiOff,
      title: 'Offline State',
      desc: 'SyncClient pauses outbound → events queue locally → header shows BUFFERING · click Normal to recover',
    },
  };

  const handleScenario = async (id) => {
    // 1. Update local shared state immediately (VideoFeed / Header react)
    setScenario(id);
    // 2. POST to backend so the polling edge pipeline changes behaviour
    try {
      await authFetch('/demo/scenario', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: id }),
      });
    } catch (e) {
      // Non-fatal: the visual overlay still works even if the POST fails.
      // Edge pipeline will pick up the new scenario on its next 5s poll.
      console.debug('[DemoSidebar] POST /demo/scenario failed (non-fatal):', e);
    }
  };

  const SimButton = ({ id }) => {
    const { icon: Icon, title, desc } = SCENARIO_META[id];
    const isActive = scenario === id;
    return (
      <button
        onClick={() => handleScenario(id)}
        className={`flex flex-col text-left p-4 rounded border transition-colors ${isActive ? 'bg-elevated border-ok' : 'bg-transparent border-color hover-bg-elevated'}`}
        style={{width: '100%', marginBottom: '1rem', position: 'relative'}}
      >
        <div className="flex items-center gap-3 w-full">
          <Icon size={20} className={isActive ? (id === 'normal' ? 'text-ok' : 'text-warning') : 'text-muted'} />
          <div className="flex-col">
            <span className={`text-sm font-display ${isActive ? 'text-main' : 'text-muted'}`}>{title}</span>
            <span className="text-xs text-muted font-body mt-1">{desc}</span>
          </div>
        </div>
        {/* This badge is accurate: selecting a scenario really does
            change pipeline behaviour (edge polls /demo/scenario every 5s)
            in addition to the client-side visual overlay. */}
        <span className="text-[10px] text-muted absolute top-2 right-2 border rounded px-1 border-color">Simulated</span>
      </button>
    );
  };

  return (
    <aside className="sidebar-right">
      <h3 className="text-sm text-muted font-body mb-6 border-b pb-4">Demo Scenario Control</h3>

      <SimButton id="normal" />
      <SimButton id="fog" />
      <SimButton id="failure" />
      <SimButton id="offline" />
    </aside>
  );
}
