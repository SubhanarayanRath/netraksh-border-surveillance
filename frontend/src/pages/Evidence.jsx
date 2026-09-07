import { useState, useEffect, useMemo } from 'react';
import { Search, Shield, CheckCircle, Database, GitBranch, Cloud } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { authFetch, WS_URL } from '../services/auth';
import LoginPrompt from '../components/LoginPrompt';
import { parseUtc } from '../utils/time';

export default function Evidence() {
  const { events } = useWebSocket(WS_URL);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [verifyStatus, setVerifyStatus] = useState(null); // 'verifying', 'verified', 'failed'
  const [searchQuery, setSearchQuery] = useState('');

  // Real decrypted evidence image (GET /events/{id}/evidence-image), separate
  // from the static /mock-fence.jpg placeholder this page already had.
  const [evidenceImageUrl, setEvidenceImageUrl] = useState(null);
  const [evidenceImageStatus, setEvidenceImageStatus] = useState('idle');
  // idle | loading | ready | no-evidence | no-key | auth-required | error
  const [evidenceImageSizeBytes, setEvidenceImageSizeBytes] = useState(null);

  // Use mock events if none from websocket
  const displayEvents = events.length > 0 ? events : [
    { event_id: 'EV-0184', event_type: 'Perimeter Breach Attempt', timestamp: new Date().toISOString(), decision_state: 'DETECTED', zone_id: 'Sector A', camera_id: 'CAM-Z4-09' },
    { event_id: 'EV-0183', event_type: 'Suspicious Vehicle Loitering', timestamp: new Date().toISOString(), decision_state: 'UNCERTAIN', zone_id: 'Sector B', camera_id: 'CAM-Z4-10' },
  ];

  useEffect(() => {
    if (displayEvents.length > 0 && !selectedEvent) {
      setSelectedEvent(displayEvents[0]);
    }
  }, [displayEvents]);

  // The search box previously had no onChange at all — typing in it did
  // nothing. Matches event_id and hash (what the placeholder promises),
  // plus event_type/decision_state — the visible title text on every list
  // item — since a real user typing a word they can see on screen (e.g.
  // "Perimeter") expects it to match, even though it isn't literally an
  // "ID or Hash".
  const filteredEvents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return displayEvents;
    return displayEvents.filter((ev) =>
      ev.event_id?.toLowerCase().includes(q) ||
      ev.hash?.toLowerCase().includes(q) ||
      ev.event_type?.toLowerCase().includes(q) ||
      ev.decision_state?.toLowerCase().includes(q)
    );
  }, [displayEvents, searchQuery]);

  const loadEvidenceImage = async (eventId) => {
    setEvidenceImageStatus('loading');
    setEvidenceImageSizeBytes(null);
    try {
      const res = await authFetch(`/events/${eventId}/evidence-image`);
      if (res.status === 401 || res.status === 403) {
        setEvidenceImageStatus('auth-required');
        return;
      }
      if (res.status === 409) {
        setEvidenceImageStatus('no-key');
        return;
      }
      if (res.status === 404 || !res.ok) {
        setEvidenceImageStatus('no-evidence');
        return;
      }
      const blob = await res.blob();
      setEvidenceImageSizeBytes(blob.size);
      setEvidenceImageUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(blob);
      });
      setEvidenceImageStatus('ready');
    } catch (_e) {
      setEvidenceImageStatus('error');
    }
  };

  useEffect(() => {
    if (selectedEvent) {
      loadEvidenceImage(selectedEvent.event_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEvent?.event_id]);

  // Release the last object URL when the page itself unmounts.
  // Switching between events is already handled inside loadEvidenceImage,
  // which revokes the URL it's about to replace before creating a new one.
  useEffect(() => {
    return () => {
      setEvidenceImageUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return prev;
      });
    };
  }, []);

  const handleVerify = async () => {
    if (!selectedEvent) return;
    setVerifyStatus('verifying');
    try {
      // Backend route is POST /events/{id}/verify — this previously called
      // it with fetch()'s default GET (a 405 every time, silently caught
      // below) and no auth header (now required, see backend/api/events.py).
      // Fixed to POST + authFetch as part of pre-deployment hardening.
      const res = await authFetch(`/events/${selectedEvent.event_id}/verify`, { method: 'POST' });
      if (res.status === 401 || res.status === 403) {
        setTimeout(() => setVerifyStatus('failed'), 1500);
        return;
      }
      // VerificationResponse (shared/schemas.py) has no is_valid field — it's
      // hash_valid/signature_valid/chain_valid, so this used to always read
      // undefined and report 'failed' even on a successful, fully-valid
      // response.
      const data = await res.json();
      const allValid = res.ok && data.hash_valid && data.signature_valid && data.chain_valid;
      setTimeout(() => {
        setVerifyStatus(allValid ? 'verified' : 'failed');
      }, 1500); // Artificial delay for animation
    } catch (e) {
      setTimeout(() => setVerifyStatus('failed'), 1500);
    }
  };

  const VerificationStep = ({ icon: Icon, title, desc, status, active }) => (
    <div className="flex flex-col items-center gap-2 text-center relative w-1/4">
      <div className={`w-12 h-12 rounded-full border-2 flex items-center justify-center ${active ? 'border-ok text-ok bg-[rgba(74,222,128,0.1)]' : 'border-color text-muted'}`}>
        <Icon size={20} />
      </div>
      <div className="flex flex-col">
        <span className="text-xs font-display text-muted">STEP</span>
        <span className="text-sm font-display text-main uppercase mt-1">{title}</span>
        <span className={`text-[10px] font-display px-2 py-1 border rounded mt-2 ${status === 'VERIFIED' || status === 'MATCH' ? 'text-ok border-ok' : 'text-muted border-color'}`}>
          {status}
        </span>
      </div>
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase">Tamper-Evident Evidence Unit</h2>
      </div>

      {/* h-[calc(100%-40px)] and w-[300px] (here and below) were bracket-
          notation classes that never applied any real CSS — see
          index.css's "looks like Tailwind, isn't real" entry. Converted to
          real inline styles. */}
      <div className="flex gap-4" style={{ height: 'calc(100% - 40px)' }}>

        {/* Left List */}
        <div className="flex flex-col bg-panel border rounded p-4 h-full" style={{ width: '300px' }}>
          <div className="flex items-center gap-2 mb-4">
            <Shield size={20} className="text-ok" />
            <span className="font-display">Evidence Vault</span>
          </div>
          <div className="relative mb-4">
            <Search size={16} className="absolute left-3 top-2.5 text-muted" />
            <input
              type="text" placeholder="Search by ID or Hash..." value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-dark border border-color rounded py-2 pl-10 pr-3 text-sm text-main"
            />
          </div>

          <div className="flex flex-col gap-2 overflow-y-auto pr-2">
            {filteredEvents.length === 0 && (
              <div className="text-muted text-xs text-center mt-4">No events match "{searchQuery}"</div>
            )}
            {filteredEvents.map((ev) => {
              const isSelected = selectedEvent?.event_id === ev.event_id;
              let badgeColor = ev.decision_state === 'DETECTED' ? 'ok' : ev.decision_state === 'UNCERTAIN' ? 'warning' : 'danger';
              return (
                <div
                  key={ev.event_id}
                  onClick={() => setSelectedEvent(ev)}
                  className={`p-3 border rounded cursor-pointer transition-colors ${isSelected ? 'border-ok bg-[rgba(74,222,128,0.05)]' : 'border-color hover-bg-elevated'}`}
                >
                  <div className="flex justify-between items-center mb-2">
                    <span className="font-display text-main text-sm">#{ev.event_id.split('-')[0]}</span>
                    <span className={`text-[10px] px-1 border rounded text-${badgeColor} border-${badgeColor}`}>
                      {ev.signature ? 'SIGNED' : 'UNSIGNED'}
                    </span>
                  </div>
                  <div className="text-sm text-main mb-1 truncate">{ev.event_type || ev.decision_state}</div>
                  <div className="text-xs text-muted font-body">
                    {parseUtc(ev.timestamp).toISOString().substring(11, 19)} UTC • {ev.zone_id}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Center Details */}
        <div className="flex-grow flex flex-col gap-4">
          <div className="flex gap-4">
            
            {/* Metadata Card */}
            <div className="flex-grow bg-panel border rounded p-6">
              <div className="flex justify-between items-start mb-8">
                <div className="flex-col">
                  <span className="text-main font-body text-sm">Event #{selectedEvent?.event_id.split('-')[0]}</span>
                  <span className="text-lg font-display text-main uppercase mt-2 block">NETRAKSH INTEGRITY DEEP DIVE</span>
                </div>
                {verifyStatus === 'verified' && (
                  <div className="border border-ok text-ok px-4 py-2 rounded font-display flex items-center gap-2 glow-ok">
                    <CheckCircle size={16} /> EVIDENCE VERIFIED
                  </div>
                )}
              </div>

              {/* Not `grid grid-cols-2` — inert class, see docs/LIMITATIONS.md */}
              <div className="mb-8" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', rowGap: '1.5rem', columnGap: '1rem' }}>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">CAPTURE TIME</span>
                  <span className="text-sm font-body">{selectedEvent ? parseUtc(selectedEvent.timestamp).toISOString().replace('T', ' ') : 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">SENSOR ID</span>
                  <span className="text-sm font-body border px-2 py-1 rounded w-max">{selectedEvent?.camera_id || 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">DETECTION TYPE</span>
                  {/* Was `selectedEvent?.event_type || 'Human'` — event_type is
                      the *rule* that fired (LOITERING, ANPR_READ, ...), not
                      what was detected, and "Human" was a hardcoded fallback
                      shown even for a real event whose detection_class was
                      something else (e.g. vehicle). detection_class
                      (EventResponse, shared/schemas.py) is the real field for
                      "what was detected". */}
                  {/* vehicle_subtype (shared.constants.VehicleSubtype) is real,
                      YOLO-derived car/motorcycle/bus/truck sub-classification —
                      only ever present when detection_class is "vehicle". */}
                  <span className="text-sm font-body">
                    {selectedEvent?.detection_class ? String(selectedEvent.detection_class).toUpperCase() : 'N/A'}
                    {selectedEvent?.vehicle_subtype && ` (${String(selectedEvent.vehicle_subtype).toUpperCase()})`}
                  </span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">EDGE NODE</span>
                  {/* EventResponse now exposes the real edge_device_id (it was
                      always stored on ingest — backend/api/events.py — just
                      never returned to the frontend). Falls back to an honest
                      "Not tracked" only when a synced event genuinely has
                      none, never to a fabricated literal. */}
                  <span className="text-sm font-body">{selectedEvent?.edge_device_id ? `${selectedEvent.edge_device_id} (Active)` : <span className="text-muted">Not tracked</span>}</span>
                </div>
                <div className="flex-col" style={{ gridColumn: 'span 2' }}>
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">CROSS-CAMERA CORROBORATION</span>
                  {/* Real, computed by backend/services/cross_camera.py after
                      ingest — see that module's docstring for exact scope
                      (temporal + real-distance plausibility, NOT person
                      re-identification). Absence is honestly shown as
                      "No corroborating sighting found", never as a
                      fabricated score. */}
                  {selectedEvent?.corroboration_score != null ? (
                    <span className="text-sm font-body text-ok">
                      Tc={selectedEvent.corroboration_score.toFixed(2)} · camera event {selectedEvent.corroborated_by_event_id?.split('-')[0]}
                      {selectedEvent.corroboration_distance_m != null && ` · ${selectedEvent.corroboration_distance_m.toFixed(0)}m away`}
                      {selectedEvent.corroboration_delta_t_s != null && ` · seen ${selectedEvent.corroboration_delta_t_s.toFixed(0)}s apart`}
                    </span>
                  ) : (
                    <span className="text-sm font-body text-muted">No corroborating sighting found (temporal/spatial plausibility only — not identity confirmation)</span>
                  )}
                </div>
              </div>

              <button 
                onClick={handleVerify}
                disabled={verifyStatus === 'verifying'}
                className="w-full bg-main text-black bg-white hover:bg-gray-200 py-3 rounded font-display uppercase tracking-widest flex items-center justify-center gap-2 transition-colors"
              >
                <GitBranch size={18} /> 
                {verifyStatus === 'verifying' ? 'Verifying Chain...' : 'Verify Netraksh Integrity Chain'}
              </button>
            </div>

            {/* Media Card */}
            <div className="flex-shrink-0 bg-panel border rounded p-2 relative" style={{ width: '300px' }}>
              <div
                className="w-full h-full bg-black rounded relative overflow-hidden"
                style={{
                  backgroundImage: `url(${evidenceImageStatus === 'ready' ? evidenceImageUrl : '/mock-fence.jpg'})`,
                  backgroundSize: 'cover',
                  backgroundPosition: 'center',
                  opacity: evidenceImageStatus === 'ready' ? 1 : 0.35,
                }}
              >
                <div className="absolute top-2 left-2 text-[10px] font-display bg-dark px-1 border rounded text-muted">
                  {evidenceImageStatus === 'ready' ? 'DECRYPTED EVIDENCE' : 'CH-04 | PREVIEW'}
                </div>

                {evidenceImageStatus === 'loading' && (
                  <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                    <span className="text-xs text-muted font-display">Decrypting...</span>
                  </div>
                )}

                {evidenceImageStatus === 'auth-required' && (
                  <div className="absolute inset-0 bg-black/85 flex items-center justify-center p-3">
                    <LoginPrompt
                      message="Sign in to view evidence"
                      onSuccess={() => selectedEvent && loadEvidenceImage(selectedEvent.event_id)}
                    />
                  </div>
                )}

                {evidenceImageStatus === 'no-key' && (
                  <div className="absolute bottom-2 left-2 right-2 text-[10px] font-display bg-dark px-2 py-1 border rounded text-warning">
                    Camera's evidence key isn't registered — run scripts/upload_evidence_key.py
                  </div>
                )}

                {evidenceImageStatus === 'no-evidence' && (
                  <div className="absolute bottom-2 left-2 right-2 text-[10px] font-display bg-dark px-2 py-1 border rounded text-muted">
                    No evidence clip on file for this event
                  </div>
                )}

                {evidenceImageStatus === 'error' && (
                  <div className="absolute bottom-2 left-2 right-2 text-[10px] font-display bg-dark px-2 py-1 border rounded text-danger">
                    Could not reach the backend
                  </div>
                )}

                {/* Mock bbox overlay — only shown over the placeholder, never over real decrypted evidence */}
                {evidenceImageStatus !== 'ready' && evidenceImageStatus !== 'auth-required' && (
                  <div className="absolute border-2 border-ok" style={{ top: '20%', left: '30%', width: '20%', height: '60%', backgroundColor: 'rgba(74,222,128,0.1)' }}>
                    <div className="absolute top-0 left-0 -translate-y-full bg-ok text-black text-xs font-display px-1 whitespace-nowrap">
                      [PERSON 98%]
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Cryptographic Hash Verification */}
          <div className="bg-panel border rounded p-6 mt-auto">
            <div className="flex items-center gap-2 mb-6">
              <GitBranch size={16} className="text-muted" />
              <span className="text-sm font-display text-main">Netraksh Cryptographic Hash Verification</span>
            </div>

            <div className="flex justify-between relative px-8">
              {/* Connecting line */}
              <div className="absolute top-6 bg-color border-b border-color -z-10" style={{ left: '10%', right: '10%', height: '1px' }}></div>
              
              <VerificationStep
                icon={Database} title="Event Data Extracted"
                // Real decrypted evidence size when we actually have the
                // bytes (evidenceImageSizeBytes, set in loadEvidenceImage);
                // this used to be a hardcoded "RAW: 1.4MB" for every event
                // regardless of whether one existed at all.
                status={evidenceImageSizeBytes != null ? `RAW: ${(evidenceImageSizeBytes / 1024).toFixed(1)}KB` : 'NO FILE'}
                active={verifyStatus !== null}
              />
              <VerificationStep
                icon={Shield} title="SHA-256 Generated"
                // Real hash from EventResponse.hash, truncated for display —
                // this used to be the literal string "A94F...72C1" for
                // every single event, never the event's actual hash.
                status={selectedEvent?.hash ? `${selectedEvent.hash.slice(0, 4)}...${selectedEvent.hash.slice(-4)}` : 'PENDING'}
                active={verifyStatus !== null}
              />
              <VerificationStep 
                icon={GitBranch} title="Local Chain Check" 
                status={verifyStatus === 'verified' ? "MATCH" : "PENDING"} 
                active={verifyStatus === 'verified'} 
              />
              <VerificationStep 
                icon={Cloud} title="Cloud Ledger Sync" 
                status={verifyStatus === 'verified' ? "VERIFIED" : "PENDING"} 
                active={verifyStatus === 'verified'} 
              />
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
