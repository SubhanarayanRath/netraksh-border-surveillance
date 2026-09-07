import { Box, Server, Camera, ShieldCheck, Database, Link, ArrowRight } from 'lucide-react';

export default function Architecture() {
  // NOTE ON LAYOUT: this used to lay the 4 pipeline cards out with a
  // `w-1/4` className. That class was never defined anywhere in index.css
  // (confirmed by grepping it — the file only ever defines fractionless
  // widths like w-full/w-64) so every card silently fell back to its
  // shrink-to-fit content width inside a fixed h-64 box; on real content,
  // that made the Reliability Gate card's 3 status rows + formula overflow
  // its own box and visually collide with the Evidence Chain row below it.
  // Real fix: a real inline flex-basis with a floor, no invented class.
  const CARD_FLEX = { flex: '1 1 210px', minWidth: 0 };

  const ArchNode = ({ step, title, subtitle, icon: Icon, children, isCore }) => (
    <div
      className={`bg-panel border rounded p-4 flex flex-col ${isCore ? 'border-ok glow-ok' : 'border-color'}`}
      style={CARD_FLEX}
    >
      <div className="flex items-center justify-between gap-2 mb-3 pb-2 border-b border-color">
        <div className="flex items-center gap-2 text-muted">
          <Icon size={16} />
          <span className="text-xs font-display uppercase tracking-widest">{title}</span>
        </div>
        <span className="text-xs font-display text-muted opacity-60">{step}</span>
      </div>
      <h3 className="text-main font-display mb-1" style={{ fontSize: '0.95rem', lineHeight: 1.35 }}>{subtitle}</h3>
      <div className="text-sm font-body text-muted flex-grow">
        {children}
      </div>
    </div>
  );

  const Connector = () => (
    <div className="flex items-center justify-center text-muted" style={{ flex: '0 0 18px' }}>
      <ArrowRight size={16} />
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-6" style={{ overflowY: 'auto' }}>
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase mb-2">Netraksh System Architecture</h2>
        <p className="text-sm font-body text-muted max-w-3xl">
          End-to-end data pipeline from physical sensor arrays to permissioned ledger consensus. Designed for zero-trust environments requiring immutable audit trails.
        </p>
      </div>

      <div className="flex-grow flex flex-col gap-8 p-8 bg-[rgba(15,23,42,0.5)] rounded border border-color relative overflow-hidden">
        {/* Background grid pattern */}
        <div className="absolute inset-0 opacity-10" style={{
          backgroundImage: 'linear-gradient(var(--border-color) 1px, transparent 1px), linear-gradient(90deg, var(--border-color) 1px, transparent 1px)',
          backgroundSize: '40px 40px'
        }}></div>

        <div className="flex flex-wrap items-stretch gap-2 relative z-10">
          <ArchNode step="STAGE 01" title="Sensor Input" subtitle="Existing IP CCTV" icon={Camera}>
            <div className="mt-4 flex flex-col gap-2">
              <span className="text-xs">RTSP / ONVIF Streams</span>
              {/* Was a fixed "FPS 30.0 / RESOLUTION 4K UHD" — fabricated,
                  not measured from anything. There's no single fixed
                  camera spec; this depends entirely on whatever stream is
                  connected (docs/PERFORMANCE_REPORT.md's real measured run
                  used a 768x576, ~10fps source, on CPU only). Stating that
                  honestly instead of inventing a spec. */}
              <div className="flex justify-between border-t border-color pt-2 mt-2">
                <span>FPS / RESOLUTION</span>
                <span className="text-main">Depends on source stream</span>
              </div>
            </div>
          </ArchNode>

          <Connector />

          <ArchNode step="STAGE 02" title="Edge Node" subtitle="Netraksh Inference Engine" icon={Box}>
            {/* Was "TensorRT Optimized" — never true. edge/detection/detector.py
                runs plain ultralytics YOLOv8n; docs/PERFORMANCE_REPORT.md's
                real measured run states this explicitly: "on CPU only, no
                GPU, no TensorRT". */}
            <div className="text-xs mb-4">YOLOv8n &middot; CPU inference (no GPU/TensorRT)</div>
            <div className="flex flex-col gap-2">
              <span className="flex items-center gap-2 text-ok"><ShieldCheck size={14}/> HEALTH GATE</span>
              <span className="flex items-center gap-2 text-ok"><ShieldCheck size={14}/> CONDITION GATE</span>
              <span className="flex items-center gap-2 text-ok"><ShieldCheck size={14}/> DETECTION GATE</span>
            </div>
          </ArchNode>

          <Connector />

          <div className="relative" style={CARD_FLEX}>
            <div className="absolute -top-3 right-4 bg-ok text-black font-display px-2 py-0.5 rounded font-bold z-20" style={{ fontSize: '10px' }}>CORE DIFFERENTIATOR</div>
            <ArchNode step="STAGE 03" title="Reliability Gate" subtitle="Netraksh Confidence Filter" icon={ShieldCheck} isCore={true}>
              {/* Was "DETECTED >=85% / UNCERTAIN 50-84% / ABSTAIN <50%" — not
                  the real gate at all. The real Hybrid Reliability Engine
                  (edge/reliability/decision.py) is R = 0.40D + 0.20T + 0.20S
                  + 0.20H banded at RELIABILITY_R_THRESHOLD (0.75); ABSTAIN
                  is not a low-R band, it's Gate 1's hard override on a
                  camera-health failure, independent of R entirely. */}
              <div className="flex flex-col gap-2 mt-1">
                <div className="bg-[rgba(74,222,128,0.1)] border border-ok text-ok p-2 rounded flex items-center gap-2 text-xs">
                  <div className="w-2 h-2 rounded-full bg-ok"></div> DETECTED (R &ge; 0.75)
                </div>
                <div className="bg-[rgba(251,191,36,0.1)] border border-warning text-warning p-2 rounded flex items-center gap-2 text-xs">
                  <div className="w-2 h-2 rounded-full bg-warning"></div> UNCERTAIN (R &lt; 0.75)
                </div>
                <div className="bg-[rgba(100,116,139,0.1)] border border-neutral text-neutral p-2 rounded flex items-center gap-2 text-xs">
                  <div className="w-2 h-2 rounded-full bg-neutral"></div> ABSTAIN (camera health failed &mdash; Gate 1 override)
                </div>
              </div>
              <div className="text-muted mt-3 font-mono" style={{ fontSize: '10px' }}>R = 0.40&middot;D + 0.20&middot;T + 0.20&middot;S + 0.20&middot;H</div>
            </ArchNode>
          </div>

          <Connector />

          <ArchNode step="STAGE 04" title="Command Server" subtitle="Netraksh HQ Aggregator" icon={Server}>
            <div className="mt-4">
              Store &amp; Forward Logic
            </div>
          </ArchNode>
        </div>

        {/* Flow note tying the pipeline row into the two ledger paths below —
            replaces a previous layout that left ~30% of the row as dead
            whitespace (Evidence Chain at 30% width + Blockchain at 40%,
            nothing filling the remaining ~30%) with an explicit statement
            of the real branching rule instead. */}
        <div className="flex items-center gap-3 relative z-10 text-xs text-muted font-body" style={{ borderTop: '1px dashed var(--border-color)', paddingTop: '1.5rem' }}>
          <ArrowRight size={14} className="text-muted" style={{ flexShrink: 0 }} />
          <span>Every event is written to the local Evidence Chain. Only <span className="text-danger">high-severity, cross-command</span> events are additionally submitted to the Permissioned Ledger.</span>
        </div>

        <div className="flex flex-wrap items-stretch gap-4 relative z-10">
          <div className="bg-panel border border-color rounded p-4 flex flex-col" style={{ flex: '1 1 280px', minWidth: 0 }}>
            <div className="flex items-center gap-2 mb-3 pb-2 border-b border-color text-muted">
              <Database size={16} />
              <span className="text-xs font-display uppercase tracking-widest">Evidence Chain</span>
            </div>
            <h3 className="text-main font-display mb-1" style={{ fontSize: '0.95rem' }}>Local Ledger</h3>
            <div className="text-sm font-body text-muted flex-grow">
              <div className="mt-1 text-xs">Cryptographic Hashing &middot; every event, always</div>
              {/* Was a hardcoded literal SHA-256 hash shown for every visit —
                  and specifically the well-known hash of the *empty string*,
                  which looks like a real captured value but isn't one.
                  edge/evidence/packager.py computes a real per-event SHA-256
                  over the actual evidence bytes; there's no single fixed
                  value to show here without a real selected event. */}
              <div className="mt-4 p-2 bg-dark rounded font-mono break-all text-muted border border-color" style={{ fontSize: '10px' }}>
                SHA-256 computed per-event over real evidence bytes at capture time — see Evidence page for a real event's hash.
              </div>
            </div>
          </div>

          <div className="bg-[rgba(239,68,68,0.05)] border border-danger rounded p-4 flex flex-col glow-danger" style={{ flex: '1 1 340px', minWidth: 0 }}>
            <div className="flex justify-between items-center gap-2 mb-3 pb-2 text-danger" style={{ borderBottom: '1px solid rgba(239,68,68,0.2)' }}>
              <div className="flex items-center gap-2">
                <Link size={16} />
                <span className="text-xs font-display uppercase tracking-widest">Blockchain</span>
              </div>
              <span className="bg-danger text-white px-1 rounded" style={{ fontSize: '10px' }}>HIGH-SEVERITY CROSS-COMMAND ONLY</span>
            </div>
            <h3 className="text-main font-display mb-1 text-danger" style={{ fontSize: '0.95rem' }}>Permissioned Ledger</h3>
            {/* Was "Hyperledger Fabric consensus network" stated as fact —
                backend/services/blockchain.py's own real, honest labeling
                is MOCK mode (WSL2/Docker unavailable on this deployment),
                with FabricCLIAdapter left in place, unused, as a real
                documented one-line swap for when Fabric becomes available.
                This page should say the same thing the running system
                actually says at runtime, not a stronger claim. */}
            <div className="text-sm font-body text-muted flex-grow mt-1">
              Hyperledger Fabric-compatible adapter &mdash; running in MOCK mode (WSL2/Docker unavailable on this deployment); real Fabric is a documented one-line swap.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
