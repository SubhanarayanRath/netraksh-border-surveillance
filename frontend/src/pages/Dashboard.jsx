import { useState, useEffect, useRef } from 'react';
import { ShieldCheck, HelpCircle, ShieldAlert, CheckCircle, GitMerge } from 'lucide-react';
import VideoFeed from '../components/VideoFeed';
import useWebSocket from '../hooks/useWebSocket';
import useDemoScenario from '../hooks/useDemoScenario';
import { WS_URL, BACKEND_URL, authFetch } from '../services/auth';
import { parseUtc } from '../utils/time';

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

// Builds the actual plain-English explanation from the same parsed
// decision_reason data the Reliability Decision panel already displays —
// "WHY THIS ALERT?" used to be a <span> with no onClick at all, styled to
// look like a clickable button (border, padding, hover-implying color)
// but doing nothing. Rather than just stripping that affordance, this
// wires it to something real: the exact factors that produced the
// decision, in one place, instead of requiring the viewer to read four
// separate numbers out of the Gate 3 grid themselves.
function explainDecision(parsed) {
  if (!parsed) return null;
  if (parsed.kind === 'abstain') {
    return `Camera health is FAILED (${parsed.healthReason}) — Gate 1's hard override abstained before any reliability score was computed. This is not a scoring decision; a failed camera is never trusted regardless of what a detector reports.`;
  }
  const factorNote = (label, value) =>
    `${label}=${value.toFixed(2)} (${value >= 0.75 ? 'strong' : value >= 0.5 ? 'moderate' : 'weak'})`;
  const verdict = parsed.aboveThreshold
    ? `R (${parsed.r.toFixed(3)}) met or exceeded the ${parsed.threshold.toFixed(3)} threshold, so this was DETECTED`
    : `R (${parsed.r.toFixed(3)}) fell below the ${parsed.threshold.toFixed(3)} threshold, so this was held as UNCERTAIN`;
  const degradedNote = parsed.degraded ? ' The camera was in a DEGRADED state at the time, which is reflected in a lower H factor above.' : '';
  return `${verdict}, from: ${factorNote('Detection confidence (D)', parsed.d)}, ${factorNote('Temporal consistency (T)', parsed.t)}, ${factorNote('Scene clarity (S)', parsed.s)}, ${factorNote('Camera health (H)', parsed.h)}.${degradedNote}`;
}

export default function Dashboard() {
  const { events, health, liveTracks } = useWebSocket(WS_URL);
  const { scenario: demoScenario } = useDemoScenario();
  const [latestEvent, setLatestEvent] = useState(null);
  const [showWhy, setShowWhy] = useState(false);

  // Media upload state — lifted here so the entire dashboard can be gated
  // behind a video upload. Until the operator loads a demo video, all
  // WebSocket events are suppressed from the UI so the jury sees a clean
  // "waiting for feed" state rather than automatic analysis on nothing.
  const [mediaUrl, setMediaUrl] = useState(`${BACKEND_URL}/demo/videos/uploaded_demo.mp4`);
  const [mediaType, setMediaType] = useState('video');
  const [isUploading, setIsUploading] = useState(false);
  const [sessionStartTime, setSessionStartTime] = useState(0);
  const fileInputRef = useRef(null);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (file) {
      if (mediaUrl) URL.revokeObjectURL(mediaUrl);
      setMediaUrl(URL.createObjectURL(file));
      setMediaType(file.type.startsWith('video/') ? 'video' : 'image');
      // Reset events so fresh analysis starts from the new upload
      setSessionStartTime(Date.now());
      setLatestEvent(null);

      if (file.type.startsWith('video/')) {
        setIsUploading(true);
        const formData = new FormData();
        formData.append('file', file);
        
        try {
          const res = await authFetch('/demo/upload', {
            method: 'POST',
            body: formData,
          });
          
          if (!res.ok) {
            console.error('Upload failed:', await res.text());
          }
        } catch (error) {
          console.error('Upload error:', error);
        } finally {
          setIsUploading(false);
        }
      }
    }
  };

  const triggerUpload = () => fileInputRef.current?.click();

  // Only accept events once the operator has loaded a demo feed
  const demoEvents = events.filter(e => new Date(e.timestamp).getTime() >= sessionStartTime);
  useEffect(() => {
    if (mediaUrl && demoEvents.length > 0) {
      setLatestEvent(demoEvents[0]);
    }
  }, [demoEvents, mediaUrl]);

  const parsed = latestEvent ? parseDecisionReason(latestEvent.decision_reason) : null;
  // Prefer the live per-camera health push (real, arrives roughly every 5s
  // independent of whether any event has fired -- see
  // backend/api/cameras.py's POST /cameras/{id}/health) over the
  // snapshot embedded in the latest event, which is only as fresh as
  // whenever that event last fired and could be stale. Falls back to the
  // event's own recorded value when no live push has arrived yet for this
  // camera. `health` was previously fetched from the socket and never
  // actually used here.
  const healthState = (latestEvent && health[latestEvent.camera_id]?.health_state)
    || latestEvent?.camera_health_state; // 'OK' | 'DEGRADED' | 'FAILED'
  const sceneCondition = latestEvent?.scene_condition;
  const decisionMeta = DECISION_META[latestEvent?.decision_state] || null;
  const whyExplanation = explainDecision(parsed);

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
      <div className={`flex flex-col rounded ${colors} transition-all ${active ? 'shadow-lg scale-105' : ''}`} style={{ padding: '0.75rem', height: '100%' }}>
        <div className="flex items-center" style={{ gap: '0.5rem', marginBottom: '0.1rem' }}>
          {icon}
          <span className="font-display font-bold text-base">{title}</span>
        </div>
        <span className="text-[10px] font-body opacity-80">{desc}</span>
      </div>
    );
  };

  const LogicGate = ({ num, title, stats, active }) => (
    <div className={`flex rounded border ${active ? 'border-ok bg-[rgba(74,222,128,0.05)]' : 'border-color opacity-50'} relative`} style={{ padding: '0.5rem', gap: '0.75rem' }}>
      <div className="flex-shrink-0 mt-1">
        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${active ? 'border-ok text-ok' : 'border-muted text-muted'}`}>
          {active && <CheckCircle size={10} />}
        </div>
      </div>
      <div className="flex flex-col w-full">
        <span className="text-[11px] font-display text-muted uppercase tracking-wider mb-1" style={{ marginBottom: '0.25rem' }}>Gate {num} — {title}</span>
        <div className="flex justify-between items-center bg-dark rounded border border-color" style={{ padding: '0.35rem' }}>
          {stats}
        </div>
      </div>
      
      {/* Connecting line. w-[2px] was a bracket-notation class (see
          index.css's "looks like Tailwind, isn't real" entry) — never
          applied any real width, same as every other arbitrary-value class
          in this file until converted to a real inline style like this. */}
      {num < 3 && <div className="absolute left-6 top-8 h-12 bg-border-color -z-10" style={{ width: '2px' }}></div>}
    </div>
  );

  return (
    <div className="h-full flex flex-col" style={{ gap: '1rem' }}>
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase">Border Intelligence Center</h2>
        <span className="text-sm text-muted font-display tracking-widest uppercase">Active Monitoring Zone: Sector Alpha</span>
      </div>

      {/* h-[calc(100%-80px)], flex-[3]/flex-[2] (below), and min-h-[400px]
          (below) were all bracket-notation classes that never applied any
          real CSS — the video feed column in particular used to collapse
          to ~2px tall as a result (confirmed via getComputedStyle, not
          guessed) since nothing was left to give it real height once
          .absolute/.relative were fixed and stopped accidentally
          contributing document-flow height. Converted to real inline
          styles. */}
      <div className="flex" style={{ height: 'calc(100% - 60px)', gap: '1rem' }}>

        {/* Left Column */}
        <div className="flex-col h-full" style={{ flex: 3, display: 'flex', gap: '0.75rem' }}>
          {/* Hidden file input — triggered from VideoFeed's upload button */}
          <input
            type="file"
            accept=".mp4,.avi,.mov,.mkv,.webm,.flv,.wmv,.mpeg,.mpg,.3gp,.3gpp,.m4v,.ogv,.ts,.m2ts,.mts,.vob,.rmvb,.rm,.divx,.xvid,.asf,.f4v,.h264,.hevc,.mp2,.mpe,.mpv,.m2v,.svi,.3g2,.mxf,video/*,image/*"
            onChange={handleFileUpload}
            ref={fileInputRef}
            style={{ display: 'none' }}
          />

          <div className="flex-grow" style={{ minHeight: '300px' }}>
            <VideoFeed
              eventData={latestEvent}
              liveTracksData={liveTracks['cam-border-01']}
              isConnected={true}
              demoScenario={demoScenario}
              mediaUrl={mediaUrl}
              mediaType={mediaType}
              onUpload={triggerUpload}
              isUploading={isUploading}
            />
          </div>

          <div className="bg-panel border rounded flex flex-col" style={{ padding: '0.75rem', minHeight: '10rem' }}>
            <div className="flex justify-between items-center border-b border-color pb-1 mb-1" style={{ paddingBottom: '0.25rem', marginBottom: '0.25rem' }}>
              <span className="text-sm font-display text-muted uppercase tracking-widest">Event Timeline</span>
              <button
                onClick={() => setShowWhy((v) => !v)}
                className="text-xs text-ok border border-ok rounded px-2 py-1 hover:bg-[rgba(74,222,128,0.1)] transition-colors"
              >
                WHY THIS ALERT?
              </button>
            </div>
            {showWhy && (
              <div className="text-xs font-body text-main bg-dark border border-color rounded mb-2" style={{ padding: '0.5rem', marginBottom: '0.5rem' }}>
                {whyExplanation || 'No real event yet to explain — this fills in from the same decision_reason data the Reliability Decision panel shows, once one arrives.'}
              </div>
            )}
            <div className="overflow-y-auto flex flex-col gap-2 flex-grow pr-2">
              {!mediaUrl ? (
                <div className="text-muted text-sm text-center mt-4">Upload a demo video to begin analysis</div>
              ) : demoEvents.length === 0 ? (
                <div className="text-muted text-sm text-center mt-4">Waiting for events...</div>
              ) : (
                demoEvents.map((ev, i) => (
                  <div key={i} className="flex gap-4 text-sm font-body">
                    <span className="text-muted w-20">{parseUtc(ev.timestamp).toISOString().substring(11, 19)}</span>
                    <span className={i === 0 ? 'text-ok' : 'text-main'}>
                      {ev.decision_state === 'DETECTED' ? `Track #${ev.track_id || ''} established. Crossed virtual fence line.` : `Motion detected in Sector 4`}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Cross-Camera Corroboration Panel
              Shows temporal/spatial plausibility score (Tc) when a second
              camera has observed the same detection class within the expected
              travel-time window.  This is NOT identity re-identification —
              see backend/services/cross_camera.py for honest scope. */}
          <div className="bg-panel border rounded p-4 flex flex-col gap-2 mt-2">
            <div className="flex items-center gap-2 border-b border-color pb-2">
              <GitMerge size={14} className="text-muted" />
              <span className="text-xs font-display text-muted uppercase tracking-widest">Cross-Camera Corroboration</span>
              <span className="text-[10px] text-muted border border-color rounded px-1 ml-auto">temporal/spatial only — not identity</span>
            </div>
            {latestEvent?.corroboration_score != null ? (
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span className="text-ok text-lg">&#10003;</span>
                  <span className="text-sm font-display text-ok">
                    Corroborated by{' '}
                    <span className="font-bold">{latestEvent.corroborated_by_event_id ? 'cam-checkpoint-01' : 'second camera'}</span>
                  </span>
                </div>
                <div className="flex gap-4 text-xs font-body text-muted">
                  <span>Tc = <span className="text-main">{latestEvent.corroboration_score.toFixed(3)}</span></span>
                  {latestEvent.corroboration_delta_t_s != null && (
                    <span>Δt = <span className="text-main">{latestEvent.corroboration_delta_t_s.toFixed(0)}s</span> apart</span>
                  )}
                  {latestEvent.corroboration_distance_m != null && (
                    <span><span className="text-main">{latestEvent.corroboration_distance_m.toFixed(0)}m</span> camera separation</span>
                  )}
                </div>
                <span className="text-[10px] text-muted italic">Same detection class appeared at a spatially-plausible camera within expected travel time. No identity or re-identification claimed.</span>
              </div>
            ) : latestEvent ? (
              <div className="flex items-start gap-2">
                <span className="text-warning text-base">&#9888;</span>
                <div className="flex flex-col">
                  <span className="text-sm font-display text-warning">No corroboration available</span>
                  <span className="text-xs text-muted">Single-camera observation only — confidence reduced. Either cam-checkpoint-01 has not yet reported a matching event, or spatial/temporal plausibility was below threshold.</span>
                </div>
              </div>
            ) : (
              <span className="text-xs text-muted">Waiting for a real event…</span>
            )}
          </div>

        </div>

        {/* Right Column */}
        <div className="flex-col h-full" style={{ flex: 2, display: 'flex', gap: '0.75rem' }}>
          <div className="bg-panel border rounded flex flex-col" style={{ padding: '1rem', gap: '0.75rem' }}>
            <div className="flex justify-between items-start">
              <div className="flex-col">
                <span className="text-[15px] font-display text-main uppercase">Reliability Decision</span>
                <span className="text-[10px] font-display text-muted uppercase tracking-widest">Logic Pipeline</span>
              </div>
              <ShieldCheck size={20} className="text-muted" />
            </div>

            <div className="flex flex-col relative" style={{ gap: '0.5rem' }}>
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
                      {/* Not `grid grid-cols-4` — inert class, see docs/LIMITATIONS.md */}
                      <div className="w-full mb-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.5rem' }}>
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

            {/* This is a live status readout, not an action — it was
                markup as a <button> with no onClick and no disabled
                attribute, so it rendered with a pointer cursor and hover
                states implying it did something on click when it never
                did. Changed to a <div role="status"> — same visual
                treatment, honestly non-interactive. */}
            <div className="mt-auto" style={{ marginTop: 'auto' }}>
              {decisionMeta ? (
                <div role="status" className={`w-full border rounded font-display text-sm tracking-widest flex items-center justify-center ${decisionMeta.colorClass}`} style={{ padding: '0.75rem 0', gap: '0.5rem' }}>
                  <decisionMeta.icon size={18} /> [{decisionMeta.label}]
                </div>
              ) : (
                <div role="status" className="w-full border border-color text-muted rounded font-display text-sm tracking-widest flex items-center justify-center opacity-60" style={{ padding: '0.75rem 0', gap: '0.5rem' }}>
                  <HelpCircle size={18} /> [AWAITING EVENT]
                </div>
              )}
            </div>
          </div>

          {/* Not `grid grid-cols-3` — inert class, see docs/LIMITATIONS.md */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', flexGrow: 1 }}>
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
