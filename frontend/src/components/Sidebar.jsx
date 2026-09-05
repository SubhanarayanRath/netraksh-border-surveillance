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
      <div className="flex-col items-center gap-2">
        <div className="flex items-center justify-center rounded border" style={{backgroundColor: 'var(--bg-elevated)', width: '52px', height: '52px'}}>
          <Logo size={36} />
        </div>
        {/* The sidebar column widened from 60px to 88px (index.css) so both
            the logo mark and this caption have real room, after the
            original 9px + tracking-widest label clipped off the viewport
            edge entirely at 60px (see docs/ARCHITECTURE.md). Still
            constrained to a fixed width with wrapping allowed as a safety
            net — not relying on it fitting exactly — so a future font/text
            change wraps to a second line instead of silently overflowing
            off-screen again. */}
        <span
          className="font-display font-bold text-ok"
          style={{
            fontSize: '11px', letterSpacing: '0.03em', lineHeight: 1.2,
            width: '72px', whiteSpace: 'normal', wordBreak: 'break-word',
            // `text-center` (Tailwind utility class) computed as
            // text-align: start here, not center — confirmed via
            // getComputedStyle, not assumed — so the word rendered
            // left-aligned inside its own centered box (the box was
            // centered in the sidebar; the glyphs inside it weren't
            // centered within the box). Set inline instead, which always
            // wins regardless of whatever is overriding the utility class.
            textAlign: 'center',
          }}
        >
          NETRAKSH
        </span>
      </div>

      <div className="flex-col gap-4" style={{width: '48px'}}>
        <Link to="/" className={getClassName("/")} title="Dashboard" style={{width: '48px', height: '48px'}}>
          <Eye size={22} />
        </Link>
        <Link to="/camera-health" className={getClassName("/camera-health")} title="Camera Health" style={{width: '48px', height: '48px'}}>
          <Activity size={22} />
        </Link>
        <Link to="/evidence" className={getClassName("/evidence")} title="Evidence Vault" style={{width: '48px', height: '48px'}}>
          <Shield size={22} />
        </Link>
        <Link to="/cross-command-alerts" className={getClassName("/cross-command-alerts")} title="Cross-Command Alerts" style={{width: '48px', height: '48px'}}>
          <Bell size={22} />
        </Link>
        <Link to="/architecture" className={getClassName("/architecture")} title="Architecture" style={{width: '48px', height: '48px'}}>
          <Map size={22} />
        </Link>
      </div>
    </nav>
  );
}
