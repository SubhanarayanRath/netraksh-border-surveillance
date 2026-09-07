import { CheckCircle, Cloud, AlertCircle, WifiOff } from 'lucide-react';
import useDemoScenario from '../hooks/useDemoScenario';

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
// and the dead backend calls are removed rather than left silently failing.
export default function DemoSidebar() {
  const { scenario, setScenario } = useDemoScenario();

  const SimButton = ({ id, icon: Icon, title, desc }) => {
    const isActive = scenario === id;
    return (
      <button
        onClick={() => setScenario(id)}
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
        {/* This badge is now accurate: selecting a scenario really does
            simulate that state across the dashboard (VideoFeed, Header) —
            "Simulated" distinguishes it from a real edge-reported condition,
            not from "does nothing" as it did before. */}
        <span className="text-[10px] text-muted absolute top-2 right-2 border rounded px-1 border-color">Simulated</span>
      </button>
    );
  };

  return (
    <aside className="sidebar-right">
      <h3 className="text-sm text-muted font-body mb-6 border-b pb-4">Demo Scenario Control</h3>

      <SimButton id="normal" icon={CheckCircle} title="Normal Ops" desc="Optimal detection clarity" />
      <SimButton id="fog" icon={Cloud} title="Dense Fog" desc="Trigger IR fallback logic" />
      <SimButton id="failure" icon={AlertCircle} title="Sensor Failure" desc="Data integrity alert" />
      <SimButton id="offline" icon={WifiOff} title="Offline State" desc="Disconnected/Manual Override" />
    </aside>
  );
}
