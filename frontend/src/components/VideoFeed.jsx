import { CameraOff, CloudFog, AlertTriangle, Upload, Play } from 'lucide-react';
import { useMemo, useState, useEffect, useRef } from 'react';

// demoScenario: 'normal' | 'fog' | 'failure' | 'offline'
// activeEvents: array of recent EventResponse objects. VideoFeed renders one
// bbox per unique track_id using real bbox_x/y/w/h (never fabricated).
export default function VideoFeed({ eventData, liveTracksData, activeEvents = [], isConnected, demoScenario = 'normal', mediaUrl, mediaType, onUpload, isUploading }) {

  const TRACK_COLORS = [
    { border: '#4ade80', bg: 'rgba(74,222,128,0.12)', label: '#000' },
    { border: '#60a5fa', bg: 'rgba(96,165,250,0.12)', label: '#000' },
    { border: '#fbbf24', bg: 'rgba(251,191,36,0.12)',  label: '#000' },
    { border: '#f87171', bg: 'rgba(248,113,113,0.12)', label: '#fff' },
    { border: '#c084fc', bg: 'rgba(192,132,252,0.12)', label: '#fff' },
    { border: '#fb923c', bg: 'rgba(251,146,60,0.12)',  label: '#000' },
    { border: '#22d3ee', bg: 'rgba(34,211,238,0.12)',  label: '#000' },
    { border: '#f472b6', bg: 'rgba(244,114,182,0.12)', label: '#fff' },
  ];
  const getTrackColor = (trackId) => TRACK_COLORS[Math.abs(trackId ?? 0) % TRACK_COLORS.length];

  // Most recent event per unique track_id
const containerRef = useRef(null);
  const videoRef = useRef(null);
  const [videoRect, setVideoRect] = useState({ left: 0, top: 0, width: 0, height: 0 });
  const [renderTrigger, setRenderTrigger] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setRenderTrigger(v => v + 1), 200);
    return () => clearInterval(timer);
  }, []);

  const activeLiveTracks = useMemo(() => {
    if (!liveTracksData || !liveTracksData.tracks) return [];
    if (Date.now() - liveTracksData.timestamp > 500) return []; // Stale
    return liveTracksData.tracks;
  }, [liveTracksData, renderTrigger]);

  useEffect(() => {
    const updateRect = () => {
      const container = containerRef.current;
      const video = videoRef.current;
      if (!container || !video) return;
      
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      const vw = video.videoWidth || video.naturalWidth || cw;
      const vh = video.videoHeight || video.naturalHeight || ch;

      if (vw === 0 || vh === 0) return;

      const containerRatio = cw / ch;
      const videoRatio = vw / vh;

      let renderedWidth = cw;
      let renderedHeight = ch;
      let left = 0;
      let top = 0;

      if (containerRatio > videoRatio) {
        renderedWidth = cw;
        renderedHeight = cw / videoRatio;
        top = (ch - renderedHeight) / 2;
      } else {
        renderedHeight = ch;
        renderedWidth = ch * videoRatio;
        left = (cw - renderedWidth) / 2;
      }
      
      setVideoRect({ left, top, width: renderedWidth, height: renderedHeight });
    };

    updateRect();
    const ro = new ResizeObserver(updateRect);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [mediaUrl, renderTrigger]);

  // Disable old activeTracks logic for overlays
  const legacyActiveTracks = useMemo(() => {
    const events = activeEvents && activeEvents.length > 0 ? activeEvents : (eventData ? [eventData] : []);
    const byTrack = new Map();
    events.forEach(ev => { if (ev.track_id != null && !byTrack.has(ev.track_id)) byTrack.set(ev.track_id, ev); });
    return Array.from(byTrack.values());
  }, [activeEvents, eventData]);

  if (demoScenario === 'offline') {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-black border rounded relative overflow-hidden">
        <CameraOff size={48} className="text-muted z-10" style={{ marginBottom: '1rem' }} />
        <span className="text-muted font-display z-10">Simulated Feed (Disconnected)</span>
        <div className="scanline"></div>
      </div>
    );
  }

  if (isUploading) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center border rounded relative overflow-hidden"
        style={{ background: 'radial-gradient(circle at 50% 50%, #0c1a13 0%, #020617 100%)' }}>
        <div style={{ width: '60px', height: '60px', borderRadius: '50%', border: '3px solid transparent', borderTopColor: 'var(--color-ok)', animation: 'spin 1s linear infinite' }}></div>
        <span className="font-display font-bold text-main mt-16" style={{ letterSpacing: '0.1em' }}>UPLOADING TO PIPELINE...</span>
        <div className="scanline"></div>
      </div>
    );
  }

  if (!mediaUrl) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center border rounded relative overflow-hidden"
        style={{ background: 'radial-gradient(circle at 50% 50%, #0c1a13 0%, #020617 100%)', cursor: 'pointer' }}
        onClick={onUpload}>
        <div className="flex flex-col items-center z-10" style={{ gap: '1rem' }}>
          <div style={{ width: '64px', height: '64px', borderRadius: '50%', background: 'rgba(74,222,128,0.15)', border: '2px solid rgba(74,222,128,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Upload size={28} style={{ color: 'var(--color-ok)' }} />
          </div>
          <span className="font-display font-bold text-main" style={{ fontSize: '1rem', letterSpacing: '0.1em' }}>LOAD DEMO VIDEO</span>
          <div style={{ background: 'var(--color-ok)', color: '#000', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '0.75rem', letterSpacing: '0.1em', padding: '0.6rem 1.5rem', borderRadius: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Play size={14} />UPLOAD DEMO MEDIA
          </div>
        </div>
        <div className="absolute" style={{ top: '1rem', left: '1rem' }}>
          <span className="bg-panel text-warning text-xs px-2 py-1 rounded font-display border border-warning">AWAITING FEED</span>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full h-full relative border rounded overflow-hidden" style={{ background: 'radial-gradient(circle at 50% 50%, #064e3b 0%, #020617 100%)', boxShadow: 'inset 0 0 50px rgba(0,0,0,0.8)' }}>

      {mediaType === 'video'
        ? <video ref={videoRef} onLoadedMetadata={() => setRenderTrigger(v=>v+1)} src={mediaUrl} autoPlay loop muted style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
        : <img ref={videoRef} onLoad={() => setRenderTrigger(v=>v+1)} src={mediaUrl} alt="Demo Feed" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
      }

      <div className="scanline" style={{ zIndex: 2 }}></div>
      {demoScenario === 'fog' && <div className="absolute inset-0" style={{ backgroundColor: 'rgba(200,210,220,0.35)', backdropFilter: 'blur(2px)', zIndex: 3 }}></div>}
      {demoScenario === 'failure' && <div className="absolute inset-0 border-4 border-danger" style={{ boxShadow: 'inset 0 0 40px rgba(248,113,113,0.4)', zIndex: 3 }}></div>}

      {/* Top badges */}
      <div className="absolute flex gap-2 flex-wrap" style={{ top: '1rem', left: '1rem', zIndex: 20 }}>
        <div className="bg-panel text-ok text-xs px-2 py-1 rounded font-display border border-ok" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-ok)', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }}></span>LIVE ANALYSIS
        </div>
        <div className="bg-panel text-main text-xs px-2 py-1 rounded font-display border">{eventData?.camera_id || 'cam-border-01'}</div>
        {activeLiveTracks.length > 0 && <div className="bg-panel text-xs px-2 py-1 rounded font-display border" style={{ color: 'var(--color-ok)' }}>{activeLiveTracks.length} TRACK{activeLiveTracks.length !== 1 ? 'S' : ''} ACTIVE</div>}
        {demoScenario === 'fog' && <div className="bg-panel text-warning text-xs px-2 py-1 rounded font-display border border-warning flex items-center gap-1"><CloudFog size={12} />SIMULATED: FOG_RAIN</div>}
        {demoScenario === 'failure' && <div className="bg-panel text-danger text-xs px-2 py-1 rounded font-display border border-danger flex items-center gap-1"><AlertTriangle size={12} />SIMULATED: SENSOR FAILURE</div>}
      </div>

      {/* ===== REAL BOUNDING BOXES (one per unique active track_id) =====
          bbox_x/y/w/h are normalized [0,1] real YOLO coordinates.
          If bbox is unavailable for a historical event, no box is drawn.  */}
      {activeLiveTracks.map((ev) => {
        const color = getTrackColor(ev.track_id);
        if (ev.bbox_x == null || ev.bbox_y == null || ev.bbox_w == null || ev.bbox_h == null) return null;
        const lbl = `TRACK #${ev.track_id ?? '?'} | ${ev.detection_class?.toUpperCase() ?? 'UNKNOWN'} ${ev.confidence != null ? (ev.confidence * 100).toFixed(1) + '%' : ''}`;
        return (
          <div key={ev.track_id} style={{
            position: 'absolute', 
            left: `${videoRect.left + (ev.bbox_x * videoRect.width)}px`, 
            top: `${videoRect.top + (ev.bbox_y * videoRect.height)}px`,
            width: `${ev.bbox_w * videoRect.width}px`, 
            height: `${ev.bbox_h * videoRect.height}px`,
            border: `2px solid ${color.border}`, backgroundColor: color.bg,
            zIndex: 10, boxShadow: `0 0 8px ${color.border}60`, transition: 'all 0.1s linear',
          }}>
            <div style={{ position: 'absolute', top: 0, left: 0, transform: 'translateY(-100%)', background: color.border, color: color.label, fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '0.6rem', letterSpacing: '0.07em', padding: '1px 5px', whiteSpace: 'nowrap', lineHeight: 1.6 }}>{lbl}</div>
            <div style={{ position: 'absolute', top: -2, left: -2, width: 10, height: 10, borderTop: `2px solid ${color.border}`, borderLeft: `2px solid ${color.border}` }} />
            <div style={{ position: 'absolute', top: -2, right: -2, width: 10, height: 10, borderTop: `2px solid ${color.border}`, borderRight: `2px solid ${color.border}` }} />
            <div style={{ position: 'absolute', bottom: -2, left: -2, width: 10, height: 10, borderBottom: `2px solid ${color.border}`, borderLeft: `2px solid ${color.border}` }} />
            <div style={{ position: 'absolute', bottom: -2, right: -2, width: 10, height: 10, borderBottom: `2px solid ${color.border}`, borderRight: `2px solid ${color.border}` }} />
          </div>
        );
      })}

      {/* Track identity legend */}
      {activeLiveTracks.length > 0 && (
        <div style={{ position: 'absolute', bottom: '3rem', left: '1rem', zIndex: 20, background: 'rgba(2,6,23,0.85)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '0.375rem', padding: '0.5rem 0.75rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: '0.55rem', color: 'var(--text-muted)', letterSpacing: '0.08em', marginBottom: '0.2rem' }}>UNIQUE TRACKING IDENTITIES</div>
          {activeLiveTracks.map(ev => {
            const color = getTrackColor(ev.track_id);
            return (
              <div key={ev.track_id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: color.border, flexShrink: 0 }} />
                <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.6rem', color: color.border, letterSpacing: '0.06em' }}>
                  TRACK #{ev.track_id} {ev.detection_class?.toUpperCase()}
                  {ev.bbox_x == null && <span style={{ color: 'var(--text-muted)', marginLeft: '0.3rem', fontSize: '0.55rem' }}>(bbox unavailable)</span>}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ position: 'absolute', bottom: '1rem', right: '1rem', zIndex: 9999 }}>
        <button onClick={onUpload} style={{ background: 'rgba(15,23,42,0.85)', border: '1px solid var(--border-color)', color: 'var(--text-muted)', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '0.65rem', letterSpacing: '0.08em', padding: '0.4rem 0.8rem', borderRadius: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
          <Upload size={12} />CHANGE MEDIA
        </button>
      </div>

      {activeLiveTracks.length === 0 && (
        <div className="absolute" style={{ bottom: '1rem', left: '1rem', zIndex: 20 }}>
          <span className="text-muted font-display uppercase tracking-widest" style={{ fontSize: '0.6rem' }}>Analysing feed — awaiting detection</span>
        </div>
      )}
    </div>
  );
}
