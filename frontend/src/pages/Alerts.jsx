import { useState, useEffect, useCallback, useMemo } from 'react';
import { AlertTriangle, Globe, Crosshair, MapPin, CheckCircle, Eye } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL, authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';
import LoginPrompt from '../components/LoginPrompt';
import TacticalMap from '../components/TacticalMap';
import { parseUtc } from '../utils/time';

// Real alert data has no free-text title/description field anywhere in the
// data model (AlertResponse only carries severity/camera/zone/event_type/
// jurisdiction/blockchain/ack fields) — these derive a readable headline
// from what actually exists, instead of claiming specific incident text
// ("Multiple Armed Intruders") that was never real.
const EVENT_TYPE_LABELS = {
  VIRTUAL_FENCE_CROSSING: 'Virtual Fence Crossing',
  LINE_CROSSING: 'Line Crossing',
  LOITERING: 'Loitering Detected',
  ABANDONED_OBJECT: 'Abandoned Object',
  VEHICLE_DETECTED: 'Vehicle Detected',
};

function alertTitle(alert) {
  const type = EVENT_TYPE_LABELS[alert.event_type] || alert.event_type || alert.decision_state || 'Escalated Event';
  return `${alert.severity} — ${type}`;
}

export default function Alerts() {
  const { alerts: wsAlerts } = useWebSocket(WS_URL);
  const { role } = useAuth();
  // Backend's real RBAC (require_operator_or_admin, backend/api/alerts.py)
  // already rejects AUDITOR's acknowledge attempt with a 403 — this just
  // reflects that real permission in the UI instead of letting an AUDITOR
  // click a button that was always going to fail.
  const canAcknowledge = role === 'ADMIN' || role === 'OPERATOR';
  const [restAlerts, setRestAlerts] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | error
  const [ackingId, setAckingId] = useState(null);

  const loadAlerts = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await authFetch('/alerts');
      if (res.status === 401 || res.status === 403) {
        setStatus('auth-required');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setRestAlerts(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => { loadAlerts(); }, [loadAlerts]);

  // Real alerts only, from two sources: GET /alerts (whatever existed
  // before this page was opened) and live WS new_alert pushes (whatever
  // arrives while it's open) — deduped by alert_id, since the same alert
  // can appear in both once the REST list is next refreshed.
  const realAlerts = useMemo(() => {
    const byId = new Map();
    for (const a of restAlerts) byId.set(a.alert_id, a);
    for (const a of wsAlerts) byId.set(a.alert_id, { ...byId.get(a.alert_id), ...a });
    return [...byId.values()].sort((a, b) =>
      (parseUtc(b.timestamp || b.created_at) || new Date(0)) - (parseUtc(a.timestamp || a.created_at) || new Date(0))
    );
  }, [restAlerts, wsAlerts]);

  // Previously: 2 hardcoded fake alerts were ALWAYS concatenated onto real
  // ones, indistinguishable from them. Now they only appear as a fallback
  // when there are zero real alerts, clearly labeled as such — the same
  // convention Evidence.jsx already uses for its own placeholder events.
  const mockAlerts = [
    { alert_id: 'ALT-992-A', severity: 'CRITICAL', event_type: 'DEMO — Multiple Intruders', camera_id: 'Sector 7, Node Alpha', timestamp: new Date(Date.now() - 1000 * 60 * 5).toISOString(), isMock: true },
    { alert_id: 'ALT-814-B', severity: 'HIGH', event_type: 'DEMO — Vehicle Ramming Attempt', camera_id: 'East Gate Checkpoint', timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(), isMock: true },
  ];
  const displayAlerts = realAlerts.length > 0 ? realAlerts : mockAlerts;

  const handleAcknowledge = async (alertId) => {
    setAckingId(alertId);
    try {
      const res = await authFetch(`/alerts/${alertId}/acknowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receiving_command_id: 'COMMAND_A', status: 'ACKNOWLEDGED' }),
      });
      if (res.ok) await loadAlerts();
    } catch (_e) {
      // best-effort — the button just stops spinning below
    } finally {
      setAckingId(null);
    }
  };

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex justify-between items-start">
        <div className="flex-col">
          <h2 className="text-xl font-display text-main tracking-widest uppercase mb-2">Cross-Command Alerts</h2>
          <p className="text-sm font-body text-muted">
            High-severity incidents broadcasted across the blockchain network from neighboring nodes.
          </p>
        </div>
        <div className="bg-[rgba(239,68,68,0.1)] border border-danger text-danger px-4 py-2 rounded font-display tracking-widest flex items-center gap-2 glow-danger">
          <Globe size={18} /> NETWORK SECURE
        </div>
      </div>

      {status === 'auth-required' && (
        <div className="max-w-xs bg-panel border rounded p-4">
          <LoginPrompt message="Sign in to view alerts" onSuccess={loadAlerts} />
        </div>
      )}

      {status !== 'auth-required' && (
        // NOT `grid grid-cols-1 lg:grid-cols-2` — found while building the
        // real map that neither class does anything in this project: there
        // is no Tailwind compiler here, only a small hand-written CSS
        // subset (index.css), and `.grid`/`grid-cols-*`/`@media` breakpoints
        // were never defined in it at all (confirmed via
        // getComputedStyle — gridTemplateColumns came back "none"). Same
        // root cause as the earlier `text-center` bug (Sidebar.jsx). This
        // one specific layout is fixed with real, working flex classes;
        // every other `grid`/`grid-cols-*` usage elsewhere in this codebase
        // has the same latent bug and is not touched here — see
        // docs/LIMITATIONS.md.
        <div className="flex gap-6 flex-grow" style={{ minHeight: 0 }}>
          <div className="flex flex-col gap-4 overflow-y-auto pr-2" style={{ flex: '1 1 0%', minWidth: 0 }}>
            {status === 'loading' && <div className="text-muted text-sm text-center mt-4">Loading real alerts…</div>}
            {status === 'error' && <div className="text-danger text-sm text-center mt-4">Could not reach the backend.</div>}
            {realAlerts.length === 0 && status === 'ready' && (
              <div className="text-[10px] font-display text-muted uppercase tracking-widest border border-color rounded px-2 py-1 text-center">
                No real alerts yet — showing demo placeholders below
              </div>
            )}
            {displayAlerts.map(alert => (
              <div key={alert.alert_id} className="bg-panel border border-danger rounded p-4 flex flex-col gap-3 relative overflow-hidden">
                <div className="absolute top-0 left-0 w-1 h-full bg-danger"></div>

                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="text-danger" size={20} />
                    <span className="text-danger font-display tracking-widest">#{alert.alert_id.split('-')[0]}</span>
                    {alert.isMock && <span className="text-[9px] border border-muted text-muted rounded px-1">DEMO</span>}
                  </div>
                  <span className="bg-danger text-white text-[10px] px-2 py-1 rounded font-display tracking-widest">{alert.severity}</span>
                </div>

                <h3 className="text-lg font-display text-main">{alert.isMock ? alert.event_type : alertTitle(alert)}</h3>
                {alert.crosses_jurisdiction_boundary && (
                  <p className="text-sm font-body text-muted">Crosses jurisdiction boundary — escalated cross-command.</p>
                )}

                <div className="flex gap-6 mt-2 pt-3 border-t border-[rgba(239,68,68,0.2)] text-xs font-display text-muted">
                  <span className="flex items-center gap-1"><MapPin size={14}/> {alert.camera_id || alert.zone_id || 'Unknown'}</span>
                  <span className="flex items-center gap-1"><Crosshair size={14}/> T - {Math.floor((Date.now() - (parseUtc(alert.timestamp || alert.created_at) || new Date())) / 60000)} MINS</span>
                  {!alert.isMock && (
                    alert.acknowledged_at ? (
                      <span className="flex items-center gap-1 text-ok"><CheckCircle size={14}/> Acknowledged{alert.acknowledged_by ? ` by ${alert.acknowledged_by}` : ''}</span>
                    ) : canAcknowledge ? (
                      <button
                        onClick={() => handleAcknowledge(alert.alert_id)}
                        disabled={ackingId === alert.alert_id}
                        className="ml-auto text-ok border border-ok rounded px-2 py-0.5 hover:bg-[rgba(74,222,128,0.1)] disabled:opacity-50"
                      >
                        {ackingId === alert.alert_id ? 'Acknowledging…' : 'Acknowledge'}
                      </button>
                    ) : (
                      // Real backend RBAC (require_operator_or_admin) would
                      // reject an AUDITOR's acknowledge attempt with a 403 —
                      // shown here as a real, honest read-only indicator
                      // instead of a button that was always going to fail.
                      <span className="ml-auto flex items-center gap-1 text-muted" title="AUDITOR role is read-only for acknowledgements">
                        <Eye size={14}/> View only
                      </span>
                    )
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="bg-panel border rounded p-2 relative h-full min-h-[400px]" style={{ flex: '1 1 0%', minWidth: 0 }}>
            {/* Real geospatial map — replaces what used to be a fully
                decorative <div> (static background image, 3 hardcoded pixel
                positions named "SECTOR 7"/"HQ"/"NODE C", tied to nothing
                real). See components/TacticalMap.jsx. */}
            <TacticalMap alerts={realAlerts} />
          </div>
        </div>
      )}
    </div>
  );
}
