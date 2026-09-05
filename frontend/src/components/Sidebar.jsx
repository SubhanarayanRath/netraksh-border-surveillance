import { Link, useLocation } from 'react-router-dom';
import { Eye, Shield, Map, Activity, Bell } from 'lucide-react';
import Logo from './Logo';

export default function Sidebar() {
  const location = useLocation();
  const path = location.pathname;

  const getClassName = (activePath) => {
    const base = "w-full h-full flex items-center justify-center rounded transition-colors";
    return path === activePath 
      ? `${base} bg-ok` 
      : `${base} text-muted hover-bg-elevated`;
  };

  return (
    <nav className="sidebar-left">
      <div className="flex-col items-center gap-1">
        <div className="w-10 h-10 flex items-center justify-center rounded border" style={{backgroundColor: 'var(--bg-elevated)'}}>
          <Logo size={26} />
        </div>
        <span className="text-[9px] font-display font-bold tracking-widest text-ok" style={{lineHeight: 1}}>NETRAKSH</span>
      </div>

      <div className="flex-col gap-4" style={{width: '40px', height: '40px'}}>
        <Link to="/" className={getClassName("/")} title="Dashboard">
          <Eye size={20} />
        </Link>
        <Link to="/camera-health" className={getClassName("/camera-health")} title="Camera Health">
          <Activity size={20} />
        </Link>
        <Link to="/evidence" className={getClassName("/evidence")} title="Evidence Vault">
          <Shield size={20} />
        </Link>
        <Link to="/cross-command-alerts" className={getClassName("/cross-command-alerts")} title="Cross-Command Alerts">
          <Bell size={20} />
        </Link>
        <Link to="/architecture" className={getClassName("/architecture")} title="Architecture">
          <Map size={20} />
        </Link>
      </div>
    </nav>
  );
}
