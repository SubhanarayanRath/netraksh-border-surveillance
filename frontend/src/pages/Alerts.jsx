import { useState, useEffect } from 'react';
import { AlertTriangle, Globe, Crosshair, MapPin } from 'lucide-react';
import useWebSocket from '../hooks/useWebSocket';
import { WS_URL } from '../services/auth';

export default function Alerts() {
  const { alerts: wsAlerts } = useWebSocket(WS_URL);
  
  const mockAlerts = [
    { id: 'ALT-992-A', severity: 'CRITICAL', title: 'Multiple Armed Intruders', location: 'Sector 7, Node Alpha', time: new Date(Date.now() - 1000 * 60 * 5).toISOString(), description: 'Group of 5 individuals detected with weapons. Moving towards perimeter fence.' },
    { id: 'ALT-814-B', severity: 'HIGH', title: 'Vehicle Ramming Attempt', location: 'East Gate Checkpoint', time: new Date(Date.now() - 1000 * 60 * 45).toISOString(), description: 'Unidentified vehicle approached gate at high speed. Retreated after warning.' },
  ];

  const displayAlerts = [...wsAlerts, ...mockAlerts];

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-grow">
        <div className="flex flex-col gap-4 overflow-y-auto pr-2">
          {displayAlerts.map(alert => (
            <div key={alert.id} className="bg-panel border border-danger rounded p-4 flex flex-col gap-3 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1 h-full bg-danger"></div>
              
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="text-danger" size={20} />
                  <span className="text-danger font-display tracking-widest">{alert.id}</span>
                </div>
                <span className="bg-danger text-white text-[10px] px-2 py-1 rounded font-display tracking-widest">{alert.severity}</span>
              </div>

              <h3 className="text-lg font-display text-main">{alert.title}</h3>
              <p className="text-sm font-body text-muted">{alert.description}</p>
              
              <div className="flex gap-6 mt-2 pt-3 border-t border-[rgba(239,68,68,0.2)] text-xs font-display text-muted">
                <span className="flex items-center gap-1"><MapPin size={14}/> {alert.location}</span>
                <span className="flex items-center gap-1"><Crosshair size={14}/> T - {Math.floor((Date.now() - new Date(alert.time)) / 60000)} MINS</span>
              </div>
            </div>
          ))}
        </div>

        <div className="bg-panel border rounded p-2 relative h-full min-h-[400px]">
          {/* Mock Map View */}
          <div className="w-full h-full bg-black rounded relative overflow-hidden" style={{ backgroundImage: 'url(/mock-map.jpg)', backgroundSize: 'cover', backgroundPosition: 'center', filter: 'grayscale(100%) sepia(20%) hue-rotate(180deg) brightness(80%)' }}>
            <div className="absolute top-0 left-0 w-full h-full bg-[rgba(15,23,42,0.7)]"></div>
            
            {/* Grid overlay */}
            <div className="absolute inset-0 opacity-20" style={{ backgroundImage: 'linear-gradient(var(--border-color) 1px, transparent 1px), linear-gradient(90deg, var(--border-color) 1px, transparent 1px)', backgroundSize: '50px 50px' }}></div>
            
            {/* Map nodes */}
            <div className="absolute top-1/4 left-1/4 flex flex-col items-center group cursor-pointer">
              <div className="w-4 h-4 bg-danger rounded-full animate-ping absolute"></div>
              <div className="w-4 h-4 bg-danger border-2 border-white rounded-full relative z-10 shadow-[0_0_10px_rgba(239,68,68,1)]"></div>
              <span className="text-[10px] font-display text-white mt-1 bg-dark px-1 rounded opacity-0 group-hover:opacity-100 transition-opacity">SECTOR 7</span>
            </div>
            
            <div className="absolute top-1/2 left-2/3 flex flex-col items-center group cursor-pointer">
              <div className="w-3 h-3 bg-ok border border-white rounded-full relative z-10 shadow-[0_0_5px_rgba(74,222,128,1)]"></div>
              <span className="text-[10px] font-display text-white mt-1 bg-dark px-1 rounded opacity-0 group-hover:opacity-100 transition-opacity">HQ</span>
            </div>

            <div className="absolute bottom-1/4 right-1/3 flex flex-col items-center group cursor-pointer">
              <div className="w-3 h-3 bg-ok border border-white rounded-full relative z-10 shadow-[0_0_5px_rgba(74,222,128,1)]"></div>
              <span className="text-[10px] font-display text-white mt-1 bg-dark px-1 rounded opacity-0 group-hover:opacity-100 transition-opacity">NODE C</span>
            </div>

            <div className="absolute bottom-4 left-4 text-xs font-display text-muted bg-dark border rounded px-2 py-1">TACTICAL OVERVIEW</div>
          </div>
        </div>
      </div>
    </div>
  );
}
