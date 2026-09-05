import { useState, useEffect, useCallback } from 'react';
import { Cpu, Zap, HardDrive, Gauge, AlertTriangle } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL, authFetch } from '../services/auth';
import LoginPrompt from '../components/LoginPrompt';
import { parseUtc } from '../utils/time';

// Real edge performance telemetry (edge/instrumentation/metrics.py's
// perf_counter()-measured latency/FPS/CPU/RSS) previously existed only as
// a local JSON file on the edge device — nothing exposed it anywhere. This
// page reads the real GET /system/metrics this session added, merged with
// live WS pushes for whichever edge device is currently reporting.
const FRAME_STAGE_LABELS = {
  health_condition_ms: 'Health + Condition',
  detection_tracking_ms: 'Detection + Tracking',
  event_processing_ms: 'Event Processing',
  total_frame_ms: 'Total Frame',
};
const EVENT_STAGE_LABELS = {
  snapshot_ms: 'Snapshot',
  hash_sign_ms: 'Hash + Sign',
  chain_store_ms: 'Chain Store',
  enqueue_ms: 'Enqueue',
  total_event_ms: 'Total (Decision → Enqueue)',
};

function formatUptime(seconds) {
  if (seconds == null) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
}

export default function Performance() {
  const { metrics: wsMetrics } = useWebSocket(WS_URL);
  const [restMetrics, setRestMetrics] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | error

  const loadMetrics = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await authFetch('/system/metrics');
      if (res.status === 401 || res.status === 403) {
        setStatus('auth-required');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setRestMetrics(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => { loadMetrics(); }, [loadMetrics]);

  // Merge: REST gives every device's latest snapshot as of page load; WS
  // pushes update whichever device reports again while the page is open.
  const merged = { ...Object.fromEntries(restMetrics.map((m) => [m.edge_device_id, m])), ...wsMetrics };
  const devices = Object.values(merged).sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''));

  const StatTile = ({ icon: Icon, label, value, sub }) => (
    <div className="bg-panel border rounded p-4 flex flex-col gap-1">
      <div className="flex items-center gap-2 text-muted text-xs font-display uppercase tracking-widest">
        <Icon size={14} /> {label}
      </div>
      <span className="text-2xl font-display text-main">{value}</span>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  );

  const StageRow = ({ label, stats }) => (
    <div className="flex items-center justify-between text-sm font-body py-1.5 border-b border-color last:border-b-0">
      <span className="text-muted">{label}</span>
      <div className="flex gap-4 text-xs">
        <span>mean <span className="text-main">{stats.mean_ms.toFixed(1)}ms</span></span>
        <span>p95 <span className="text-warning">{stats.p95_ms.toFixed(1)}ms</span></span>
        <span>max <span className="text-danger">{stats.max_ms.toFixed(1)}ms</span></span>
        <span className="text-muted">(n={stats.count})</span>
      </div>
    </div>
  );

  const DeviceCard = ({ m }) => (
    <div className="bg-panel border rounded p-6 flex flex-col gap-6">
      <div className="flex justify-between items-start">
        <div className="flex-col">
          <span className="text-lg font-display text-main uppercase">{m.edge_device_id}</span>
          <span className="text-xs font-display text-muted uppercase tracking-widest">
            Uptime {formatUptime(m.uptime_seconds)} · Last report {m.timestamp ? parseUtc(m.timestamp).toLocaleTimeString() : '—'}
          </span>
        </div>
        <Gauge size={24} className="text-muted" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile icon={Zap} label="Measured FPS" value={m.fps.toFixed(1)} sub="rolling window, not declared rate" />
        {/* CPU and RSS gate independently on their own field being non-null,
            not jointly on `psutil_available` — a single end-of-run CPU%
            sample can be uncredible (see docs/PERFORMANCE_REPORT.md: "this
            reading is not credible... do not put 0% CPU in the PPT") while
            the RSS reading from that exact same run is fine to quote. A
            shared gate would have hidden a real, credible RSS number just
            because CPU wasn't trustworthy that run. */}
        <StatTile
          icon={Cpu} label="CPU"
          value={m.cpu_percent != null ? `${m.cpu_percent.toFixed(1)}%` : '—'}
          sub={m.cpu_percent != null ? undefined : (m.psutil_available ? 'not sampled this run' : 'psutil not installed on edge')}
        />
        <StatTile
          icon={HardDrive} label="Memory (RSS)"
          value={m.rss_mb != null ? `${m.rss_mb.toFixed(0)} MB` : '—'}
          sub={m.rss_mb != null ? undefined : (m.psutil_available ? 'not sampled this run' : 'psutil not installed on edge')}
        />
        <StatTile icon={AlertTriangle} label="Alerts Generated" value={m.alerts_generated} sub="this process's lifetime" />
      </div>

      <div>
        <span className="text-xs font-display text-muted uppercase tracking-widest">Per-Frame Stage Latency</span>
        <div className="mt-2">
          {Object.entries(m.frames).map(([stage, stats]) => (
            <StageRow key={stage} label={FRAME_STAGE_LABELS[stage] || stage} stats={stats} />
          ))}
        </div>
      </div>

      {m.events.total_event_ms.count > 0 && (
        <div>
          <span className="text-xs font-display text-muted uppercase tracking-widest">Per-Event Stage Latency (evidence path)</span>
          <div className="mt-2">
            {Object.entries(m.events).map(([stage, stats]) => (
              <StageRow key={stage} label={EVENT_STAGE_LABELS[stage] || stage} stats={stats} />
            ))}
          </div>
        </div>
      )}

      {m.adaptive_gate && (
        <div className="flex justify-between items-center text-xs font-display text-muted border-t border-color pt-3">
          <span>Adaptive Compute Gate</span>
          <span className={m.adaptive_gate.state === 'ACTIVE' ? 'text-ok' : 'text-muted'}>
            {m.adaptive_gate.state} · skipped {(m.adaptive_gate.skip_ratio * 100).toFixed(0)}%
            ({m.adaptive_gate.frames_skipped}/{m.adaptive_gate.frames_run + m.adaptive_gate.frames_skipped} frames)
          </span>
        </div>
      )}
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase">Edge Performance</h2>
        <p className="text-sm font-body text-muted">
          Real, locally-measured latency and resource usage from every edge device that has ever reported —
          not simulated, not declared/configured values.
        </p>
      </div>

      {status === 'auth-required' && (
        <div className="max-w-xs bg-panel border rounded p-4">
          <LoginPrompt message="Sign in to view performance data" onSuccess={loadMetrics} />
        </div>
      )}

      {status === 'loading' && <div className="text-muted text-sm text-center mt-8">Loading real metrics…</div>}
      {status === 'error' && <div className="text-danger text-sm text-center mt-8">Could not reach the backend.</div>}

      {status === 'ready' && (
        devices.length === 0 ? (
          <div className="text-muted text-sm text-center mt-8">
            No edge device has reported performance metrics yet. This page fills in automatically once
            edge/main.py's EdgePipeline is running against a real camera feed.
          </div>
        ) : (
          <div className="flex flex-col gap-6 overflow-y-auto pr-2">
            {devices.map((m) => <DeviceCard key={m.edge_device_id} m={m} />)}
          </div>
        )
      )}
    </div>
  );
}
