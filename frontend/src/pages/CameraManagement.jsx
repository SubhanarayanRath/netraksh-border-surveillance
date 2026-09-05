import { useState, useEffect, useCallback } from 'react';
import { MapPin, Plus, Save, ShieldAlert } from 'lucide-react';
import { authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';
import LoginPrompt from '../components/LoginPrompt';

// The first genuinely ADMIN-exclusive page in this app — every other page
// is readable by any authenticated role (require_any_role on the backend).
// PUT /cameras/{id}/location and POST /cameras have always been real,
// ADMIN-gated endpoints (backend/api/cameras.py) — this is what actually
// exposes them anywhere in the UI, previously only reachable via a script
// or curl. Backend RBAC (require_admin) is the real enforcement; the
// client-side role check below is just an honest reflection of it, not a
// substitute for it — a non-admin hitting the real endpoints here would
// still get a real 403.
export default function CameraManagement() {
  const { role } = useAuth();
  const [cameras, setCameras] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | auth-required | forbidden | error
  const [editingId, setEditingId] = useState(null);
  const [editLat, setEditLat] = useState('');
  const [editLon, setEditLon] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  const [newName, setNewName] = useState('');
  const [newLocation, setNewLocation] = useState('');
  const [newLat, setNewLat] = useState('');
  const [newLon, setNewLon] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState(null);

  const loadCameras = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await authFetch('/cameras');
      if (res.status === 401) {
        setStatus('auth-required');
        return;
      }
      if (res.status === 403) {
        setStatus('forbidden');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setCameras(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => { loadCameras(); }, [loadCameras]);

  const startEdit = (cam) => {
    setEditingId(cam.camera_id);
    setEditLat(cam.latitude != null ? String(cam.latitude) : '');
    setEditLon(cam.longitude != null ? String(cam.longitude) : '');
    setSaveError(null);
  };

  const saveLocation = async (cameraId) => {
    const lat = parseFloat(editLat);
    const lon = parseFloat(editLon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      setSaveError('Latitude and longitude must both be real numbers.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const res = await authFetch(`/cameras/${cameraId}/location`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude: lat, longitude: lon }),
      });
      if (res.status === 403) {
        setSaveError('Only ADMIN can set a camera location (real backend RBAC, not just this UI).');
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setSaveError(data.detail || 'Save failed.');
        return;
      }
      setEditingId(null);
      await loadCameras();
    } catch (_e) {
      setSaveError('Could not reach the backend.');
    } finally {
      setSaving(false);
    }
  };

  const registerCamera = async (e) => {
    e.preventDefault();
    if (!newName.trim() || !newLocation.trim()) {
      setRegisterError('Name and location are both required.');
      return;
    }
    setRegistering(true);
    setRegisterError(null);
    try {
      const body = { name: newName.trim(), location: newLocation.trim() };
      const lat = parseFloat(newLat);
      const lon = parseFloat(newLon);
      if (!Number.isNaN(lat) && !Number.isNaN(lon)) {
        body.latitude = lat;
        body.longitude = lon;
      }
      const res = await authFetch('/cameras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.status === 403) {
        setRegisterError('Only ADMIN can register a camera (real backend RBAC, not just this UI).');
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setRegisterError(data.detail || 'Registration failed.');
        return;
      }
      setNewName(''); setNewLocation(''); setNewLat(''); setNewLon('');
      await loadCameras();
    } catch (_e) {
      setRegisterError('Could not reach the backend.');
    } finally {
      setRegistering(false);
    }
  };

  return (
    <div className="h-full flex flex-col gap-6">
      <div className="flex-col">
        <h2 className="text-xl font-display text-main tracking-widest uppercase">Camera Management</h2>
        <p className="text-sm font-body text-muted">
          Register cameras and set their real map coordinates — ADMIN role only, enforced by the
          real backend (not just hidden here for other roles).
        </p>
      </div>

      {status === 'auth-required' && (
        <div className="max-w-xs bg-panel border rounded p-4">
          <LoginPrompt message="Sign in as ADMIN" onSuccess={loadCameras} />
        </div>
      )}

      {(status === 'forbidden' || (status === 'ready' && role !== 'ADMIN')) && (
        <div className="max-w-md bg-panel border border-danger rounded p-4 flex items-center gap-3">
          <ShieldAlert size={24} className="text-danger flex-shrink-0" />
          <span className="text-sm font-body text-main">
            Signed in as <strong>{role}</strong> — this page is ADMIN-only. The backend already
            enforces this for real (every request above used a real 403), this message just
            explains why nothing below is editable for you.
          </span>
        </div>
      )}

      {status === 'loading' && <div className="text-muted text-sm text-center mt-8">Loading real camera list…</div>}
      {status === 'error' && <div className="text-danger text-sm text-center mt-8">Could not reach the backend.</div>}

      {status === 'ready' && (
        <div className="flex flex-col gap-6 overflow-y-auto pr-2">
          <div className="bg-panel border rounded overflow-hidden">
            <table className="w-full text-sm font-body">
              <thead>
                <tr className="text-left text-xs font-display text-muted uppercase border-b border-color">
                  <th className="p-3">Camera</th>
                  <th className="p-3">Location</th>
                  <th className="p-3">Coordinates</th>
                  <th className="p-3">Health</th>
                  {role === 'ADMIN' && <th className="p-3"></th>}
                </tr>
              </thead>
              <tbody>
                {cameras.map((cam) => (
                  <tr key={cam.camera_id} className="border-b border-color last:border-b-0">
                    <td className="p-3 text-main">{cam.name}<div className="text-xs text-muted">{cam.camera_id}</div></td>
                    <td className="p-3 text-muted">{cam.location}</td>
                    <td className="p-3">
                      {editingId === cam.camera_id ? (
                        <div className="flex flex-col gap-1">
                          <div className="flex gap-1">
                            <input value={editLat} onChange={(e) => setEditLat(e.target.value)} placeholder="lat" className="w-20 bg-dark border border-color rounded px-1.5 py-1 text-xs text-main" />
                            <input value={editLon} onChange={(e) => setEditLon(e.target.value)} placeholder="lon" className="w-20 bg-dark border border-color rounded px-1.5 py-1 text-xs text-main" />
                            <button onClick={() => saveLocation(cam.camera_id)} disabled={saving} className="text-ok border border-ok rounded px-2 hover:bg-[rgba(74,222,128,0.1)] disabled:opacity-50">
                              <Save size={14} />
                            </button>
                          </div>
                          {saveError && <span className="text-[10px] text-danger">{saveError}</span>}
                        </div>
                      ) : (
                        <span className="text-muted">
                          {cam.latitude != null ? `${cam.latitude.toFixed(4)}, ${cam.longitude.toFixed(4)}` : 'not set'}
                        </span>
                      )}
                    </td>
                    <td className="p-3">
                      <span className={cam.health_state === 'OK' ? 'text-ok' : cam.health_state === 'DEGRADED' ? 'text-warning' : cam.health_state === 'FAILED' ? 'text-danger' : 'text-muted'}>
                        {cam.health_state || 'no data yet'}
                      </span>
                    </td>
                    {role === 'ADMIN' && (
                      <td className="p-3">
                        {editingId !== cam.camera_id && (
                          <button onClick={() => startEdit(cam)} className="text-muted hover:text-main flex items-center gap-1 text-xs">
                            <MapPin size={14} /> Set location
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {role === 'ADMIN' && (
            <div className="bg-panel border rounded p-6 max-w-lg">
              <div className="flex items-center gap-2 mb-4">
                <Plus size={18} className="text-ok" />
                <span className="font-display text-main uppercase">Register New Camera</span>
              </div>
              <form onSubmit={registerCamera} className="flex flex-col gap-3">
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Name (e.g. Border Post Gamma)" className="bg-dark border border-color rounded px-3 py-2 text-sm text-main" />
                <input value={newLocation} onChange={(e) => setNewLocation(e.target.value)} placeholder="Location (e.g. Sector 9)" className="bg-dark border border-color rounded px-3 py-2 text-sm text-main" />
                <div className="flex gap-2">
                  <input value={newLat} onChange={(e) => setNewLat(e.target.value)} placeholder="Latitude (optional)" className="flex-1 bg-dark border border-color rounded px-3 py-2 text-sm text-main" />
                  <input value={newLon} onChange={(e) => setNewLon(e.target.value)} placeholder="Longitude (optional)" className="flex-1 bg-dark border border-color rounded px-3 py-2 text-sm text-main" />
                </div>
                {registerError && <span className="text-xs text-danger">{registerError}</span>}
                <button type="submit" disabled={registering} className="bg-white hover:bg-gray-200 text-black py-2 rounded font-display text-sm uppercase tracking-widest disabled:opacity-50">
                  {registering ? 'Registering…' : 'Register Camera'}
                </button>
              </form>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
