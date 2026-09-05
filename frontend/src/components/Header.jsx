import { User, Activity, AlertTriangle, Cpu, ChevronDown, ShieldCheck } from 'lucide-react';
import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Logo from './Logo';
import { authFetch } from '../services/auth';

export default function Header() {
  const [timeStr, setTimeStr] = useState('');
  const [showSyncPanel, setShowSyncPanel] = useState(false);
  const [syncStatus, setSyncStatus] = useState({ queued: 0, synced: 0, failed: 0 });
  const [pendingAlerts, setPendingAlerts] = useState(null); // null = not yet known

  useEffect(() => {
    const timer = setInterval(() => {
      const d = new Date();
      setTimeStr(d.toISOString().substring(11, 19) + " UTC");
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch sync status periodically
  useEffect(() => {
    const fetchSync = async () => {
      try {
        // /sync/status requires require_any_role (backend/api/system.py) — this
        // was a bare fetch() with no auth header, so it 401'd on every poll for
        // anyone not logged in (silently swallowed by the catch below). Using
        // authFetch means it actually succeeds once a viewer has signed in
        // (e.g. via the Evidence page's login form) instead of always failing.
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
  }, []);

  // The "⚠ 04" badge used to be a hardcoded literal "04" — never reflected
  // anything real. /system/status already returns a real
  // pending_acknowledgements count (backend/api/system.py); it just wasn't
  // being read anywhere in the frontend.
  useEffect(() => {
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
  }, []);

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
            <span className="flex items-center gap-1"><Cpu size={12} className="text-ok" /> EDGE: ONLINE</span>
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
          
          <div className="w-8 h-8 rounded-full bg-elevated flex items-center justify-center border text-ok">
            <User size={16} />
          </div>
        </div>
      </div>

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
            <span className="text-muted">Last Sync:</span>
            <span>Just now</span>
          </div>
          <div className="mt-2 pt-2 border-t border-color flex items-center gap-2 text-xs font-display">
            <ShieldCheck size={14} className="text-ok" />
            <span className="text-ok">Chain Integrity OK</span>
          </div>
        </div>
      )}
    </header>
  );
}
