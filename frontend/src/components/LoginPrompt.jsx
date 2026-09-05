import { useState } from 'react';
import { Lock } from 'lucide-react';
import { login } from '../services/auth';

// Shared inline login form — extracted from Evidence.jsx (which had this
// exact markup duplicated inline) so Health.jsx can gate its own
// auth-required GET /cameras call the same way, without copy-pasting the
// form fields, error handling, and submitting state a second time.
export default function LoginPrompt({ onSuccess, message = 'Sign in to view this data' }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      onSuccess?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full flex flex-col gap-2">
      <div className="flex items-center gap-1 text-muted mb-1">
        <Lock size={12} />
        <span className="text-[10px] font-display uppercase tracking-widest">{message}</span>
      </div>
      <input
        type="text" placeholder="Username" value={username}
        onChange={(e) => setUsername(e.target.value)}
        className="w-full bg-dark border border-color rounded py-1.5 px-2 text-xs text-main"
      />
      <input
        type="password" placeholder="Password" value={password}
        onChange={(e) => setPassword(e.target.value)}
        className="w-full bg-dark border border-color rounded py-1.5 px-2 text-xs text-main"
      />
      {error && <span className="text-[10px] text-danger">{error}</span>}
      <button
        type="submit" disabled={submitting}
        className="w-full bg-white hover:bg-gray-200 text-black py-1.5 rounded font-display text-xs uppercase tracking-widest transition-colors"
      >
        {submitting ? 'Signing in...' : 'Sign in'}
      </button>
    </form>
  );
}
