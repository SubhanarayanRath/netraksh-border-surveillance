import { useState, useEffect, useRef, useMemo } from 'react';
import { ShieldCheck, HelpCircle, ShieldAlert, CheckCircle, GitMerge } from 'lucide-react';
import VideoFeed from '../components/VideoFeed';
import useWebSocket from '../hooks/useWebSocket';
import useDemoScenario from '../hooks/useDemoScenario';
import { WS_URL, BACKEND_URL, authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';
import { parseUtc } from '../utils/time';

// Reads structured scores from the event instead of string-parsing the reason.
function parseDecisionReason(ev) {
  if (!ev) return null;
  if (ev.decision_state === 'ABSTAIN') {
    return { kind: 'abstain', healthReason: ev.decision_reason || 'unknown' };
  }
  
  // If the event doesn't have structured scores yet (legacy data), fallback to string parsing
  if (ev.score_r == null && ev.decision_reason) {
    const rMatch = ev.decision_reason.match(/R=([\d.]+)\s*[<>]=?\s*([\d.]+)/);
    const factorMatch = ev.decision_reason.match(/D=([\d.]+),T=([\d.]+),S=([\d.]+),H=([\d.]+)/);
    if (!rMatch || !factorMatch) return null;
    return {
      kind: 'scored',
      r: parseFloat(rMatch[1]),
      threshold: parseFloat(rMatch[2]),
      aboveThreshold: ev.decision_reason.includes('R_ABOVE_THRESHOLD'),
      degraded: ev.decision_reason.includes('DEGRADED_CAMERA'),
      d: parseFloat(factorMatch[1]),
      t: parseFloat(factorMatch[2]),
      s: parseFloat(factorMatch[3]),
      h: parseFloat(factorMatch[4]),
    };
  }

  // Parse threshold from decision_reason if present, otherwise default 0.75
  let threshold = 0.75;
  if (ev.decision_reason) {
    const rMatch = ev.decision_reason.match(/R=[\d.]+\s*[<>]=?\s*([\d.]+)/);
    if (rMatch) threshold = parseFloat(rMatch[1]);
  }

  return {
    kind: 'scored',
    r: ev.score_r ?? 0,
    threshold: threshold,
    aboveThreshold: ev.decision_state === 'DETECTED',
    degraded: ev.camera_health_state === 'DEGRADED',
    d: ev.score_d ?? 0,
    t: ev.score_t ?? 0,
    s: ev.score_s ?? 0,
    h: ev.score_h ?? 0,
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
  const {
    events, health, metrics, liveTracks, cameras, isConnected,
    connectionStatus, resetRealtimeState, refreshEventsForContext, refreshTelemetryForContext,
  } = useWebSocket(WS_URL);
  const { scenario: demoScenario } = useDemoScenario();
  const [latestEvent, setLatestEvent] = useState(null);
  const [showWhy, setShowWhy] = useState(false);
  const { role } = useAuth();
  const canUpload = role && (role.toUpperCase() === 'ADMIN' || role.toUpperCase() === 'OPERATOR');

  // Media upload state — lifted here so the entire dashboard can be gated
  // behind a video upload. Until the operator loads a demo video, all
  // WebSocket events are suppressed from the UI so the jury sees a clean
  // "waiting for feed" state rather than automatic analysis on nothing.
  const [mediaUrl, setMediaUrl] = useState(null);
  const [mediaType, setMediaType] = useState('video');
  const [isUploading, setIsUploading] = useState(false);
  const [sessionStartTime, setSessionStartTime] = useState(0);
  const [videoSessionId, setVideoSessionId] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const [playbackEnded, setPlaybackEnded] = useState(false);
  const [selectedCameraId, setSelectedCameraId] = useState('');
  const [now, setNow] = useState(Date.now());
  const [backendStatus, setBackendStatus] = useState('CHECKING');
  const fileInputRef = useRef(null);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/ready`);
        if (mounted) setBackendStatus(response.ok ? 'HEALTHY' : 'UNAVAILABLE');
      } catch (_) {
        if (mounted) setBackendStatus('UNAVAILABLE');
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  const cameraIds = Array.from(new Set([
    ...cameras.map(camera => camera.camera_id),
    ...Object.keys(liveTracks),
    ...Object.keys(metrics),
    ...events.map(event => event.camera_id).filter(Boolean),
  ]));
  const cameraModels = useMemo(() => cameraIds.map(cameraId => {
    const camera = cameras.find(item => item.camera_id === cameraId) || {};
    const rawName = String(camera.name || '').trim();
    const normalizedId = String(cameraId || '').replace(/[_-]+/g, ' ').trim();
    const parts = normalizedId.split(/\s+/).filter(Boolean);
    const formattedParts = parts.map((part) => {
      if (/^cam$/i.test(part)) return 'Camera';
      if (/^border$/i.test(part)) return 'Border';
      if (/^checkpoint$/i.test(part)) return 'Checkpoint';
      if (/^\d+$/.test(part)) return part.padStart(2, '0');
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    });
    const friendlyFromId = formattedParts.includes('Camera')
      ? formattedParts.join(' ')
      : ['Camera', ...formattedParts].join(' ');
    const friendlyName = rawName && !/^unknown[-_]/i.test(rawName)
      ? rawName
      : friendlyFromId || 'Camera';
    const receivedAt = liveTracks[cameraId]?.timestamp;
    const age = receivedAt == null ? null : now - receivedAt;
    const analysisState = liveTracks[cameraId]?.analysis_state;
    const status = analysisState === 'COMPLETED'
      ? 'COMPLETED'
      : age != null && age <= 5000 ? 'LIVE' : age != null && age <= 30000 ? 'STALE' : 'OFFLINE';
    return {
      cameraId,
      friendlyName,
      displayId: cameraId.toUpperCase(),
      streamId: liveTracks[cameraId]?.stream_id || null,
      sourceType: 'EDGE CAMERA',
      status,
      lastSeen: receivedAt || null,
    };
  }), [cameraIds, cameras, liveTracks, now]);
  const reportingCameraId = videoSessionId
    ? Object.entries(liveTracks).find(([, telemetry]) => telemetry?.stream_id === videoSessionId)?.[0]
    : null;
  const selectedCameraHasActiveStream = selectedCameraId
    && (!videoSessionId || liveTracks[selectedCameraId]?.stream_id === videoSessionId);
  const activeCameraId = (selectedCameraHasActiveStream ? selectedCameraId : reportingCameraId)
    || selectedCameraId
    || Object.keys(liveTracks)[0]
    || cameras.find(camera => camera.health_state)?.camera_id
    || cameraIds[0]
    || null;
  const activeCamera = cameraModels.find(camera => camera.cameraId === activeCameraId) || null;
  const activeTelemetryReceivedAt = activeCameraId ? liveTracks[activeCameraId]?.timestamp : null;
  const telemetryAgeMs = activeTelemetryReceivedAt == null ? null : now - activeTelemetryReceivedAt;
  const analysisState = activeCameraId ? liveTracks[activeCameraId]?.analysis_state : null;
  const telemetryStatus = !isConnected ? 'DISCONNECTED'
    : analysisState === 'COMPLETED' ? 'COMPLETED'
    : telemetryAgeMs == null ? 'WAITING'
    : telemetryAgeMs > 5000 ? 'STALE'
    : 'LIVE';
  const activeMetrics = activeCameraId ? metrics[activeCameraId] : null;
  const metricTimestampMs = activeMetrics?.timestamp ? Date.parse(activeMetrics.timestamp) : NaN;
  const metricsFresh = Number.isFinite(metricTimestampMs) && now - metricTimestampMs < 30000;

  const eventTimestampMs = (value) => {
    if (!value) return NaN;
    const date = parseUtc(value);
    return date ? date.getTime() : NaN;
  };

  useEffect(() => {
    if (!activeCameraId) return;
    refreshEventsForContext(activeCameraId, videoSessionId);
    refreshTelemetryForContext(activeCameraId, videoSessionId);
  }, [activeCameraId, videoSessionId, refreshEventsForContext, refreshTelemetryForContext]);


  // On mount: check if the server already has a browser-playable video
  // from a previous session.  This avoids the empty-feed state after a
  // page refresh when the edge runner is still processing the last upload.
  //
  // Session lifecycle: reuse the existing backend session_id when present.
  // Generating a new randomUUID() on every page reload caused the DemoRunner
  // to restart every time the browser refreshed (because the polling thread
  // sees a new session_id via /api/dashboard/video/internal-sync and triggers
  // a pipeline restart), discarding in-flight telemetry and desynchronising
  // the videoSessionId guard in Dashboard.  The guard nulls out liveTelemetry
  // when liveTelemetry.stream_id !== videoSessionId, so a mismatch means LIVE
  // telemetry is silently dropped even when the edge is running correctly.
  useEffect(() => {
    const checkExistingVideo = async () => {
      try {
        const res = await authFetch('/api/dashboard/video/current');
        if (!res.ok) return;
        const data = await res.json();
        if (data.preview_url) {
          if (data.session_id) {
            // REUSE the existing backend session_id so the DemoRunner's
            // currently-running pipeline (and its telemetry stream_id) already
            // matches what the frontend will filter against.  A new session is
            // only needed when the user explicitly uploads a new video.
            setVideoSessionId(data.session_id);
            setSessionStartTime(Date.now());
            // Do NOT POST a new session_id here — that would restart the
            // DemoRunner unnecessarily.  The backend already has the correct
            // state; we are just synchronising the browser to it.
          }
          const mediaRes = await authFetch(data.preview_url);
          if (mediaRes.ok) {
            const blob = await mediaRes.blob();
            const blobUrl = URL.createObjectURL(blob);
            setMediaUrl(blobUrl);
            setMediaType('video');
          }
        }
      } catch (_) {/* non-fatal */}
    };
    checkExistingVideo();
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!file.type.startsWith('video/')) {
      setUploadError('Please select a supported video file.');
      return;
    }

    resetRealtimeState();
    setUploadError(null);
    setPlaybackEnded(false);
    setSessionStartTime(Date.now());
    setLatestEvent(null);
    const nextUrl = URL.createObjectURL(file);
    if (mediaUrl?.startsWith('blob:')) URL.revokeObjectURL(mediaUrl);
    // Avoid presenting a known-incompatible AVI/DivX blob while the backend
    // creates the browser preview. Native MP4 files can still render instantly.
    setMediaUrl(file.type === 'video/mp4' ? nextUrl : null);
    setMediaType('video');
    setIsUploading(true);
    setVideoSessionId(null);

    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await authFetch('/api/dashboard/video/upload', { method: 'POST', body: formData });
      if (!res.ok) {
        let detail = 'Video upload failed.';
        try { detail = (await res.json()).detail || detail; } catch (_) { /* keep concise fallback */ }
        throw new Error(detail);
      }
      const uploaded = await res.json();
      
      if (uploaded.session_id && uploaded.source_name) {
        try {
          const analyzeRes = await authFetch('/api/dashboard/video/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              session_id: uploaded.session_id,
              source_name: uploaded.source_name,
              preview_name: uploaded.preview_url ? `uploaded_${uploaded.session_id}_preview.mp4` : null
            })
          });
          if (!analyzeRes.ok) {
             console.error('Failed to trigger analysis on edge', await analyzeRes.text());
          }
        } catch (err) {
          console.error('Network error triggering analysis:', err);
        }
      }

      if (uploaded.status === 'ok_no_preview') {
        URL.revokeObjectURL(nextUrl);
        setMediaUrl(null);
        if (uploaded.session_id) setVideoSessionId(uploaded.session_id);
        setUploadError(uploaded.message);
        return;
      }
      if (uploaded.session_id) setVideoSessionId(uploaded.session_id);
      if (uploaded.preview_url) {
        const mediaRes = await authFetch(uploaded.preview_url);
        if (mediaRes.ok) {
            const blob = await mediaRes.blob();
            const blobUrl = URL.createObjectURL(blob);
            if (nextUrl !== mediaUrl) URL.revokeObjectURL(nextUrl);
            setMediaUrl(blobUrl);
        } else {
            throw new Error('Failed to load video media.');
        }
      } else if (file.type !== 'video/mp4') {
        throw new Error('This video needs an H.264 MP4 preview, but the server could not create one.');
      }
    } catch (error) {
      console.error('Upload error:', error);
      URL.revokeObjectURL(nextUrl);
      setMediaUrl(null);
      setUploadError(error.message || 'Video upload failed.');
    } finally {
      setIsUploading(false);
    }
  };

  useEffect(() => () => {
    if (mediaUrl) URL.revokeObjectURL(mediaUrl);
  }, [mediaUrl]);

  const [fleetHealth, setFleetHealth] = useState([]);
  
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const response = await authFetch('/api/nodes/health');
        if (response.ok) setFleetHealth(await response.json());
      } catch (e) {
        console.error("Failed to fetch fleet health", e);
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const triggerUpload = () => fileInputRef.current?.click();

  // Events for the selected camera and active uploaded-video context.
  const contextualEvents = [];
  const _seenIds = new Set();
  events.forEach(e => {
    if (activeCameraId && e.camera_id !== activeCameraId) return;
    // Prefer the exact stream contract. A camera/time fallback is allowed
    // only for genuinely legacy events that have no stream_id and only while
    // this browser has a known upload start time.
    if (videoSessionId && e.stream_id && e.stream_id !== videoSessionId) return;
    if (videoSessionId && !e.stream_id) {
      const timestamp = eventTimestampMs(e.timestamp);
      if (!sessionStartTime || !Number.isFinite(timestamp) || timestamp < sessionStartTime) return;
    }
    
    // Deduplication
    const id = e.event_id || e.id;
    if (id) {
      if (_seenIds.has(id)) return;
      _seenIds.add(id);
    }
    
    // Legacy fallback applies only when no session contract is available.
    if (!videoSessionId) {
      const timestamp = eventTimestampMs(e.timestamp);
      if (!Number.isFinite(timestamp) || timestamp < sessionStartTime) return;
    }
    contextualEvents.push(e);
  });

  useEffect(() => {
    if (mediaUrl && contextualEvents.length > 0) {
      setLatestEvent(contextualEvents[0]);
    }
  }, [contextualEvents.length, contextualEvents[0]?.event_id, contextualEvents[0]?.id, mediaUrl]);

  const securityEvents = contextualEvents.filter(ev => ev.event_type && String(ev.event_type).toLowerCase() !== 'unknown');

  const parsed = latestEvent ? parseDecisionReason(latestEvent) : null;
  // Reliability factors and Gate 1 must describe the same event snapshot.
  // Live camera health is only a fallback when no event health was recorded.
  const healthState = latestEvent?.camera_health_state
    || (latestEvent && health[latestEvent.camera_id]?.health_state); // 'OK' | 'DEGRADED' | 'FAILED'
  const sceneCondition = latestEvent?.scene_condition;
  const decisionMeta = DECISION_META[latestEvent?.decision_state] || null;
  const whyExplanation = explainDecision(parsed);
  let liveTelemetry = !activeCameraId ? null : liveTracks[activeCameraId];
  if (liveTelemetry && videoSessionId && liveTelemetry.stream_id && liveTelemetry.stream_id !== videoSessionId) {
    liveTelemetry = null;
  }

  const StatusPill = ({ title, desc, type, active }) => {
    let colors = '';
    let icon = null;
    
    if (type === 'detected') {
      colors = active ? 'bg-ok text-black' : 'badge-outline';
      icon = <CheckCircle size={16} />;
    } else if (type === 'uncertain') {
      colors = active ? 'bg-warning text-black' : 'badge-outline';
      icon = <HelpCircle size={16} />;
    } else {
      colors = active ? 'bg-danger text-white' : 'badge-outline';
      icon = <ShieldAlert size={16} />;
    }

    return (
      <div className={`dashboard-status-pill card ${colors} transition-all ${active ? 'shadow-lg scale-105' : 'opacity-60'}`} style={{ padding: '0.625rem', height: '100%', borderColor: active ? 'transparent' : 'var(--border-color)', borderRadius: 'var(--radius-md)' }}>
        <div className="flex items-center" style={{ gap: '0.375rem', marginBottom: '0.2rem' }}>
          {icon}
          <span className="font-display font-bold" style={{ fontSize: '0.7rem', letterSpacing: '0.05em' }}>{title}</span>
        </div>
        <span className="font-body" style={{ fontSize: '0.55rem', opacity: 0.8, lineHeight: 1.2 }}>{desc}</span>
      </div>
    );
  };

  const LogicGate = ({ num, title, stats, active }) => (
    <div className={`dashboard-logic-gate flex rounded border ${active ? 'border-ok bg-[rgba(34,211,164,0.05)]' : 'border-color opacity-50'} relative`} style={{ padding: '0.5rem', gap: '0.75rem', borderRadius: 'var(--radius-md)' }}>
      <div className="flex-shrink-0 mt-1">
        <div className={`w-3 h-3 rounded-full border-2 flex items-center justify-center ${active ? 'border-ok text-ok bg-[rgba(34,211,164,0.2)]' : 'border-color text-muted'}`}>
        </div>
      </div>
      <div className="flex flex-col w-full">
        <span className="dashboard-gate-title font-display text-muted uppercase tracking-wider" style={{ fontSize: '0.55rem', letterSpacing: '0.1em', marginBottom: '0.25rem' }}>Gate {num} — {title}</span>
        <div className="flex justify-between items-center rounded border border-color" style={{ padding: '0.35rem', background: 'var(--bg-base)' }}>
          {stats}
        </div>
      </div>
      
      {num < 3 && <div className="absolute left-6 top-8 h-12 bg-border-color -z-10" style={{ width: '1px' }}></div>}
    </div>
  );

  return (
    <div className="dashboard-page h-full flex flex-col" style={{ gap: '1rem' }}>
      <div className="section-header">
        <div>
          <div className="section-title">Border Intelligence Center</div>
          <div className="section-sub">Real-time camera, edge and reliability monitoring</div>
        </div>
        <div className="dashboard-command-status">
          <label className="dashboard-camera-select">
            <span>ACTIVE CAMERA</span>
            <select
              value={activeCameraId || ''}
              onChange={(event) => {
                setSelectedCameraId(event.target.value);
                setLatestEvent(null);
                setPlaybackEnded(false);
              }}
              disabled={cameraIds.length === 0}
            >
              {cameraIds.length === 0 && <option value="">No camera configured</option>}
              {cameraModels.map(camera => {
                return <option key={camera.cameraId} value={camera.cameraId}>{camera.friendlyName} · {camera.displayId} · {camera.status}</option>;
              })}
            </select>
          </label>
          <div className={`dashboard-status-chip status-${backendStatus.toLowerCase()}`}>
            <span>BACKEND</span><strong>{backendStatus}</strong>
          </div>
          <div className={`dashboard-status-chip status-${connectionStatus.toLowerCase()}`}>
            <span>SOCKET</span><strong>{connectionStatus}</strong>
          </div>
          <div className={`dashboard-status-chip status-${telemetryStatus.toLowerCase()}`}>
            <span>TELEMETRY</span><strong>{telemetryStatus}</strong>
          </div>
        </div>
      </div>

      <div className="dashboard-live-strip">
        <div><span>CAMERA</span><strong title={activeCamera?.displayId}>{activeCamera?.friendlyName || 'Not configured'}</strong></div>
        <div><span>CAMERA HEALTH</span><strong>{health[activeCameraId]?.health_state || 'UNKNOWN'}</strong></div>
        <div><span>FPS</span><strong>{metricsFresh && Number.isFinite(activeMetrics?.fps) ? activeMetrics.fps.toFixed(2) : 'N/A'}</strong></div>
        <div><span>LIVE TRACKS</span><strong>{telemetryStatus === 'LIVE' ? (liveTracks[activeCameraId]?.tracks?.length ?? 0) : 'N/A'}</strong></div>
        <div><span>FRAME</span><strong>{telemetryStatus === 'LIVE' && liveTracks[activeCameraId]?.frame_width ? `${liveTracks[activeCameraId].frame_width}×${liveTracks[activeCameraId].frame_height}` : 'N/A'}</strong></div>
        <div><span>LAST TELEMETRY</span><strong>{telemetryAgeMs == null ? 'Never' : `${Math.max(0, telemetryAgeMs / 1000).toFixed(1)}s ago`}</strong></div>
      </div>

      {/* h-[calc(100%-80px)], flex-[3]/flex-[2] (below), and min-h-[400px]
          (below) were all bracket-notation classes that never applied any
          real CSS — the video feed column in particular used to collapse
          to ~2px tall as a result (confirmed via getComputedStyle, not
          guessed) since nothing was left to give it real height once
          .absolute/.relative were fixed and stopped accidentally
          contributing document-flow height. Converted to real inline
          styles. */}
      <div className="dashboard-main-grid flex" style={{ flex: 1, minHeight: 0, gap: '1rem' }}>

        {/* Left Column */}
        <div className="dashboard-left-column flex-col h-full" style={{ flex: 3, display: 'flex', gap: '0.75rem' }}>
          {/* Hidden file input — triggered from VideoFeed's upload button */}
          <input
            type="file"
            accept=".mp4,.avi,.mov,.mkv,.webm,.flv,.wmv,.mpeg,.mpg,.3gp,.3gpp,.m4v,.ogv,.ts,.m2ts,.mts,.vob,.rmvb,.rm,.divx,.xvid,.asf,.f4v,.h264,.hevc,.mp2,.mpe,.mpv,.m2v,.svi,.3g2,.mxf,video/*,image/*"
            onChange={handleFileUpload}
            ref={fileInputRef}
            style={{ display: 'none' }}
          />

          <div className="dashboard-video-slot" style={{ minHeight: '300px' }}>
            <VideoFeed
              eventData={latestEvent}
              liveTracksData={liveTelemetry}
              telemetryStatus={telemetryStatus}
              cameraId={activeCameraId}
              playbackEnded={playbackEnded}
              demoScenario={demoScenario}
              mediaUrl={mediaUrl}
              mediaType={mediaType}
              currentFps={metricsFresh ? activeMetrics?.fps : null}
              onUpload={triggerUpload}
              isUploading={isUploading}
              canUpload={canUpload}
              uploadError={uploadError}
              onVideoEnded={() => setPlaybackEnded(true)}
              onStartAnalysis={(time) => {
                if (playbackEnded) {
                  // Reuse the same videoSessionId to preserve the active session and events
                  // Do NOT generate a new crypto.randomUUID() for a loop of the same video.
                  
                  // Fire POST before clearing playbackEnded state
                  authFetch('/api/dashboard/video/scenario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ video_session_id: videoSessionId, scenario: demoScenario || 'normal', video_time: 0 })
                  }).catch(e => console.error("Failed to set new session", e));

                  // Keep the existing videoSessionId
                  setSessionStartTime(Date.now());
                  setPlaybackEnded(false);
                  setLatestEvent(null);
                } else {
                  authFetch('/api/dashboard/video/scenario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ video_session_id: videoSessionId, scenario: demoScenario || 'normal', video_time: time })
                  }).catch(e => console.error("Failed to sync play time", e));
                }
              }}
              onPauseAnalysis={(time) => {
                 authFetch('/api/dashboard/video/scenario', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ video_session_id: videoSessionId, scenario: 'paused', video_time: time })
                  }).catch(e => console.error("Failed to sync pause", e));
              }}
            />
          </div>

          <div className="dashboard-timeline-card card" style={{ minHeight: '21rem' }}>
            <div className="card-header">
              <span className="card-title">Event Timeline</span>
              <button
                onClick={() => setShowWhy((v) => !v)}
                className="btn btn-sm btn-outline"
                style={{ fontSize: '0.5rem', letterSpacing: '0.05em' }}
              >
                WHY THIS ALERT?
              </button>
            </div>
            
            <div className="flex flex-col" style={{ padding: '0.75rem', gap: '0.5rem', overflowY: 'auto' }}>
              {showWhy && (
                <div className="text-xs font-body text-main border border-color rounded mb-2" style={{ padding: '0.5rem', background: 'var(--bg-base)' }}>
                  {whyExplanation || 'No real event yet to explain — this fills in from the same decision_reason data the Reliability Decision panel shows, once one arrives.'}
                </div>
              )}
              <div className="flex flex-col gap-2 flex-grow pr-2">
                {!mediaUrl && securityEvents.length === 0 ? (
                  <div className="state-empty" style={{ padding: '1rem' }}>
                    <div className="state-empty-sub">No verified security events recorded for this camera yet</div>
                  </div>
                ) : analysisState === 'COMPLETED' && securityEvents.length === 0 ? (
                  <div className="state-empty" style={{ padding: '1rem' }}>
                    <div className="state-empty-sub">VIDEO COMPLETE — NO SECURITY EVENTS DETECTED FOR THIS STREAM</div>
                  </div>
                ) : securityEvents.length === 0 ? (
                  <div className="state-loading" style={{ padding: '1rem' }}>
                    <span>PROCESSING — NO VERIFIED SECURITY EVENT YET</span>
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                        {['TIME','TRACK','TYPE','DECISION','SEVERITY','CONF','VERIFIED'].map(h => (
                          <th key={h} style={{
                            fontFamily: 'var(--font-display)', fontSize: '0.75rem',
                            fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
                            color: 'var(--text-muted)', padding: '0.25rem 0.5rem',
                            textAlign: 'left', whiteSpace: 'nowrap',
                          }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {/* Real events from processed video */}
                      {securityEvents.map((ev, i) => {
                        const parsedEv = parseDecisionReason(ev);
                        const conf = parsedEv?.kind === 'scored'
                          ? `${Math.round(parsedEv.d * 100)}%`
                          : 'N/A';
                        const tsDate = parseUtc(ev.timestamp);
                        const tsStr = tsDate && !isNaN(tsDate)
                          ? tsDate.toISOString().substring(11, 19)
                          : 'N/A';
                        const decColor =
                          ev.decision_state === 'DETECTED'  ? 'var(--color-ok)'      :
                          ev.decision_state === 'UNCERTAIN' ? 'var(--color-warning)'  :
                          ev.decision_state === 'ABSTAIN'   ? 'var(--color-danger)'   :
                                                              'var(--text-muted)';
                        const typeLabel = ev.event_type
                          ? ev.event_type.replace(/_/g, ' ')
                          : (ev.detection_class || 'N/A');
                        return (
                          <tr key={ev.event_id || ev.id || `${ev.timestamp}-${ev.track_id||''}-${i}`}
                              style={{ borderBottom: '1px solid rgba(30,48,80,0.4)' }}>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', color: 'var(--accent)', padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{tsStr}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', color: 'var(--text-main)', padding: '0.3rem 0.5rem' }}>#{ev.track_id ?? 'N/A'}</td>
                            <td style={{ fontSize: '0.875rem', color: 'var(--text-main)', padding: '0.3rem 0.5rem', maxWidth: '8rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={typeLabel}>{typeLabel}</td>
                            <td style={{ fontFamily: 'var(--font-display)', fontSize: '0.8rem', fontWeight: 700, color: decColor, padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{ev.decision_state || 'N/A'}</td>
                            <td style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', color: ev.severity === 'HIGH' || ev.severity === 'CRITICAL' ? 'var(--color-danger)' : 'var(--text-muted)', padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{ev.severity || 'N/A'}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.875rem', color: 'var(--text-muted)', padding: '0.3rem 0.5rem' }}>{conf}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: ev.verified_ok === true ? 'var(--color-ok)' : 'var(--text-muted)', padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>{ev.verified_ok == null ? 'N/A' : ev.verified_ok ? 'YES' : 'NO'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          {/* Cross-Camera Corroboration Panel
              Shows temporal/spatial plausibility score (Tc) when a second
              camera has observed the same detection class within the expected
              travel-time window.  This is NOT identity re-identification —
              see backend/services/cross_camera.py for honest scope. */}
          <div className="dashboard-cross-camera-card card mt-2">
            <div className="card-header">
              <div className="flex items-center gap-2">
                <GitMerge size={12} className="text-muted" />
                <span className="card-title">Cross-Camera Corroboration</span>
              </div>
              <span className="badge badge-neutral" style={{ fontSize: '0.45rem' }}>temporal/spatial only</span>
            </div>
            <div className="flex flex-col" style={{ padding: '0.75rem' }}>
              {latestEvent?.corroborated_by_event_id ? (
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-ok text-lg">&#10003;</span>
                    <span className="text-sm font-display text-ok">
                      Corroborated by{' '}
                      <span className="font-bold">{latestEvent.corroborating_camera_id || 'second camera'}</span>
                    </span>
                  </div>
                  <div className="flex gap-4 text-xs font-body text-muted">
                    <span>Tc = <span className="text-main">{Number.isFinite(latestEvent.corroboration_score) ? latestEvent.corroboration_score.toFixed(3) : 'N/A'}</span></span>
                    {latestEvent.corroboration_delta_t_s != null && (
                      <span>Δt = <span className="text-main">{latestEvent.corroboration_delta_t_s.toFixed(0)}s</span> apart</span>
                    )}
                    {latestEvent.corroboration_distance_m != null && (
                      <span><span className="text-main">{latestEvent.corroboration_distance_m.toFixed(0)}m</span> separation</span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted italic mt-1">Same detection class appeared at a spatially-plausible camera within expected travel time. No identity re-id claimed.</span>
                </div>
              ) : latestEvent ? (
                <div className="flex items-start gap-2">
                  <span className="text-warning text-base">&#9888;</span>
                  <div className="flex flex-col">
                    <span className="text-sm font-display text-warning">NO CORROBORATION / INSUFFICIENT EVIDENCE</span>
                    <span className="text-xs text-muted">This event has no qualifying second-camera match in the persisted record. A result will appear only when a real spatially and temporally plausible event is available.</span>
                  </div>
                </div>
              ) : (
                <span className="text-xs text-muted">Waiting for a real event…</span>
              )}
            </div>
          </div>

        </div>

        {/* Right Column */}
        <div className="dashboard-right-column flex-col h-full" style={{ flex: 2, display: 'flex', gap: '0.75rem' }}>
          <div className="dashboard-reliability-card card">
            <div className="card-header">
              <span className="card-title">Reliability Decision Pipeline</span>
              <ShieldCheck size={14} className="text-muted" />
            </div>

            <div className="flex flex-col relative" style={{ gap: '0.5rem', padding: '0.75rem' }}>
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
                    <span className="text-xs text-muted">{liveTelemetry ? 'N/A — no reliability event for current telemetry' : 'Waiting for a real event…'}</span>
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
                    <span className="text-xs text-muted">{liveTelemetry ? 'N/A — no scene decision for current telemetry' : 'Waiting for a real event…'}</span>
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
                    <span className="text-xs text-muted">{liveTelemetry ? 'N/A — reliability is emitted only with a processed event' : 'Waiting for a real event…'}</span>
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
            <div className="mt-auto" style={{ marginTop: 'auto', padding: '0 0.75rem 0.75rem' }}>
              {decisionMeta ? (
                <div role="status" className={`w-full border rounded font-display tracking-widest flex items-center justify-center ${decisionMeta.colorClass}`} style={{ padding: '0.5rem 0', gap: '0.5rem', fontSize: '0.75rem' }}>
                  <decisionMeta.icon size={14} /> [{decisionMeta.label}]
                </div>
              ) : (
                <div role="status" className="w-full border border-color text-muted rounded font-display tracking-widest flex items-center justify-center opacity-60" style={{ padding: '0.5rem 0', gap: '0.5rem', fontSize: '0.75rem' }}>
                  <HelpCircle size={14} /> [AWAITING EVENT]
                </div>
              )}
            </div>
          </div>

          {/* Not `grid grid-cols-3` — inert class, see docs/LIMITATIONS.md */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
            <StatusPill 
              title="DETECTED" desc="Reliable detection confirmed" 
              type="detected" active={latestEvent?.decision_state === 'DETECTED'} />
            <StatusPill 
              title="UNCERTAIN" desc="Confidence < Threshold" 
              type="uncertain" active={latestEvent?.decision_state === 'UNCERTAIN'} />
            <StatusPill 
              title="ABSTAIN" desc="System Unreliable" 
              type="abstain" active={latestEvent?.decision_state === 'ABSTAIN'} />
          </div>
          
          {/* System Fleet Health Widget */}
          <div className="dashboard-fleet-card card flex-grow">
             <div className="card-header">
                <span className="card-title">System Fleet Health</span>
                <span className="badge badge-neutral" style={{ fontSize: '0.45rem' }}>{fleetHealth.length} Nodes</span>
             </div>
             <div className="overflow-y-auto custom-scrollbar flex flex-col gap-2 flex-grow" style={{ padding: '0.75rem' }}>
               {fleetHealth.length === 0 && <div className="state-empty-sub">Health data unavailable</div>}
               {fleetHealth.map(node => {
                 const lastPingMs = node.last_ping ? Date.parse(node.last_ping) : NaN;
                 const nodeFresh = Number.isFinite(lastPingMs) && now - lastPingMs < 30000;
                 const nodeState = nodeFresh ? node.health_state : (node.last_ping ? 'OFFLINE' : 'UNKNOWN');
                 let color = 'text-warning';
                 let bgColor = 'bg-[rgba(245,158,11,0.05)]';
                 if (nodeState === 'FAILED' || nodeState === 'OFFLINE') {
                   color = 'text-danger';
                   bgColor = 'bg-[rgba(239,68,68,0.05)]';
                 } else if (nodeFresh && node.health_state === 'OK') {
                   color = 'text-ok';
                   bgColor = 'bg-[rgba(34,211,164,0.05)]';
                 }

                 return (
                   <div key={node.camera_id} className={`flex flex-col border rounded p-2 ${bgColor}`} style={{ borderColor: `var(--color-${color.replace('text-','')})` }}>
                     <div className="flex justify-between items-center mb-1">
                       <span className={`font-display ${color}`} style={{ fontSize: '0.65rem' }}>{node.name}</span>
                       <span className={`font-display ${color}`} style={{ fontSize: '0.5rem' }}>{nodeState}</span>
                     </div>
                     <div className="flex justify-between text-muted" style={{ fontSize: '0.55rem', fontFamily: 'var(--font-mono)' }}>
                       <span>FPS: {nodeFresh && Number.isFinite(node.fps) ? node.fps.toFixed(1) : 'N/A'}</span>
                       <span>CPU: {nodeFresh && Number.isFinite(node.cpu_percent) ? `${node.cpu_percent.toFixed(1)}%` : 'N/A'}</span>
                       <span>Uptime: {nodeFresh && Number.isFinite(node.uptime_seconds) ? `${Math.floor(node.uptime_seconds / 3600)}h` : 'N/A'}</span>
                     </div>
                   </div>
                 );
               })}
             </div>
          </div>
        </div>

      </div>
    </div>
  );
}
