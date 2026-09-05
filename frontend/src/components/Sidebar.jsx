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
        {/* This sidebar column is a fixed 60px (.sidebar-left, index.css) — at
            9px + tracking-widest, "NETRAKSH" in Space Grotesk (a wide
            geometric font) overflowed past the container's left edge and,
            since this is the leftmost column at x=0, past the browser
            viewport itself, clipping the "N" instead of wrapping or
            shrinking to fit. Constrained to the icon rail's own 40px width
            with no extra letter-spacing and explicit wrapping allowed as a
            safety net, so even if a font metric runs slightly wide again,
            it wraps to a second line instead of clipping off-screen. */}
        <span
          className="font-display font-bold text-ok text-center"
          style={{ fontSize: '6px', lineHeight: 1.2, width: '40px', whiteSpace: 'normal', wordBreak: 'break-word' }}
        >
          NETRAKSH
        </span>
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
