import { CameraOff, CloudFog, AlertTriangle } from 'lucide-react';

// demoScenario: 'normal' | 'fog' | 'failure' | 'offline', from the Demo
// Scenario Control panel (hooks/useDemoScenario.js). Previously that panel's
// selection reached nothing outside itself — this is the fix for that: an
// honestly-labeled, client-side-only simulated overlay, never mixed into
// real eventData/isConnected so it can never be mistaken for a real
// edge-reported condition.
// camera_id is dynamically read from eventData to show the actual reporting
// camera (cam-border-01 or cam-checkpoint-01); falls back to 'cam-border-01'.
export default function VideoFeed({ eventData, isConnected, demoScenario = 'normal' }) {
  // eventData shape: { detection_class: 'person', confidence: 0.91, bbox: [x,y,w,h], track_id: '184', ... }

  if ((!isConnected && !eventData) || demoScenario === 'offline') {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-black border rounded relative overflow-hidden">
        <CameraOff size={48} className="text-muted mb-4 z-10" />
        <span className="text-muted font-display z-10">Simulated Feed (Disconnected)</span>
        {demoScenario === 'offline' && (
          <span className="text-[10px] text-danger border border-danger rounded px-1 mt-2 z-10">
            SIMULATED — Demo Scenario Control: Offline State
          </span>
        )}
        <div className="scanline"></div>
      </div>
    );
  }

  // Bounding box logic. NOTE: EventResponse (shared/schemas.py) — what
  // actually crosses the WebSocket — has no `bbox` field at all; it exists
  // only on the edge-internal EvidencePackage schema and never reaches the
  // frontend. So `eventData.bbox` was always undefined for every real
  // event, and this always fell to a hardcoded "PERSON #184 | 91% CONF"
  // placeholder box — drawn even while connected with zero real events yet
  // (the only guard was `!isConnected && !eventData`), so the very first
  // thing anyone saw on opening the dashboard was a fake, unconditional
  // "detection" that never happened. Fixed: the box (and its label) now
  // render only when a real eventData exists; connected-but-idle renders
  // no box at all. The box's on-screen position stays a fixed placeholder
  // region (no real pixel coordinates exist to draw it at without a real
  // video stream, which this project doesn't have), but it is never shown
  // without a real underlying event backing it.
  const bboxStyle = {
    position: 'absolute',
    left: '30%',
    top: '20%',
    width: '20%',
    height: '60%',
    border: '2px solid var(--color-ok)',
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
    zIndex: 10
  };
  const label = eventData
    ? `${eventData.detection_class.toUpperCase()} #${eventData.track_id ?? '---'} | ${(eventData.confidence * 100).toFixed(0)}% CONF`
    : null;

  return (
    <div className="w-full h-full relative bg-black border rounded overflow-hidden" style={{ backgroundImage: 'url(/mock-fence.jpg)', backgroundSize: 'cover', backgroundPosition: 'center' }}>
      
      {/* Fallback pattern if no image */}
      <div className="absolute inset-0 opacity-20" style={{
        backgroundImage: 'radial-gradient(var(--text-muted) 1px, transparent 1px)',
        backgroundSize: '20px 20px'
      }}></div>

      <div className="scanline"></div>

      {/* Demo Scenario Control overlays — client-side-only simulation, never
          derived from or mixed into real eventData. Distinct visual
          treatment per scenario so it reads as "simulated", not a real
          camera-health/scene-condition report. */}
      {demoScenario === 'fog' && (
        <div className="absolute inset-0 z-10" style={{ backgroundColor: 'rgba(200, 210, 220, 0.35)', backdropFilter: 'blur(2px)' }}></div>
      )}
      {demoScenario === 'failure' && (
        <div className="absolute inset-0 z-10 border-4 border-danger" style={{ boxShadow: 'inset 0 0 40px rgba(248,113,113,0.4)' }}></div>
      )}

      {/* Top badges */}
      <div className="absolute top-4 left-4 z-20 flex gap-2">
        {/* DEMO FEED badge — clearly not a live RTSP stream */}
        <div className="bg-panel text-warning text-xs px-2 py-1 rounded font-display border border-warning">
          DEMO FEED
        </div>
        <div className="bg-panel text-main text-xs px-2 py-1 rounded font-display border">
          {eventData?.camera_id || 'cam-border-01'}
        </div>
        {demoScenario === 'fog' && (
          <div className="bg-panel text-warning text-xs px-2 py-1 rounded font-display border border-warning flex items-center gap-1">
            <CloudFog size={12} /> SIMULATED: FOG_RAIN — IR fallback engaged
          </div>
        )}
        {demoScenario === 'failure' && (
          <div className="bg-panel text-danger text-xs px-2 py-1 rounded font-display border border-danger flex items-center gap-1">
            <AlertTriangle size={12} /> SIMULATED: SENSOR FAILURE
          </div>
        )}
      </div>

      <div className="absolute top-4 right-4 z-20">
        <span className="text-[10px] text-muted border rounded px-1 bg-dark">
          DEMO FEED — {eventData?.camera_id || 'cam-border-01'}
        </span>
      </div>

      {/* Bounding Box — only ever drawn for a real event; see label logic above. */}
      {eventData && (
        <div style={bboxStyle}>
          <div className="absolute top-0 left-0 -translate-y-full bg-ok text-black text-xs font-display px-1 whitespace-nowrap">
            {label}
          </div>
        </div>
      )}

      {!eventData && (
        <div className="absolute bottom-4 left-4 z-20 text-[10px] text-muted font-display uppercase tracking-widest">
          Monitoring — no active event
        </div>
      )}
    </div>
  );
}
