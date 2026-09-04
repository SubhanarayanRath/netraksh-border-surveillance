import { CheckCircle, Cloud, AlertCircle, WifiOff } from 'lucide-react';
import { useState } from 'react';
import { authFetch } from '../services/auth';

export default function DemoSidebar() {
  const [activeSim, setActiveSim] = useState('normal');

  // NOTE: none of these /demo/* routes exist in the backend (confirmed —
  // there is no backend/api/demo.py or equivalent router). Every click here
  // always hits the catch below and falls back to the local "Simulated"
  // UI state only, which is exactly what the "Simulated" badge on each
  // button already discloses — this was not a hidden gap, just an
  // unimplemented one. See docs/LIMITATIONS.md.
  const handleTrigger = async (type) => {
    setActiveSim(type);
    try {
      if (type === 'normal') await authFetch('/demo/inject-condition?condition=CLEAR', {method: 'POST'});
      if (type === 'fog') await authFetch('/demo/inject-condition?condition=FOG', {method: 'POST'});
      if (type === 'failure') await authFetch('/demo/trigger-camera-failure', {method: 'POST'});
      if (type === 'offline') await authFetch('/demo/simulate-offline', {method: 'POST'});
    } catch (e) {
      console.warn("Demo endpoint failed, using local simulation state fallback");
    }
  };

  const SimButton = ({ id, icon: Icon, title, desc }) => {
    const isActive = activeSim === id;
    return (
      <button 
        onClick={() => handleTrigger(id)}
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
        {/* Mock fallback badge */}
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
