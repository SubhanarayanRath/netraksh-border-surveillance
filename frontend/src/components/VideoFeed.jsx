import { CameraOff, CloudFog, AlertTriangle, Upload, Play } from 'lucide-react';
import { useMemo, useState, useEffect, useRef } from 'react';

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

  const containerRef = useRef(null);
  const videoRef = useRef(null);
  const [videoRect, setVideoRect] = useState({ left: 0, top: 0, width: 0, height: 0, vw: 0, vh: 0, cw: 0, ch: 0 });
  const [renderTrigger, setRenderTrigger] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setRenderTrigger(v => v + 1), 50);
    return () => clearInterval(timer);
  }, []);

  const activeLiveTracks = useMemo(() => {
    if (!liveTracksData || !liveTracksData.tracks) return [];
    if (Date.now() - liveTracksData.timestamp > 500) return [];
    
    if (liveTracksData.video_time != null && videoRef.current) {
      if (!videoRef.current.paused) {
        videoRef.current.pause();
      }
      
      const targetTime = liveTracksData.video_time;
      const diff = Math.abs(videoRef.current.currentTime - targetTime);
      if (diff > 0.05) {
        console.log(`SEEKING from ${videoRef.current.currentTime} to ${targetTime}`);
        videoRef.current.currentTime = targetTime;
      }
    }
    
    return liveTracksData.tracks;
  }, [liveTracksData, renderTrigger]);

  useEffect(() => {
    const updateRect = () => {
      const container = containerRef.current;
      const video = videoRef.current;
      if (!container || !video) return;
      
      const rect = container.getBoundingClientRect();
      const cw = rect.width;
      const ch = rect.height;
      const vw = liveTracksData?.frame_width || video.videoWidth || video.naturalWidth || 768;
      const vh = liveTracksData?.frame_height || video.videoHeight || video.naturalHeight || 576;

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
      
      setVideoRect({ left, top, width: renderedWidth, height: renderedHeight, cw, ch, vw, vh });
    };

    updateRect();
    const ro = new ResizeObserver(updateRect);
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [mediaUrl, renderTrigger, liveTracksData?.frame_width]);

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
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full h-full relative border rounded overflow-hidden" style={{ background: 'radial-gradient(circle at 50% 50%, #064e3b 0%, #020617 100%)', boxShadow: 'inset 0 0 50px rgba(0,0,0,0.8)' }}>
      <video ref={videoRef} onLoadedMetadata={() => setRenderTrigger(v=>v+1)} src={mediaUrl} muted style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', zIndex: 0 }} />

      <div className="absolute top-[20%] left-1/2 transform -translate-x-1/2 bg-red-600/90 text-white font-mono text-xl p-4 z-50 whitespace-pre text-center border-4 border-yellow-400">
        {`[SUPER DEBUG OVERLAY]\n`}
        {`CW: ${videoRect.cw?.toFixed(1)}, CH: ${videoRect.ch?.toFixed(1)}\n`}
        {`VW: ${videoRect.vw}, VH: ${videoRect.vh}\n`}
        {`RENDERED_W: ${videoRect.width?.toFixed(1)}, RENDERED_H: ${videoRect.height?.toFixed(1)}\n`}
        {`OFFSET_L: ${videoRect.left?.toFixed(1)}, OFFSET_T: ${videoRect.top?.toFixed(1)}\n`}
        {liveTracksData ? `SEQ: ${liveTracksData.sequence}\nVID_TIME: ${liveTracksData.video_time?.toFixed(2)}s\n` : `NO DATA\n`}
        {videoRef.current ? `PLAYING_TIME: ${videoRef.current.currentTime?.toFixed(2)}s\nPAUSED: ${videoRef.current.paused}\nREADY_STATE: ${videoRef.current.readyState}\n` : `NO VIDEO\n`}
        {`TRACKS: ${activeLiveTracks.length}`}
      </div>

      {activeLiveTracks.map((ev) => {
        const color = getTrackColor(ev.track_id);
        if (ev.bbox_x == null || ev.bbox_y == null || ev.bbox_w == null || ev.bbox_h == null) return null;
        const lbl = `TRACK #${ev.track_id ?? '?'}`;
        return (
          <div key={ev.track_id} style={{
            position: 'absolute', 
            left: `${videoRect.left + (ev.bbox_x * videoRect.width)}px`, 
            top: `${videoRect.top + (ev.bbox_y * videoRect.height)}px`,
            width: `${ev.bbox_w * videoRect.width}px`, 
            height: `${ev.bbox_h * videoRect.height}px`,
            border: `2px solid ${color.border}`, backgroundColor: color.bg,
            zIndex: 10, boxShadow: `0 0 8px ${color.border}60`, transition: 'none',
          }}>
            <div style={{ position: 'absolute', top: 0, left: 0, transform: 'translateY(-100%)', background: color.border, color: color.label, fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: '0.6rem', padding: '1px 5px', whiteSpace: 'nowrap' }}>{lbl}</div>
          </div>
        );
      })}
    </div>
  );
}
