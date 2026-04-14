import { useState } from 'react';
import './Login.css';

function Login({ onLogin }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');

    if (!username.trim() || !password) {
      setError('Please enter both username and password.');
      return;
    }

    // Store login state
    const storage = remember ? localStorage : sessionStorage;
    storage.setItem('hedis_logged_in', 'true');
    storage.setItem('hedis_user', username.trim());

    onLogin(username.trim());
  };

  return (
    <div className="login-page">
      <div className="login-wrapper">
        <div className="login-logo">
          <img src="/ct-logo.png" alt="Cognizant Logo" />
          <h1>Care Gap Management System</h1>
          <p>AI-POWERED PLATFORM</p>
        </div>

        <div className="login-card">
          <h2>Sign In</h2>
          <p className="subtitle">Access the care management platform</p>

          {error && <div className="login-error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="login-form-group">
              <label htmlFor="username">Username</label>
              <input
                type="text"
                id="username"
                placeholder="Enter your username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            <div className="login-form-group">
              <label htmlFor="password">Password</label>
              <input
                type="password"
                id="password"
                placeholder="Enter your password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            <div className="login-remember-row">
              <label>
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                Remember me
              </label>
              <a href="#" onClick={(e) => e.preventDefault()}>Forgot password?</a>
            </div>

            <button type="submit" className="login-btn">Sign In</button>
          </form>
        </div>

        <div className="login-footer">
          HEDIS Care Gap Management — Powered by AI Agents & Knowledge Graph
        </div>
      </div>
    </div>
  );
}

export default Login;
