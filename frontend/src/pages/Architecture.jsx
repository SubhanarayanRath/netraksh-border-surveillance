import { Box, Server, Camera, ShieldCheck, Database, Link, ArrowRight } from 'lucide-react';

export default function Architecture() {
  const ArchNode = ({ title, subtitle, icon: Icon, children, isCore }) => (
    <div className={`bg-panel border rounded p-4 flex flex-col ${isCore ? 'border-ok glow-ok' : 'border-color'}`}>
      <div className="flex items-center gap-2 mb-4 text-muted border-b border-color pb-2">
        <Icon size={16} />
        <span className="text-xs font-display uppercase tracking-widest">{title}</span>
      </div>
      <h3 className="text-main font-display mb-1">{subtitle}</h3>
      <div className="text-sm font-body text-muted flex-grow">
        {children}
      </div>
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase mb-2">Netraksh System Architecture</h2>
        <p className="text-sm font-body text-muted max-w-3xl">
          End-to-end data pipeline from physical sensor arrays to permissioned ledger consensus. Designed for zero-trust environments requiring immutable audit trails.
        </p>
      </div>

      <div className="flex-grow flex flex-col gap-8 justify-center p-8 bg-[rgba(15,23,42,0.5)] rounded border border-color relative overflow-hidden">
        {/* Background grid pattern */}
        <div className="absolute inset-0 opacity-10" style={{
          backgroundImage: 'linear-gradient(var(--border-color) 1px, transparent 1px), linear-gradient(90deg, var(--border-color) 1px, transparent 1px)',
          backgroundSize: '40px 40px'
        }}></div>

        <div className="flex gap-4 relative z-10 items-stretch h-64">
          <div className="w-1/4">
            <ArchNode title="Sensor Input" subtitle="Existing IP CCTV" icon={Camera}>
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
          </div>

          <div className="flex items-center text-muted"><ArrowRight /></div>

          <div className="w-1/4">
            <ArchNode title="Edge Node" subtitle="Netraksh Inference Engine" icon={Box}>
              {/* Was "TensorRT Optimized" — never true. edge/detection/detector.py
                  runs plain ultralytics YOLOv8n; docs/PERFORMANCE_REPORT.md's
                  real measured run states this explicitly: "on CPU only, no
                  GPU, no TensorRT". */}
              <div className="text-xs mb-4">YOLOv8n · CPU inference (no GPU/TensorRT)</div>
              <div className="flex flex-col gap-2">
                <span className="flex items-center gap-2 text-ok"><ShieldCheck size={14}/> HEALTH GATE</span>
                <span className="flex items-center gap-2 text-ok"><ShieldCheck size={14}/> CONDITION GATE</span>
                <span className="flex items-center gap-2 text-ok"><ShieldCheck size={14}/> DETECTION GATE</span>
              </div>
            </ArchNode>
          </div>

          <div className="flex items-center text-ok"><ArrowRight /></div>

          <div className="w-1/4 relative">
            <div className="absolute -top-3 right-4 bg-ok text-black text-[10px] font-display px-2 py-0.5 rounded font-bold z-20">CORE DIFFERENTIATOR</div>
            <ArchNode title="Reliability Gate" subtitle="Netraksh Confidence Filter" icon={ShieldCheck} isCore={true}>
              {/* Was "DETECTED >=85% / UNCERTAIN 50-84% / ABSTAIN <50%" — not
                  the real gate at all. The real Hybrid Reliability Engine
                  (edge/reliability/decision.py) is R = 0.40D + 0.20T + 0.20S
                  + 0.20H banded at RELIABILITY_R_THRESHOLD (0.75); ABSTAIN
                  is not a low-R band, it's Gate 1's hard override on a
                  camera-health failure, independent of R entirely. */}
              <div className="flex flex-col gap-3 mt-4">
                <div className="bg-[rgba(74,222,128,0.1)] border border-ok text-ok p-2 rounded flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-ok"></div> DETECTED (R &ge; 0.75)
                </div>
                <div className="bg-[rgba(251,191,36,0.1)] border border-warning text-warning p-2 rounded flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-warning"></div> UNCERTAIN (R &lt; 0.75)
                </div>
                <div className="bg-[rgba(100,116,139,0.1)] border border-neutral text-neutral p-2 rounded flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-neutral"></div> ABSTAIN (camera health failed — Gate 1 override)
                </div>
              </div>
              <div className="text-[10px] text-muted mt-3 font-mono">R = 0.40&middot;D + 0.20&middot;T + 0.20&middot;S + 0.20&middot;H</div>
            </ArchNode>
          </div>

          <div className="flex items-center text-muted"><ArrowRight /></div>

          <div className="w-1/4">
            <ArchNode title="Command Server" subtitle="Netraksh HQ Aggregator" icon={Server}>
              <div className="mt-4">
                Store & Forward Logic
              </div>
            </ArchNode>
          </div>
        </div>

        <div className="flex gap-4 relative z-10 justify-center">
          <div className="w-[30%]">
            <ArchNode title="Evidence Chain" subtitle="Local Ledger" icon={Database}>
              <div className="mt-2 text-xs">Cryptographic Hashing</div>
              {/* Was a hardcoded literal SHA-256 hash shown for every visit —
                  and specifically the well-known hash of the *empty string*,
                  which looks like a real captured value but isn't one.
                  edge/evidence/packager.py computes a real per-event SHA-256
                  over the actual evidence bytes; there's no single fixed
                  value to show here without a real selected event. */}
              <div className="mt-4 p-2 bg-dark rounded text-[10px] font-mono break-all text-muted border border-color">
                SHA-256 computed per-event over real evidence bytes at capture time — see Evidence page for a real event's hash.
              </div>
            </ArchNode>
          </div>

          <div className="w-[40%] ml-8">
            <div className="bg-[rgba(239,68,68,0.05)] border border-danger rounded p-4 flex flex-col glow-danger h-full">
              <div className="flex justify-between items-center mb-4 text-danger border-b border-[rgba(239,68,68,0.2)] pb-2">
                <div className="flex items-center gap-2">
                  <Link size={16} />
                  <span className="text-xs font-display uppercase tracking-widest">Blockchain</span>
                </div>
                <span className="text-[10px] bg-danger text-white px-1 rounded">HIGH-SEVERITY CROSS-COMMAND ONLY</span>
              </div>
              <h3 className="text-main font-display mb-1 text-danger">Permissioned Ledger</h3>
              {/* Was "Hyperledger Fabric consensus network" stated as fact —
                  backend/services/blockchain.py's own real, honest labeling
                  is MOCK mode (WSL2/Docker unavailable on this deployment),
                  with FabricCLIAdapter left in place, unused, as a real
                  documented one-line swap for when Fabric becomes available.
                  This page should say the same thing the running system
                  actually says at runtime, not a stronger claim. */}
              <div className="text-sm font-body text-muted flex-grow mt-2">
                Hyperledger Fabric-compatible adapter — running in MOCK mode (WSL2/Docker unavailable on this deployment); real Fabric is a documented one-line swap
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
