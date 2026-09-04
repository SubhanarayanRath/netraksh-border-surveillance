// NETRAKSH Frontend — minimal auth client.
//
// The backend has always had full JWT/RBAC infrastructure
// (backend/api/auth.py, POST /auth/token) but nothing in this frontend
// called it until GET /events/{id}/evidence-image was wired up requiring
// require_any_role. GET /events/{id} and POST /events/{id}/verify were
// later closed the same way as part of pre-deployment hardening (see
// docs/LIMITATIONS.md) — every fetch() against the backend in this
// frontend now goes through authFetch() below rather than a bare fetch(),
// kept intentionally minimal (login + token storage + an authenticated
// fetch helper), not a full auth system.

const TOKEN_KEY = 'netraksh_token';
const ROLE_KEY = 'netraksh_role';

// Derived from the page's own origin, not hardcoded to localhost. The
// backend serves this built frontend directly (single port, same origin —
// see backend/main.py's StaticFiles mount), so this resolves correctly
// whether the app is opened as http://localhost:8443 in dev or as a real
// https://<domain> once deployed, with no build-time config needed.
export const BACKEND_URL = window.location.origin;
export const WS_URL =
  (window.location.protocol === 'https:' ? 'wss://' : 'ws://') +
  window.location.host +
  '/ws/dashboard';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY);
}

export function isAuthenticated() {
  return !!getToken();
}

// POST /auth/token expects OAuth2PasswordRequestForm — form-encoded, not JSON.
export async function login(username, password) {
  const body = new URLSearchParams();
  body.set('username', username);
  body.set('password', password);

  const res = await fetch(`${BACKEND_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });

  if (!res.ok) {
    let detail = 'Login failed';
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (_e) {
      // response wasn't JSON — keep the generic message
    }
    throw new Error(detail);
  }

  const data = await res.json();
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(ROLE_KEY, data.role);
  return data;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}

// fetch() against the backend with the stored token attached, if any.
// Callers still need to check res.status themselves (401/403 = not signed
// in or wrong role, 404/409 = valid response the endpoint defines).
export async function authFetch(path, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return fetch(`${BACKEND_URL}${path}`, { ...options, headers });
}
