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

  // Bounding box logic
  let bboxStyle = {};
  let label = "";
  if (eventData && eventData.bbox) {
    // If bbox is [x, y, w, h] normalized 0-1
    const [x, y, w, h] = eventData.bbox;
    bboxStyle = {
      position: 'absolute',
      left: `${x * 100}%`,
      top: `${y * 100}%`,
      width: `${w * 100}%`,
      height: `${h * 100}%`,
      border: '2px solid var(--color-ok)',
      backgroundColor: 'rgba(74, 222, 128, 0.1)',
      zIndex: 10
    };
    label = `${eventData.detection_class.toUpperCase()} #${eventData.track_id || '---'} | ${(eventData.confidence * 100).toFixed(0)}% CONF`;
  } else {
    // Mock default bbox if connected but no specific event
    bboxStyle = {
      position: 'absolute',
      left: '30%',
      top: '20%',
      width: '20%',
      height: '60%',
      border: '2px solid var(--color-ok)',
      backgroundColor: 'rgba(74, 222, 128, 0.1)',
      zIndex: 10
    };
    label = "PERSON #184 | 91% CONF";
  }

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

      {/* Bounding Box */}
      <div style={bboxStyle}>
        <div className="absolute top-0 left-0 -translate-y-full bg-ok text-black text-xs font-display px-1 whitespace-nowrap">
          {label}
        </div>
      </div>
    </div>
  );
}
