import { CameraOff } from 'lucide-react';

export default function VideoFeed({ eventData, isConnected }) {
  // eventData shape: { detection_class: 'person', confidence: 0.91, bbox: [x,y,w,h], track_id: '184', ... }
  
  if (!isConnected && !eventData) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-black border rounded relative overflow-hidden">
        <CameraOff size={48} className="text-muted mb-4 z-10" />
        <span className="text-muted font-display z-10">Simulated Feed (Disconnected)</span>
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

      {/* Top badges */}
      <div className="absolute top-4 left-4 z-20 flex gap-2">
        <div className="bg-danger text-white text-xs px-2 py-1 rounded font-display flex items-center gap-1">
          <div className="w-2 h-2 bg-white rounded-full animate-pulse"></div> LIVE
        </div>
        <div className="bg-panel text-main text-xs px-2 py-1 rounded font-display border">
          CAM-07 | NORTH FENCE
        </div>
      </div>

      <div className="absolute top-4 right-4 z-20">
        <span className="text-[10px] text-muted border rounded px-1 bg-dark">Simulated Feed</span>
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
