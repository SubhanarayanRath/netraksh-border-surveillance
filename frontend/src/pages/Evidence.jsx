import { useState, useEffect } from 'react';
import { Search, Shield, CheckCircle, Database, GitBranch, Cloud, Lock } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { authFetch, login, WS_URL } from '../services/auth';

export default function Evidence() {
  const { events } = useWebSocket(WS_URL);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [verifyStatus, setVerifyStatus] = useState(null); // 'verifying', 'verified', 'failed'

  // Real decrypted evidence image (GET /events/{id}/evidence-image), separate
  // from the static /mock-fence.jpg placeholder this page already had.
  const [evidenceImageUrl, setEvidenceImageUrl] = useState(null);
  const [evidenceImageStatus, setEvidenceImageStatus] = useState('idle');
  // idle | loading | ready | no-evidence | no-key | auth-required | error
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginError, setLoginError] = useState(null);
  const [loginSubmitting, setLoginSubmitting] = useState(false);

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

  const loadEvidenceImage = async (eventId) => {
    setEvidenceImageStatus('loading');
    setLoginError(null);
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

  const handleLoginSubmit = async (e) => {
    e.preventDefault();
    setLoginSubmitting(true);
    setLoginError(null);
    try {
      await login(loginUsername, loginPassword);
      if (selectedEvent) await loadEvidenceImage(selectedEvent.event_id);
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginSubmitting(false);
    }
  };

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

      <div className="flex gap-4 h-[calc(100%-40px)]">
        
        {/* Left List */}
        <div className="w-[300px] flex flex-col bg-panel border rounded p-4 h-full">
          <div className="flex items-center gap-2 mb-4">
            <Shield size={20} className="text-ok" />
            <span className="font-display">Evidence Vault</span>
          </div>
          <div className="relative mb-4">
            <Search size={16} className="absolute left-3 top-2.5 text-muted" />
            <input type="text" placeholder="Search by ID or Hash..." className="w-full bg-dark border border-color rounded py-2 pl-10 pr-3 text-sm text-main" />
          </div>

          <div className="flex flex-col gap-2 overflow-y-auto pr-2">
            {displayEvents.map((ev) => {
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
                    <span className={`text-[10px] px-1 border rounded text-${badgeColor} border-${badgeColor}`}>SIGNED</span>
                  </div>
                  <div className="text-sm text-main mb-1 truncate">{ev.event_type || ev.decision_state}</div>
                  <div className="text-xs text-muted font-body">
                    {new Date(ev.timestamp).toLocaleTimeString()} UTC • {ev.zone_id}
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

              <div className="grid grid-cols-2 gap-y-6 gap-x-4 mb-8">
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">CAPTURE TIME</span>
                  <span className="text-sm font-body">{selectedEvent ? new Date(selectedEvent.timestamp).toISOString().replace('T', ' ') : 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">SENSOR ID</span>
                  <span className="text-sm font-body border px-2 py-1 rounded w-max">{selectedEvent?.camera_id || 'N/A'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">DETECTION TYPE</span>
                  <span className="text-sm font-body">{selectedEvent?.event_type || 'Human'}</span>
                </div>
                <div className="flex-col">
                  <span className="text-xs text-muted font-display uppercase tracking-widest mb-1">EDGE NODE</span>
                  <span className="text-sm font-body">edge-001 (Active)</span>
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
            <div className="w-[300px] flex-shrink-0 bg-panel border rounded p-2 relative">
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
                    <form onSubmit={handleLoginSubmit} className="w-full flex flex-col gap-2">
                      <div className="flex items-center gap-1 text-muted mb-1">
                        <Lock size={12} />
                        <span className="text-[10px] font-display uppercase tracking-widest">Sign in to view evidence</span>
                      </div>
                      <input
                        type="text" placeholder="Username" value={loginUsername}
                        onChange={(e) => setLoginUsername(e.target.value)}
                        className="w-full bg-dark border border-color rounded py-1.5 px-2 text-xs text-main"
                      />
                      <input
                        type="password" placeholder="Password" value={loginPassword}
                        onChange={(e) => setLoginPassword(e.target.value)}
                        className="w-full bg-dark border border-color rounded py-1.5 px-2 text-xs text-main"
                      />
                      {loginError && <span className="text-[10px] text-danger">{loginError}</span>}
                      <button
                        type="submit" disabled={loginSubmitting}
                        className="w-full bg-white hover:bg-gray-200 text-black py-1.5 rounded font-display text-xs uppercase tracking-widest transition-colors"
                      >
                        {loginSubmitting ? 'Signing in...' : 'Sign in'}
                      </button>
                    </form>
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
                  <div className="absolute top-[20%] left-[30%] w-[20%] h-[60%] border-2 border-ok bg-[rgba(74,222,128,0.1)]">
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
              <div className="absolute top-6 left-[10%] right-[10%] h-[1px] bg-color border-b border-color -z-10"></div>
              
              <VerificationStep 
                icon={Database} title="Event Data Extracted" 
                status="RAW: 1.4MB" 
                active={verifyStatus !== null} 
              />
              <VerificationStep 
                icon={Shield} title="SHA-256 Generated" 
                status={verifyStatus === 'verified' ? "A94F...72C1" : "PENDING"} 
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
