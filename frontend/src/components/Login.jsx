import { useState, useRef, useEffect, useCallback } from 'react';
import './Login.css';

/* ── Animated knowledge-graph background ──────────────────────────────────── */
const GRAPH_LABELS = ['Member', 'Persona', 'Measure', 'Provider', 'CareGap'];
const GRAPH_COLORS = {
  Member:   { fill: '#000048', stroke: 'rgba(38,239,233,0.6)' },
  Persona:  { fill: 'rgba(38,239,233,0.15)', stroke: '#26EFE9' },
  Measure:  { fill: 'rgba(233,199,29,0.12)', stroke: '#E9C71D' },
  Provider: { fill: 'rgba(45,184,31,0.10)', stroke: '#2DB81F' },
  CareGap:  { fill: 'rgba(184,31,45,0.12)', stroke: '#B81F2D' },
};

function createNodes(count, w, h) {
  const nodes = [];
  for (let i = 0; i < count; i++) {
    const label = GRAPH_LABELS[i % GRAPH_LABELS.length];
    nodes.push({
      id: i,
      label,
      x: Math.random() * w,
      y: Math.random() * h,
      r: 4 + Math.random() * 10,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      pulse: Math.random() * Math.PI * 2,
    });
  }
  return nodes;
}

function createEdges(nodes, density = 0.08) {
  const edges = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      if (Math.random() < density && nodes[i].label !== nodes[j].label) {
        edges.push({ source: i, target: j });
      }
    }
  }
  return edges;
}

function GraphBackground() {
  const canvasRef = useRef(null);
  const stateRef = useRef(null);
  const rafRef = useRef(null);

  const init = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width = w;
    canvas.height = h;
    const nodeCount = Math.max(28, Math.floor((w * h) / 25000));
    const nodes = createNodes(nodeCount, w, h);
    const edges = createEdges(nodes);
    stateRef.current = { nodes, edges, w, h };
  }, []);

  useEffect(() => {
    init();

    const onResize = () => {
      init();
    };
    window.addEventListener('resize', onResize);

    const draw = () => {
      const canvas = canvasRef.current;
      const state = stateRef.current;
      if (!canvas || !state) { rafRef.current = requestAnimationFrame(draw); return; }
      const ctx = canvas.getContext('2d');
      const { nodes, edges, w, h } = state;

      ctx.clearRect(0, 0, w, h);

      // Update positions
      const now = performance.now() / 1000;
      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        // Bounce off walls
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;
        n.x = Math.max(0, Math.min(w, n.x));
        n.y = Math.max(0, Math.min(h, n.y));
      }

      // Draw edges — only when nodes are within connection distance
      const maxDist = 220;
      for (const edge of edges) {
        const a = nodes[edge.source];
        const b = nodes[edge.target];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist > maxDist) continue;
        const alpha = (1 - dist / maxDist) * 0.25;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = `rgba(38, 239, 233, ${alpha})`;
        ctx.lineWidth = 0.8;
        ctx.stroke();

        // Small arrowhead at midpoint
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        const angle = Math.atan2(dy, dx);
        const arrLen = 5;
        ctx.beginPath();
        ctx.moveTo(mx + arrLen * Math.cos(angle), my + arrLen * Math.sin(angle));
        ctx.lineTo(mx + arrLen * Math.cos(angle + 2.5), my + arrLen * Math.sin(angle + 2.5));
        ctx.lineTo(mx + arrLen * Math.cos(angle - 2.5), my + arrLen * Math.sin(angle - 2.5));
        ctx.closePath();
        ctx.fillStyle = `rgba(38, 239, 233, ${alpha * 0.6})`;
        ctx.fill();
      }

      // Draw nodes
      for (const n of nodes) {
        const col = GRAPH_COLORS[n.label];
        const pulseScale = 1 + 0.15 * Math.sin(now * 1.2 + n.pulse);
        const r = n.r * pulseScale;

        // Outer glow
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 3, 0, Math.PI * 2);
        ctx.fillStyle = col.fill;
        ctx.fill();

        // Node circle
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.strokeStyle = col.stroke;
        ctx.lineWidth = 1.2;
        ctx.stroke();
        ctx.fillStyle = col.fill;
        ctx.fill();

        // Inner dot
        ctx.beginPath();
        ctx.arc(n.x, n.y, r * 0.3, 0, Math.PI * 2);
        ctx.fillStyle = col.stroke;
        ctx.globalAlpha = 0.5;
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      window.removeEventListener('resize', onResize);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [init]);

  return <canvas ref={canvasRef} className="login-graph-canvas" />;
}

/* ── Login component ──────────────────────────────────────────────────────── */
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
      <GraphBackground />
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
