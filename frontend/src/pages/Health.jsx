import { useState, useEffect } from 'react';
import { CameraOff, AlertTriangle, ShieldCheck, Activity } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL } from '../services/auth';

export default function Health() {
  const { health } = useWebSocket(WS_URL);

  const mockCameras = [
    { id: 'CAM-07', zone: 'North Fence', status: 'OK', fps: 30, jitter: 2, blur: 0.1, exposure: 'BAL', drift: 0.8, ai: 'NOMINAL' },
    { id: 'CAM-12', zone: 'Sector B', status: 'DEGRADED', fps: 12, jitter: 45, blur: 0.7, exposure: 'LOW', drift: 1.2, ai: '< 40%' },
    { id: 'CAM-04', zone: 'East Gate', status: 'FAILED', fps: 0, jitter: null, blur: null, exposure: 'N/A', drift: null, ai: 'FROZEN' },
  ];

  // Merge websocket health data with mock data if available
  const cameras = mockCameras.map(cam => {
    if (health[cam.id]) {
      const h = health[cam.id];
      return {
        ...cam,
        status: h.status, // OK, DEGRADED, FAILED
        fps: h.fps,
        blur: h.blur_score,
      };
    }
    return cam;
  });

  const CameraCard = ({ cam }) => {
    let borderColor = 'border-color';
    let badgeColor = 'bg-neutral text-white';
    
    if (cam.status === 'OK') {
      borderColor = 'border-ok';
      badgeColor = 'bg-ok text-black';
    } else if (cam.status === 'DEGRADED') {
      borderColor = 'border-warning';
      badgeColor = 'bg-warning text-black';
    } else if (cam.status === 'FAILED') {
      borderColor = 'border-danger';
      badgeColor = 'bg-danger text-white';
    }

    return (
      <div className={`bg-panel border rounded flex flex-col overflow-hidden ${borderColor}`}>
        <div className="h-32 w-full relative bg-black flex items-center justify-center">
          {cam.status === 'FAILED' ? (
            <div className="flex flex-col items-center gap-2 text-danger">
              <CameraOff size={32} />
              <span className="text-xs font-display tracking-widest">NO SIGNAL</span>
            </div>
          ) : (
            <div className="w-full h-full relative" style={{ backgroundImage: 'url(/mock-fence.jpg)', backgroundSize: 'cover', backgroundPosition: 'center', filter: cam.status === 'DEGRADED' ? 'blur(4px) brightness(0.5)' : 'none' }}>
              <div className="absolute top-2 left-2 text-[10px] font-display bg-white text-black px-1 rounded">{cam.status === 'OK' ? 'ONLINE' : 'DEGRADED'}</div>
              <div className="absolute bottom-2 right-2 text-[10px] font-display bg-dark border rounded px-1 text-muted text-white">LIVE</div>
            </div>
          )}
          {cam.status === 'DEGRADED' && (
            <div className="absolute top-2 right-2 text-[10px] font-display bg-dark border rounded px-1 text-muted text-white">IR FALLBACK</div>
          )}
          {cam.status === 'FAILED' && (
            <div className="absolute top-2 left-2 text-[10px] font-display bg-danger text-white px-1 rounded">FAILED</div>
          )}
        </div>
        
        <div className="p-4 flex flex-col gap-4">
          <div className="flex justify-between items-center border-b border-color pb-2">
            <span className="text-main font-display">{cam.id}</span>
            <span className="text-xs text-muted">{cam.zone}</span>
          </div>

          <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-xs font-display text-muted uppercase">
            <div className="flex-col">
              <span>FPS / JITTER</span>
              <span className="text-main mt-1 block">{cam.fps} <span className="lowercase">Δ {cam.jitter || 0}ms</span></span>
            </div>
            <div className="flex-col">
              <span>BLUR INDEX {cam.status === 'DEGRADED' ? '(FOG)' : ''}</span>
              <span className="text-main mt-1 block">{cam.blur !== null ? cam.blur : '-'}</span>
            </div>
            <div className="flex-col">
              <span>EXPOSURE</span>
              <span className="text-main mt-1 block">{cam.exposure}</span>
            </div>
            <div className="flex-col">
              <span>SYNC DRIFT</span>
              <span className="text-main mt-1 block lowercase">Δ {cam.drift !== null ? `${cam.drift}s` : 'N/A'}</span>
            </div>
          </div>

          <div className="mt-auto pt-4 border-t border-color flex justify-between items-center text-xs font-display">
            <span className="text-muted">AI ENGINE</span>
            {cam.status === 'FAILED' ? (
              <span className="text-danger flex items-center gap-1"><CameraOff size={12}/> {cam.ai}</span>
            ) : cam.status === 'DEGRADED' ? (
              <span className="text-warning flex items-center gap-1"><AlertTriangle size={12}/> {cam.ai}</span>
            ) : (
              <span className="text-ok flex items-center gap-1"><ShieldCheck size={12}/> {cam.ai}</span>
            )}
          </div>
          
          {cam.status === 'FAILED' && (
            <button className="w-full mt-2 py-2 border border-danger text-danger text-xs font-display rounded hover:bg-[rgba(239,68,68,0.1)]">
              ⟲ INITIATE REBOOT
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex justify-between items-start">
        <div className="flex-col max-w-2xl">
          <h2 className="text-xl font-display text-main tracking-widest uppercase mb-2">CAMERA HEALTH MATRIX</h2>
          <p className="text-sm font-body text-muted">
            Real-time status of all perimeter visual sensors. Highlighting optical clarity, latency drift, and connection state to ensure continuous intelligence gathering.
          </p>
        </div>
        <div className="bg-panel border rounded p-4 flex gap-4 items-center">
          <div className="relative w-16 h-16 rounded-full border-4 border-ok flex items-center justify-center">
            <span className="font-display text-main text-lg">82%</span>
          </div>
          <div className="flex flex-col gap-1 text-xs font-display">
            <span className="text-muted">System Sight</span>
            <span className="text-ok flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-ok"></div> 36 OK</span>
            <span className="text-warning flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-warning"></div> 5 DEGRADED</span>
            <span className="text-danger flex items-center gap-1"><div className="w-2 h-2 rounded-full bg-danger"></div> 3 FAILED</span>
          </div>
        </div>
      </div>

      <div className="flex gap-4">
        <button className="bg-ok text-black px-4 py-2 rounded text-sm font-display flex items-center gap-2">
           All Sectors
        </button>
        <button className="bg-transparent border border-color text-muted px-4 py-2 rounded text-sm font-display flex items-center gap-2 hover-bg-elevated">
          <AlertTriangle size={14} /> Needs Attention (8)
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {cameras.map(cam => <CameraCard key={cam.id} cam={cam} />)}
      </div>
    </div>
  );
}
