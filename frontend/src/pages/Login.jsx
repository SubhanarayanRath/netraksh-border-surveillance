import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Lock } from 'lucide-react';
import { login } from '../services/auth';
import Logo from '../components/Logo';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  
  const navigate = useNavigate();
  const location = useLocation();

  const from = location.state?.from?.pathname || "/";

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-screen w-full items-center justify-center bg-background">
      <div className="w-full max-w-sm p-8 bg-panel border border-color rounded shadow-lg flex flex-col gap-6">
        <div className="flex flex-col items-center gap-4">
          <Logo size={48} />
          <div className="flex flex-col items-center text-center">
            <h1 className="text-2xl font-display tracking-widest text-main m-0 p-0" style={{lineHeight: 1}}>NETRAKSH</h1>
            <span className="text-sm text-muted font-display tracking-widest mt-1">BORDER INTELLIGENCE UNIT</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="w-full flex flex-col gap-3">
          <div className="flex items-center gap-1 text-muted mb-1 justify-center">
            <Lock size={14} />
            <span className="text-xs font-display uppercase tracking-widest">Sign in to continue</span>
          </div>
          
          <input
            type="text" placeholder="Username" value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full bg-dark border border-color rounded py-2 px-3 text-sm text-main"
          />
          <input
            type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full bg-dark border border-color rounded py-2 px-3 text-sm text-main"
          />
          {error && <span className="text-xs text-danger text-center">{error}</span>}
          
          <button
            type="submit" disabled={submitting}
            className="w-full bg-white hover:bg-gray-200 text-black py-2 rounded font-display text-sm uppercase tracking-widest transition-colors mt-2"
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
