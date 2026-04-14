import { useState, useEffect } from 'react';
import Login from './components/Login';
import Dashboard from './components/Dashboard';
import MemberDetails from './components/MemberDetails';
import Analytics from './components/Analytics';
import './App.css';

function App() {
  const [user, setUser] = useState(null);
  const [selectedMember, setSelectedMember] = useState(null);
  const [view, setView] = useState('dashboard'); // 'dashboard', 'analytics', or 'details'

  // Check if already logged in
  useEffect(() => {
    const stored =
      sessionStorage.getItem('hedis_logged_in') === 'true'
        ? sessionStorage.getItem('hedis_user')
        : localStorage.getItem('hedis_logged_in') === 'true'
          ? localStorage.getItem('hedis_user')
          : null;
    if (stored) setUser(stored);
  }, []);

  const handleLogin = (username) => {
    setUser(username);
  };

  const handleLogout = () => {
    sessionStorage.removeItem('hedis_logged_in');
    sessionStorage.removeItem('hedis_user');
    localStorage.removeItem('hedis_logged_in');
    localStorage.removeItem('hedis_user');
    setUser(null);
    setView('dashboard');
    setSelectedMember(null);
  };

  const handleMemberSelect = (member) => {
    setSelectedMember(member);
    setView('details');
  };

  const handleBackToDashboard = () => {
    setSelectedMember(null);
    setView('dashboard');
  };

  if (!user) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <div className="header-left">
            <img
              src="/ct-logo.png"
              alt="Cognizant Logo"
              className="cognizant-logo"
            />
            <div className="header-divider"></div>
            <div className="header-title-section">
              <h1>Care Gap Management System</h1>
              <p className="header-subtitle">HEDIS Quality Measure Compliance & Member Outreach</p>
            </div>
          </div>
          <nav className="header-nav">
            <button
              className={view === 'dashboard' ? 'active' : ''}
              onClick={() => { setView('dashboard'); setSelectedMember(null); }}
            >
              Dashboard
            </button>
            <button
              className={view === 'analytics' ? 'active' : ''}
              onClick={() => { setView('analytics'); setSelectedMember(null); }}
            >
              Analytics
            </button>
            <button className="logout-btn" onClick={handleLogout}>
              Logout
            </button>
          </nav>
        </div>
      </header>

      <main className="app-main">
        {view === 'dashboard' ? (
          <Dashboard onMemberSelect={handleMemberSelect} />
        ) : view === 'analytics' ? (
          <Analytics />
        ) : (
          <MemberDetails
            member={selectedMember}
            onBack={handleBackToDashboard}
          />
        )}
      </main>
    </div>
  );
}

export default App;
