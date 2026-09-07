import { User, Activity, AlertTriangle, Cpu, ChevronDown, ShieldCheck, ShieldAlert, LogOut } from 'lucide-react';
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Logo from './Logo';
import { authFetch, logout } from '../services/auth';
import useAuth from '../hooks/useAuth';
import useDemoScenario from '../hooks/useDemoScenario';
import LoginPrompt from './LoginPrompt';

const ROLE_COLORS = {
  ADMIN: 'text-danger border-danger',
  OPERATOR: 'text-ok border-ok',
  AUDITOR: 'text-warning border-warning',
};

export default function Header() {
  const { isAuthenticated, role, username } = useAuth();
  const { scenario } = useDemoScenario();
  const [timeStr, setTimeStr] = useState('');
  const [showSyncPanel, setShowSyncPanel] = useState(false);
  const [showAccountPanel, setShowAccountPanel] = useState(false);
  const [syncStatus, setSyncStatus] = useState({ queued: 0, synced: 0, failed: 0 });
  const [pendingAlerts, setPendingAlerts] = useState(null); // null = not yet known
  const [chainStatus, setChainStatus] = useState(null); // null = not yet checked

  useEffect(() => {
    const timer = setInterval(() => {
      const d = new Date();
      setTimeStr(d.toISOString().substring(11, 19) + " UTC");
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch sync status periodically
  useEffect(() => {
    // /sync/status requires require_any_role (backend/api/system.py) — an
    // anonymous viewer will never get anything but 401 from it. Polling it
    // anyway every 5s regardless of auth state meant every unauthenticated
    // visit spammed the console with a 401 every 5 seconds forever, for a
    // request that was never going to succeed. Only poll once signed in.
    if (!isAuthenticated) return undefined;
    const fetchSync = async () => {
      try {
        const res = await authFetch('/sync/status');
        if (res.ok) {
          const data = await res.json();
          setSyncStatus(data);
        }
      } catch (e) {}
    };
    fetchSync();
    const timer = setInterval(fetchSync, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated]);

  // The "⚠ 04" badge used to be a hardcoded literal "04" — never reflected
  // anything real. /system/status already returns a real
  // pending_acknowledgements count (backend/api/system.py); it just wasn't
  // being read anywhere in the frontend.
  useEffect(() => {
    // Same reasoning as the sync-status poll above: /system/status also
    // requires require_any_role, so this is a guaranteed 401 for anyone not
    // signed in — only poll once authenticated.
    if (!isAuthenticated) return undefined;
    const fetchAlertCount = async () => {
      try {
        const res = await authFetch('/system/status');
        if (res.ok) {
          const data = await res.json();
          setPendingAlerts(data.pending_acknowledgements);
        }
      } catch (_e) {}
    };
    fetchAlertCount();
    const timer = setInterval(fetchAlertCount, 5000);
    return () => clearInterval(timer);
  }, [isAuthenticated]);

  // The sync panel's "Chain Integrity OK" line was a hardcoded literal,
  // never actually checked — but GET /system/verify-chain (public, no auth
  // required — backend/api/system.py) already does a real check across
  // every EvidencePackage's stored verified_ok flag. Fetched when the panel
  // opens rather than polled continuously, since this isn't data that
  // changes on its own between opens.
  useEffect(() => {
    if (!showSyncPanel) return;
    const fetchChainStatus = async () => {
      try {
        const res = await authFetch('/system/verify-chain');
        if (res.ok) setChainStatus(await res.json());
      } catch (_e) {}
    };
    fetchChainStatus();
  }, [showSyncPanel]);

  return (
    <header className="header-top relative">
      <div className="flex items-center gap-3">
        <Logo size={30} />
        <div className="flex-col">
          <h1 className="text-lg font-display tracking-widest text-main m-0 p-0" style={{lineHeight: 1}}>NETRAKSH</h1>
          <span className="text-xs text-muted font-display tracking-widest">BORDER INTELLIGENCE UNIT</span>
        </div>
      </div>

      <div className="flex items-center gap-8">
        <div className="flex-col items-center">
          <span className="text-lg font-body text-main" style={{lineHeight: 1}}>{timeStr}</span>
          <span className="text-xs text-muted font-display tracking-widest">SYSTEM TIME</span>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs font-display">
            {/* Was a hardcoded "EDGE: ONLINE" regardless of any real state.
                Still not tied to a real edge heartbeat (no such endpoint
                exists yet — see docs/LIMITATIONS.md), but it now at least
                honestly reflects the Demo Scenario Control panel's
                "Offline State" selection instead of always claiming ONLINE
                no matter what the demo panel next to it says. */}
            <span className="flex items-center gap-1">
              <Cpu size={12} className={scenario === 'offline' ? 'text-danger' : 'text-ok'} />
              EDGE: {scenario === 'offline' ? 'OFFLINE' : 'ONLINE'}
            </span>
            <button 
              onClick={() => setShowSyncPanel(!showSyncPanel)}
              className="flex items-center gap-1 hover:text-white transition-colors relative"
            >
              <Activity size={12} className={syncStatus.queued > 0 ? "text-warning" : "text-ok"} /> 
              SYNC: {syncStatus.queued > 0 ? 'BUFFERING' : '100%'}
              <ChevronDown size={12} />
            </button>
          </div>
          
          <Link to="/cross-command-alerts" className="badge badge-danger hover:scale-105 transition-transform">
            <AlertTriangle size={14} /> {pendingAlerts != null ? String(pendingAlerts).padStart(2, '0') : '--'}
          </Link>
          
          {/* Was a purely decorative circle — no click handler, no real
              session info, no way to sign out anywhere in the app. Every
              login this whole project does (Evidence/Health/Alerts/
              Performance's LoginPrompt) had nowhere to show who was
              actually signed in or let them sign out again. */}
          <button
            onClick={() => setShowAccountPanel((v) => !v)}
            className={`w-8 h-8 rounded-full bg-elevated flex items-center justify-center border transition-colors ${isAuthenticated ? (ROLE_COLORS[role] || 'text-ok') : 'text-muted'}`}
            title={isAuthenticated ? `${username} (${role})` : 'Not signed in'}
          >
            <User size={16} />
          </button>
        </div>
      </div>

      {showAccountPanel && (
        <div className="absolute top-[60px] right-4 w-64 bg-panel border rounded p-4 shadow-lg z-50 flex flex-col gap-3">
          {isAuthenticated ? (
            <>
              <div className="flex justify-between items-center border-b border-color pb-2">
                <span className="text-xs font-display text-muted uppercase">Signed In</span>
                <span className={`text-[10px] font-display border rounded px-1.5 py-0.5 ${ROLE_COLORS[role] || 'text-ok border-ok'}`}>{role}</span>
              </div>
              <div className="text-sm font-body text-main">{username}</div>
              <button
                onClick={() => { logout(); setShowAccountPanel(false); }}
                className="flex items-center justify-center gap-2 text-xs font-display text-danger border border-danger rounded py-1.5 hover:bg-[rgba(248,113,113,0.1)] transition-colors"
              >
                <LogOut size={14} /> Sign Out
              </button>
            </>
          ) : (
            <LoginPrompt message="Sign in" onSuccess={() => setShowAccountPanel(false)} />
          )}
        </div>
      )}

      {/* Expandable Sync Panel */}
      {showSyncPanel && (
        <div className="absolute top-[60px] right-24 w-64 bg-panel border rounded p-4 shadow-lg z-50 flex flex-col gap-3">
          <div className="flex justify-between items-center border-b border-color pb-2">
            <span className="text-xs font-display text-muted uppercase">Sync Status</span>
            <div className={`w-2 h-2 rounded-full ${syncStatus.queued > 0 ? 'bg-warning animate-pulse' : 'bg-ok'}`}></div>
          </div>
          <div className="flex justify-between text-sm font-body">
            <span className="text-muted">Buffered Events:</span>
            <span className={syncStatus.queued > 0 ? 'text-warning' : 'text-main'}>{syncStatus.queued}</span>
          </div>
          <div className="flex justify-between text-sm font-body">
            <span className="text-muted">Successfully Synced:</span>
            <span className="text-ok">{syncStatus.synced}</span>
          </div>
          <div className="flex justify-between text-sm font-body">
            {/* No backend anywhere tracks a real "last successful sync"
                timestamp (SyncStatusResponse.last_sync_at exists as a schema
                field but no endpoint ever populates or returns it) — this
                used to just say "Just now" unconditionally. Showing the
                honest absence of that data instead of a fabricated one. */}
            <span className="text-muted">Last Sync:</span>
            <span className="text-muted">Not tracked</span>
          </div>
          <div className="mt-2 pt-2 border-t border-color flex items-center gap-2 text-xs font-display">
            {/* Was a hardcoded "Chain Integrity OK" regardless of any real
                state — now calls the real GET /system/verify-chain
                (backend/api/system.py), which checks every stored
                EvidencePackage.verified_ok. */}
            {chainStatus == null ? (
              <span className="text-muted">Checking chain integrity…</span>
            ) : chainStatus.is_valid ? (
              <>
                <ShieldCheck size={14} className="text-ok" />
                <span className="text-ok">{chainStatus.message}</span>
              </>
            ) : (
              <>
                <ShieldAlert size={14} className="text-danger" />
                <span className="text-danger">{chainStatus.message}</span>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
