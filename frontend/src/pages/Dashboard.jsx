import { useState, useEffect } from 'react';
import { ShieldCheck, HelpCircle, ShieldAlert, CheckCircle } from 'lucide-react';
import VideoFeed from '../components/VideoFeed';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL } from '../services/auth';

// Parses the REAL decision_reason string edge/reliability/decision.py writes,
// e.g. "R_ABOVE_THRESHOLD:R=0.907>=0.750 (D=0.80,T=0.85,S=0.93,H=1.00)" or
// "CAMERA_FAILED:frozen_stream" — the same four formats that function ever
// produces, not a guess at its shape. Returns null if reason is missing or
// doesn't match either format (never fabricates a fallback R/D/T/S/H).
function parseDecisionReason(reason) {
  if (!reason) return null;
  if (reason.startsWith('CAMERA_FAILED')) {
    return { kind: 'abstain', healthReason: reason.split(':')[1] || 'unknown' };
  }
  const rMatch = reason.match(/R=([\d.]+)\s*[<>]=?\s*([\d.]+)/);
  const factorMatch = reason.match(/D=([\d.]+),T=([\d.]+),S=([\d.]+),H=([\d.]+)/);
  if (!rMatch || !factorMatch) return null;
  return {
    kind: 'scored',
    r: parseFloat(rMatch[1]),
    threshold: parseFloat(rMatch[2]),
    aboveThreshold: reason.includes('R_ABOVE_THRESHOLD'),
    degraded: reason.includes('DEGRADED_CAMERA'),
    d: parseFloat(factorMatch[1]),
    t: parseFloat(factorMatch[2]),
    s: parseFloat(factorMatch[3]),
    h: parseFloat(factorMatch[4]),
  };
}

const SCENE_CONDITION_LABELS = {
  CLEAR_DAY: 'Clear Day',
  LOW_LIGHT_NIGHT: 'Night / Low-Light',
  FOG_RAIN: 'Fog / Rain',
  GLARE: 'Glare',
};

const DECISION_META = {
  DETECTED: { label: 'DETECTED', icon: ShieldCheck, colorClass: 'text-ok border-ok bg-[rgba(74,222,128,0.1)] glow-ok' },
  UNCERTAIN: { label: 'UNCERTAIN', icon: HelpCircle, colorClass: 'text-warning border-warning bg-[rgba(251,191,36,0.1)]' },
  ABSTAIN: { label: 'ABSTAIN', icon: ShieldAlert, colorClass: 'text-danger border-danger bg-[rgba(248,113,113,0.1)]' },
};

export default function Dashboard() {
  const { events, health } = useWebSocket(WS_URL);
  const [latestEvent, setLatestEvent] = useState(null);

  useEffect(() => {
    if (events.length > 0) {
      setLatestEvent(events[0]);
    }
  }, [events]);

  const parsed = latestEvent ? parseDecisionReason(latestEvent.decision_reason) : null;
  const healthState = latestEvent?.camera_health_state; // 'OK' | 'DEGRADED' | 'FAILED'
  const sceneCondition = latestEvent?.scene_condition;
  const decisionMeta = DECISION_META[latestEvent?.decision_state] || null;

  const StatusPill = ({ title, desc, type, active }) => {
    let colors = '';
    let icon = null;
    
    if (type === 'detected') {
      colors = active ? 'bg-ok text-black' : 'border border-ok text-ok opacity-50';
      icon = <CheckCircle size={20} />;
    } else if (type === 'uncertain') {
      colors = active ? 'bg-warning text-black' : 'border border-warning text-warning opacity-50';
      icon = <HelpCircle size={20} />;
    } else {
      colors = active ? 'bg-neutral text-white' : 'border border-neutral text-neutral opacity-50';
      icon = <HelpCircle size={20} />;
    }

    return (
      <div className={`flex flex-col p-4 rounded ${colors} transition-all ${active ? 'shadow-lg scale-105' : ''}`}>
        <div className="flex items-center gap-2 mb-1">
          {icon}
          <span className="font-display font-bold text-lg">{title}</span>
        </div>
        <span className="text-xs font-body opacity-80">{desc}</span>
      </div>
    );
  };

  const LogicGate = ({ num, title, stats, active }) => (
    <div className={`flex gap-4 p-4 rounded border ${active ? 'border-ok bg-[rgba(74,222,128,0.05)]' : 'border-color opacity-50'} relative`}>
      <div className="flex-shrink-0 mt-1">
        <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${active ? 'border-ok text-ok' : 'border-muted text-muted'}`}>
          {active && <CheckCircle size={12} />}
        </div>
      </div>
      <div className="flex flex-col w-full">
        <span className="text-sm font-display text-muted uppercase tracking-wider mb-2">Gate {num} — {title}</span>
        <div className="flex justify-between items-center bg-dark p-2 rounded border border-color">
          {stats}
        </div>
      </div>
      
      {/* Connecting line */}
      {num < 3 && <div className="absolute left-6 top-8 w-[2px] h-12 bg-border-color -z-10"></div>}
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase">Border Intelligence Center</h2>
        <span className="text-sm text-muted font-display tracking-widest uppercase">Active Monitoring Zone: Sector Alpha</span>
      </div>

      <div className="flex gap-6 h-[calc(100%-80px)]">
        
        {/* Left Column */}
        <div className="flex-col flex-[3] gap-4 h-full">
          <div className="flex-grow min-h-[400px]">
            <VideoFeed eventData={latestEvent} isConnected={true} />
          </div>

          <div className="bg-panel border rounded p-4 h-48 flex flex-col">
            <div className="flex justify-between items-center border-b border-color pb-2 mb-2">
              <span className="text-sm font-display text-muted uppercase tracking-widest">Event Timeline</span>
              <span className="text-xs text-ok border border-ok rounded px-2 py-1">WHY THIS ALERT?</span>
            </div>
            <div className="overflow-y-auto flex flex-col gap-2 flex-grow pr-2">
              {events.length === 0 ? (
                <div className="text-muted text-sm text-center mt-4">Waiting for events...</div>
              ) : (
                events.map((ev, i) => (
                  <div key={i} className="flex gap-4 text-sm font-body">
                    <span className="text-muted w-20">{new Date(ev.timestamp).toISOString().substring(11, 19)}</span>
                    <span className={i === 0 ? 'text-ok' : 'text-main'}>
                      {ev.decision_state === 'DETECTED' ? `Track #${ev.track_id || ''} established. Crossed virtual fence line.` : `Motion detected in Sector 4`}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right Column */}
        <div className="flex-col flex-[2] gap-4 h-full">
          <div className="bg-panel border rounded p-6 flex flex-col gap-6 flex-grow">
            <div className="flex justify-between items-start">
              <div className="flex-col">
                <span className="text-lg font-display text-main uppercase">Reliability Decision</span>
                <span className="text-xs font-display text-muted uppercase tracking-widest">Logic Pipeline</span>
              </div>
              <ShieldCheck size={24} className="text-muted" />
            </div>

            <div className="flex flex-col gap-4 relative">
              <LogicGate
                num={1} title="Camera Health (hard override)"
                active={!!latestEvent}
                stats={
                  healthState ? (
                    <>
                      <div className="flex-col"><span className="text-xs text-muted">STATE</span>
                        <span className={`text-sm ${healthState === 'OK' ? 'text-ok' : healthState === 'DEGRADED' ? 'text-warning' : 'text-danger'}`}>
                          {healthState}
                        </span>
                      </div>
                      {healthState === 'FAILED' && parsed?.kind === 'abstain' && (
                        <div className="flex-col"><span className="text-xs text-muted">REASON</span><span className="text-sm text-danger">{parsed.healthReason}</span></div>
                      )}
                    </>
                  ) : (
                    <span className="text-xs text-muted">Waiting for a real event…</span>
                  )
                }
              />
              <LogicGate
                num={2} title="Scene Condition"
                active={!!latestEvent}
                stats={
                  sceneCondition ? (
                    <>
                      <span className="text-xs text-muted">Illumination Profile</span>
                      <span className="text-xs border px-1 rounded bg-elevated">{SCENE_CONDITION_LABELS[sceneCondition] || sceneCondition}</span>
                    </>
                  ) : (
                    <span className="text-xs text-muted">Waiting for a real event…</span>
                  )
                }
              />
              <LogicGate
                num={3} title="Reliability Factors (R = 0.40·D + 0.20·T + 0.20·S + 0.20·H)"
                active={!!latestEvent}
                stats={
                  parsed?.kind === 'scored' ? (
                    <div className="flex-col w-full">
                      <div className="grid grid-cols-4 gap-2 w-full mb-2">
                        {[
                          ['D', parsed.d], ['T', parsed.t], ['S', parsed.s], ['H', parsed.h],
                        ].map(([label, value]) => (
                          <div key={label} className="flex-col items-center text-center">
                            <span className="text-xs text-muted block">{label}</span>
                            <span className="text-sm block">{value.toFixed(2)}</span>
                          </div>
                        ))}
                      </div>
                      <div className="flex justify-between w-full mb-1">
                        <span className="text-xs text-muted">R SCORE</span>
                        <span className="text-xs text-muted">THRESHOLD</span>
                      </div>
                      <div className="flex justify-between w-full">
                        <span className={`text-sm font-bold ${parsed.aboveThreshold ? 'text-ok' : 'text-warning'}`}>{parsed.r.toFixed(3)}</span>
                        <span className="text-sm">{parsed.threshold.toFixed(3)}</span>
                      </div>
                      <div className="w-full h-1 bg-dark mt-2 rounded overflow-hidden">
                        <div className={`h-full ${parsed.aboveThreshold ? 'bg-ok' : 'bg-warning'}`} style={{ width: `${Math.min(parsed.r * 100, 100)}%` }}></div>
                      </div>
                      {parsed.degraded && <span className="text-xs text-warning mt-1">Flagged: DEGRADED camera context</span>}
                    </div>
                  ) : parsed?.kind === 'abstain' ? (
                    <span className="text-xs text-muted">Gate 1 override — R was never computed for this event</span>
                  ) : (
                    <span className="text-xs text-muted">Waiting for a real event…</span>
                  )
                }
              />
            </div>

            <div className="mt-auto">
              {decisionMeta ? (
                <button className={`w-full border py-4 rounded font-display text-xl tracking-widest flex items-center justify-center gap-2 ${decisionMeta.colorClass}`}>
                  <decisionMeta.icon size={24} /> [{decisionMeta.label}]
                </button>
              ) : (
                <button className="w-full border border-color text-muted py-4 rounded font-display text-xl tracking-widest flex items-center justify-center gap-2 opacity-60">
                  <HelpCircle size={24} /> [AWAITING EVENT]
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <StatusPill 
              title="DETECTED" desc="Evidence Cryptographically Verified" 
              type="detected" active={latestEvent?.decision_state === 'DETECTED'} />
            <StatusPill 
              title="UNCERTAIN" desc="Confidence < Threshold" 
              type="uncertain" active={latestEvent?.decision_state === 'UNCERTAIN'} />
            <StatusPill 
              title="ABSTAIN" desc="System Unreliable" 
              type="abstain" active={latestEvent?.decision_state === 'ABSTAIN'} />
          </div>
        </div>

      </div>
    </div>
  );
}
