import { useState } from 'react';
import { Mail, Lock, Eye, EyeOff } from 'lucide-react';
import './Login.css';

function Login({ onLogin }) {
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [showPwd, setShowPwd]   = useState(false);
  const [error, setError]       = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');

    if (!email.trim() || !password) {
      setError('Please enter both Email ID and password.');
      return;
    }

    sessionStorage.setItem('hedis_logged_in', 'true');
    sessionStorage.setItem('hedis_user', email.trim());

    onLogin(email.trim());
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <img src="/CTS.png" alt="Cognizant" />
          <span className="login-logo-text">Cognizant</span>
        </div>

        <h2 className="login-title">Sign In</h2>
        <p className="login-subtitle">Access the Care Gap Management platform</p>

        {error && <div className="login-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <label className="login-label" htmlFor="email">Email ID</label>
          <div className="login-input-wrap">
            <Mail size={18} className="login-input-icon" />
            <input
              type="email"
              id="email"
              placeholder="name@cognizant.com"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <label className="login-label" htmlFor="password">Password</label>
          <div className="login-input-wrap">
            <Lock size={18} className="login-input-icon" />
            <input
              type={showPwd ? 'text' : 'password'}
              id="password"
              placeholder="Enter your password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              className="login-eye"
              onClick={() => setShowPwd(v => !v)}
              aria-label={showPwd ? 'Hide password' : 'Show password'}
            >
              {showPwd ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>

          <div className="login-forgot-row">
            <a href="#" onClick={(e) => e.preventDefault()}>Forgot password?</a>
          </div>

          <button type="submit" className="login-btn">Sign In</button>
        </form>
      </div>

      <div className="login-footer">
        © Cognizant — Care Gap Management powered by AI Agents &amp; Knowledge Graph
      </div>
    </div>
  );
}

export default Login;
