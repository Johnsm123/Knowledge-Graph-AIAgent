import { useState, useEffect } from 'react';
import {
  Users, AlertCircle, CheckCircle, TrendingUp, Activity, UserPlus,
  Search, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight,
  SortAsc, SortDesc, Filter, Zap, Loader, Mail, Calendar,
  UserCog, Stethoscope, ClipboardList, RotateCcw,
} from 'lucide-react';
import axios from 'axios';
import AddMember from './AddMember';
import Neo4jGraph from './Neo4jGraph';
import { useRealtimeEvents } from '../hooks/useRealtimeEvents';
import './Dashboard.css';

import { API_BASE } from '../lib/apiBase';
const PAGE_SIZE = 12;

// Demo scope — Critical / Needs Attention / Compliant filters and the
// matching counts only consider open gaps for these three cancer-screening
// measures. To broaden the demo, add measure IDs here.
const DEMO_MEASURE_IDS = new Set(['BCS', 'CCS', 'COL']);

// Per-member demo-scope open-gap count. Prefers `open_gap_measures` (an
// array on the member object); falls back to `m.open_gaps` if the array
// isn't available (older /members responses).
const demoOpenGapCount = (m) => {
  const list = Array.isArray(m?.open_gap_measures) ? m.open_gap_measures : null;
  if (list) return list.filter(x => DEMO_MEASURE_IDS.has(x)).length;
  return m?.open_gaps || 0;
};

// ── Category helpers ──────────────────────────────────────────────────────────
const getCategory = (openGaps) => {
  if (openGaps >= 3) return 'critical';
  if (openGaps >= 1) return 'moderate';
  return 'compliant';
};

const CATEGORY_META = {
  critical:  { label: 'Critical',         color: '#B81F2D', bg: 'rgba(184,31,45,0.08)' },
  moderate:  { label: 'Needs Attention',  color: '#E9C71D', bg: 'rgba(233,199,29,0.12)' },
  compliant: { label: 'Compliant',        color: '#2DB81F', bg: 'rgba(45,184,31,0.10)' },
  all:       { label: 'All Members',      color: '#000048', bg: 'rgba(47,120,196,0.08)' },
};

// ── Gap badge ─────────────────────────────────────────────────────────────────
function GapBadge({ gaps }) {
  if (gaps === 0) return (
    <span className="gap-badge gap-badge--compliant">
      <CheckCircle size={13} /> Compliant
    </span>
  );
  if (gaps <= 2) return (
    <span className="gap-badge gap-badge--moderate">
      <AlertCircle size={13} /> {gaps} Open Gap{gaps > 1 ? 's' : ''}
    </span>
  );
  return (
    <span className="gap-badge gap-badge--critical">
      <AlertCircle size={13} /> {gaps} Open Gaps
    </span>
  );
}

// ── Initials avatar ───────────────────────────────────────────────────────────
function Avatar({ name, category }) {
  const initials = (name || '?').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase();
  return <div className={`member-avatar avatar--${category}`}>{initials}</div>;
}

// ── Pagination component ──────────────────────────────────────────────────────
function Pagination({ page, totalPages, total, pageSize, onPage }) {
  if (totalPages <= 1) return null;

  const start = (page - 1) * pageSize + 1;
  const end   = Math.min(page * pageSize, total);

  // Build page number array with ellipsis
  const pages = [];
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || Math.abs(i - page) <= 1) pages.push(i);
    else if (pages[pages.length - 1] !== '…') pages.push('…');
  }

  return (
    <div className="pagination">
      <span className="pagination-info">
        Showing {start}–{end} of {total} members
      </span>
      <div className="pagination-controls">
        <button className="pg-btn" onClick={() => onPage(1)}         disabled={page === 1}><ChevronsLeft  size={15} /></button>
        <button className="pg-btn" onClick={() => onPage(page - 1)} disabled={page === 1}><ChevronLeft   size={15} /></button>
        {pages.map((p, i) =>
          p === '…' ? (
            <span key={`el-${i}`} className="pg-ellipsis">…</span>
          ) : (
            <button key={p} className={`pg-btn pg-num ${page === p ? 'active' : ''}`} onClick={() => onPage(p)}>
              {p}
            </button>
          )
        )}
        <button className="pg-btn" onClick={() => onPage(page + 1)} disabled={page === totalPages}><ChevronRight  size={15} /></button>
        <button className="pg-btn" onClick={() => onPage(totalPages)} disabled={page === totalPages}><ChevronsRight size={15} /></button>
      </div>
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
function Dashboard({ onMemberSelect }) {
  const [stats,         setStats]         = useState(null);
  const [members,       setMembers]       = useState([]);
  const [loading,       setLoading]       = useState(true);
  const [category,      setCategory]      = useState('critical');
  const [search,        setSearch]        = useState('');
  const [sortBy,        setSortBy]        = useState('gaps_desc');
  const [measureFilter, setMeasureFilter] = useState('all');
  const [page,          setPage]          = useState(1);
  const [showAddMember, setShowAddMember] = useState(false);
  // Auto-process state: { [member_id]: { status, message, step } }
  const [processing, setProcessing]       = useState({});
  // Knowledge Explorer — three pre-built subgraphs from /dashboard/main-graph
  const [explorerTab, setExplorerTab]   = useState('members');   // members | providers | measures
  const [graphs, setGraphs]             = useState({ members_graph: null, providers_graph: null, measures_graph: null });
  const [explorerLoading, setExplorerLoading] = useState(false);
  // Selected node id (string like "M:M0001" / "P:P1001" / "Q:BCS"). null = show all.
  const [selectedNodeId, setSelectedNodeId] = useState(null);

  useEffect(() => { fetchDashboardData(); fetchExplorerData(); }, []);
  useEffect(() => { setPage(1); }, [category, search, sortBy, measureFilter]);

  useRealtimeEvents({
    appointment_booked: () => { fetchDashboardData(); },
    care_gap_updated:   () => { fetchDashboardData(); },
    profile_updated:    () => { fetchDashboardData(); },
  });

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      const [statsRes, membersRes] = await Promise.all([
        axios.get(`${API_BASE}/dashboard/stats`),
        axios.get(`${API_BASE}/members`),
      ]);
      setStats(statsRes.data);
      setMembers(membersRes.data.members || []);
    } catch (err) {
      console.error('Dashboard fetch error:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchExplorerData = async () => {
    try {
      setExplorerLoading(true);
      const res = await axios.get(`${API_BASE}/dashboard/main-graph`);
      setGraphs({
        members_graph:   res.data?.members_graph   || { nodes: [], edges: [] },
        providers_graph: res.data?.providers_graph || { nodes: [], edges: [] },
        measures_graph:  res.data?.measures_graph  || { nodes: [], edges: [] },
      });
    } catch (err) {
      console.error('Explorer graph fetch error:', err);
    } finally {
      setExplorerLoading(false);
    }
  };

  // Pick the active graph for the current tab.
  const activeGraph = (() => {
    const key = explorerTab === 'members' ? 'members_graph'
              : explorerTab === 'providers' ? 'providers_graph'
              : 'measures_graph';
    return graphs[key] || { nodes: [], edges: [] };
  })();

  // The "primary" label per tab (what the user picks to drill into).
  const primaryLabel = explorerTab === 'members'   ? 'Member'
                     : explorerTab === 'providers' ? 'Provider'
                     : 'Measure';

  // Filter the active graph based on the current tab and selection.
  //
  // Default (no selection): show every PRIMARY node (Member / Provider / Measure)
  // plus their direct edges to other primaries — gives a tab-wide overview.
  //
  // After selecting a primary node: show ONLY that node + its 1-hop neighbors
  // (NOT a transitive BFS — that would pull back sibling members through a
  // shared PCP or shared measure, which the user doesn't want).
  //
  // Special case for the MEMBERS tab on selection: also pull in each connected
  // Measure's rule-attribute leaves (AgeRange / Gender / CPT / ICD / Exclusion)
  // from the measures_graph so the user sees "the codes for this member's gaps".
  // Defensive filter — Exclusion and Prereq leaves are intentionally
  // hidden from the Knowledge Explorer regardless of what the backend
  // currently returns. "Prereq" is also rewritten to "Disease" client-side
  // so the legend reads cleanly even before Flask is restarted.
  const HIDDEN_LABELS = new Set(['Exclusion', 'Prereq']);
  const sanitizeNode = (n) => {
    if (!n) return n;
    if (n.label === 'Prereq') return { ...n, label: 'Disease' };
    return n;
  };
  const sanitizeGraph = (g) => {
    if (!g) return { nodes: [], edges: [] };
    const droppedIds = new Set((g.nodes || []).filter(n => HIDDEN_LABELS.has(n.label)).map(n => n.id));
    return {
      nodes: (g.nodes || []).filter(n => !HIDDEN_LABELS.has(n.label)).map(sanitizeNode),
      edges: (g.edges || []).filter(e => !droppedIds.has(e.source) && !droppedIds.has(e.target)),
    };
  };

  const filteredGraph = (() => {
    const cleanActive = sanitizeGraph(activeGraph);
    if (!selectedNodeId) {
      return {
        nodes: cleanActive.nodes.filter(n => n.label === primaryLabel),
        edges: [],
      };
    }
    // 1-hop neighborhood of the selected node
    const visible = new Set([selectedNodeId]);
    for (const e of cleanActive.edges) {
      if (e.source === selectedNodeId) visible.add(e.target);
      if (e.target === selectedNodeId) visible.add(e.source);
    }
    let extraNodes = [];
    let extraEdges = [];
    // Members tab: enrich with measure leaves (CPT, ICD, AgeRange, Disease)
    // pulled from the measures_graph for each measure the member has an OPEN_GAP to.
    // Exclusion / Prereq leaves are stripped by sanitizeGraph().
    if (explorerTab === 'members') {
      const mg = sanitizeGraph(graphs.measures_graph || { nodes: [], edges: [] });
      const measureIdsInScope = [...visible].filter(id => id.startsWith('Q:'));
      const leafIds = new Set();
      for (const e of mg.edges) {
        if (measureIdsInScope.includes(e.source)) {
          leafIds.add(e.target);
          extraEdges.push(e);
        }
      }
      extraNodes = mg.nodes.filter(n => leafIds.has(n.id));
      leafIds.forEach(id => visible.add(id));
    }
    const nodesById = new Map();
    for (const n of cleanActive.nodes) if (visible.has(n.id)) nodesById.set(n.id, n);
    for (const n of extraNodes)        if (!nodesById.has(n.id)) nodesById.set(n.id, n);
    return {
      nodes: [...nodesById.values()],
      edges: [
        ...cleanActive.edges.filter(e => visible.has(e.source) && visible.has(e.target)),
        ...extraEdges,
      ],
    };
  })();

  const resetExplorer = () => setSelectedNodeId(null);
  const switchExplorerTab = (tab) => { setSelectedNodeId(null); setExplorerTab(tab); };

  const handleExplorerNodeClick = (node) => {
    if (!node) return;
    // Only the PRIMARY node type drives the filter.
    // (Clicking a leaf — Age, CPT, Exclusion — does nothing here.)
    if (node.label === primaryLabel) {
      setSelectedNodeId(prev => prev === node.id ? null : node.id);
    }
  };

  // ── Auto-process handler (SSE) ──────────────────────────────────────────
  const handleAutoProcess = (e, memberId) => {
    e.stopPropagation(); // don't navigate to member details

    setProcessing(prev => ({
      ...prev,
      [memberId]: { status: 'running', step: 'detect_gaps', message: 'Starting...' },
    }));

    const es = new EventSource(`${API_BASE}/members/${memberId}/auto-process`);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const step = data.step || '';
        const status = data.status || '';

        if (step === 'error') {
          setProcessing(prev => ({
            ...prev,
            [memberId]: { status: 'error', step: 'error', message: data.message || 'Error' },
          }));
          es.close();
          return;
        }

        if (step === 'complete') {
          const doneMsg = data.email_sent
            ? 'Email Sent'
            : (data.status === 'compliant' ? 'Compliant' : 'Done');
          setProcessing(prev => ({
            ...prev,
            [memberId]: {
              status: 'done',
              step: 'complete',
              message: doneMsg,
              gapsCount: data.gaps_count || 0,
              emailSent: data.email_sent || false,
            },
          }));
          es.close();
          // Refresh dashboard data after a short delay
          setTimeout(() => fetchDashboardData(), 1500);
          return;
        }

        // Progress updates
        let msg = data.message || '';
        if (step === 'detect_gaps' && status === 'running') msg = 'Detecting gaps...';
        else if (step === 'detect_gaps' && status === 'done') msg = 'Gaps detected';
        else if (step === 'agent_analysis' && status === 'running') msg = `Agent: ${data.agent || '...'}`;
        else if (step === 'agent_analysis' && status === 'done' && data.agent) msg = `Agent done: ${data.agent}`;
        else if (step === 'agent_analysis' && status === 'done') msg = 'Analysis complete';
        else if (step === 'email' && status === 'running') msg = 'Sending email...';
        else if (step === 'email' && status === 'done') msg = 'Email sent!';
        else if (step === 'email' && status === 'error') msg = data.message || 'Email failed';
        else if (step === 'email' && status === 'skipped') msg = 'No email on file';

        setProcessing(prev => ({
          ...prev,
          [memberId]: { status: 'running', step, message: msg },
        }));
      } catch (err) {
        console.error('Auto-process SSE parse error:', err);
      }
    };

    es.onerror = () => {
      setProcessing(prev => ({
        ...prev,
        [memberId]: prev[memberId]?.status === 'done'
          ? prev[memberId]
          : { status: 'error', step: 'error', message: 'Connection lost' },
      }));
      es.close();
    };
  };

  // ── Set default email for members without one ─────────────────────────────
  const handleSetDefaultEmails = async () => {
    try {
      const res = await axios.post(`${API_BASE}/members/set-default-email`);
      if (res.data.status === 'success') {
        alert(`Updated ${res.data.updated_count} members with default email.`);
        fetchDashboardData();
      }
    } catch (err) {
      console.error('Set default email error:', err);
    }
  };

  // ── Filtering + sorting ───────────────────────────────────────────────────
  const filtered = members
    .filter(m => {
      const n = demoOpenGapCount(m);
      if (category === 'critical')  return n >= 3;
      if (category === 'moderate')  return n >= 1 && n < 3;
      if (category === 'compliant') return n === 0;
      return true;
    })
    .filter(m => {
      if (!search) return true;
      const q = search.toLowerCase();
      return (
        (m.name       || '').toLowerCase().includes(q) ||
        (m.member_id  || '').toLowerCase().includes(q) ||
        (m.pcp_name   || '').toLowerCase().includes(q)
      );
    })
    .filter(m => {
      if (measureFilter === 'all') return true;
      // Source-of-truth: derive membership from the Knowledge-Explorer graph
      // we already loaded (`graphs.members_graph.edges`). Every open gap is an
      // OPEN_GAP edge from M:<member_id> → Q:<measure_id>. This works even when
      // the /members endpoint was not redeployed with `open_gap_measures`.
      // Fallback: if the explorer graph hasn't loaded yet, fall back to the
      // stats roster. A member with multiple open measures matches whichever
      // measure is currently selected.
      const fromGraph = (graphs?.members_graph?.edges || [])
        .filter(e => e.type === 'OPEN_GAP' && e.source === `M:${m.member_id}`)
        .some(e => e.target === `Q:${measureFilter}`);
      if (fromGraph) return true;
      const measureRow = (stats?.gaps_by_measure || []).find(r => r.measure_id === measureFilter);
      const memberIds  = measureRow?.member_ids || [];
      if (memberIds.includes(m.member_id)) return true;
      const list = m.open_gap_measures;
      return Array.isArray(list) && list.includes(measureFilter);
    })
    .sort((a, b) => {
      if (sortBy === 'gaps_desc')  return b.open_gaps - a.open_gaps;
      if (sortBy === 'gaps_asc')   return a.open_gaps - b.open_gaps;
      if (sortBy === 'name_asc')   return (a.name || '').localeCompare(b.name || '');
      if (sortBy === 'name_desc')  return (b.name || '').localeCompare(a.name || '');
      return 0;
    });

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const counts = {
    all:       members.length,
    critical:  members.filter(m => demoOpenGapCount(m) >= 3).length,
    moderate:  members.filter(m => { const n = demoOpenGapCount(m); return n >= 1 && n < 3; }).length,
    compliant: members.filter(m => demoOpenGapCount(m) === 0).length,
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <p>Loading dashboard…</p>
      </div>
    );
  }

  return (
    <div className="dashboard">

      {/* ── Stats ── */}
      <div className="stats-grid">
        <div className="stat-card total">
          <div className="stat-icon"><Users size={30} /></div>
          <div className="stat-content">
            <h3>Total Members</h3>
            <p className="stat-value">{stats?.total_members || 0}</p>
          </div>
        </div>
        <div className="stat-card gaps">
          <div className="stat-icon"><AlertCircle size={30} /></div>
          <div className="stat-content">
            <h3>Members with Gaps</h3>
            <p className="stat-value">{stats?.members_with_gaps || 0}</p>
            <p className="stat-subtitle">{stats?.total_open_gaps || 0} total open gaps</p>
          </div>
        </div>
        <div className="stat-card compliant">
          <div className="stat-icon"><CheckCircle size={30} /></div>
          <div className="stat-content">
            <h3>Compliant Members</h3>
            <p className="stat-value">{stats?.compliant_members || 0}</p>
            <p className="stat-subtitle">No open care gaps</p>
          </div>
        </div>
        <div className="stat-card outreach">
          <div className="stat-icon"><Activity size={30} /></div>
          <div className="stat-content">
            <h3>Outreach Activity</h3>
            <p className="stat-value">{stats?.outreach_stats?.total_outreach || 0}</p>
            <p className="stat-subtitle">{stats?.outreach_stats?.completed || 0} completed</p>
          </div>
        </div>
      </div>

      {/* Knowledge Explorer removed — graph filter data is still fetched in
          state (graphs.members_graph) because the measure-filter chip on
          the Members panel uses its OPEN_GAP edges. */}
      {false && (
        <div className="explorer-section" style={{ display: 'none' }}>
        <div className="section-header">
          <h2><Activity size={20} className="graph-icon" /> Knowledge Explorer</h2>
          {selectedNodeId && (
            <button className="explorer-reset-btn" onClick={resetExplorer} title="Show all items in this filter">
              <RotateCcw size={14} /> Reset filter
            </button>
          )}
        </div>
        <p className="section-subtitle">
          Pick a filter tab below. Click any node in the graph to isolate that record and its connected parameters; click <strong>Reset filter</strong> to bring everything back.
        </p>

        {/* Filter tab pills */}
        <div className="explorer-tabs">
          <button
            className={`explorer-tab ${explorerTab === 'members' ? 'active' : ''}`}
            onClick={() => switchExplorerTab('members')}
          >
            <Users size={14} /> Members
            <span className="tab-count">({(graphs.members_graph?.nodes || []).filter(n => n.label === 'Member').length})</span>
          </button>
          <button
            className={`explorer-tab ${explorerTab === 'providers' ? 'active' : ''}`}
            onClick={() => switchExplorerTab('providers')}
          >
            <Stethoscope size={14} /> Providers
            <span className="tab-count">({(graphs.providers_graph?.nodes || []).filter(n => n.label === 'Provider').length})</span>
          </button>
        </div>

        {explorerLoading ? (
          <div className="graph-loading"><Loader size={18} className="spinning" /> Loading…</div>
        ) : filteredGraph.nodes.length === 0 ? (
          <div className="graph-loading">No data yet for this filter.</div>
        ) : (
          <Neo4jGraph
            nodes={filteredGraph.nodes}
            edges={filteredGraph.edges}
            width={1100}
            height={560}
            onNodeClick={handleExplorerNodeClick}
          />
        )}

        {selectedNodeId && (
          <p className="explorer-hint">
            Showing <strong>{filteredGraph.nodes.length}</strong> connected node{filteredGraph.nodes.length === 1 ? '' : 's'}.
            Click <strong>Reset filter</strong> above to see every {primaryLabel.toLowerCase()} again.
          </p>
        )}
        </div>
      )}

      {/* ── Members panel ── */}
      <div className="members-panel">

        {/* Header row */}
        <div className="members-header-row">
          <h2 className="members-title">Members</h2>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="set-email-btn" onClick={handleSetDefaultEmails} title="Add default test email to members without one">
              <Mail size={15} /> Set Default Emails
            </button>
            <button
              className="add-member-btn"
              onClick={() => window.open('http://localhost:5001/api/v1/members/bulk-upload-page', '_blank', 'noopener')}
            >
              <UserPlus size={17} /> Upload Patient Record
            </button>
          </div>
        </div>

        {/* Search + Sort */}
        <div className="members-toolbar">
          <div className="search-bar">
            <Search size={15} className="search-icon" />
            <input
              type="text"
              placeholder="Search name, ID, or PCP…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            {search && (
              <button className="search-clear" onClick={() => setSearch('')}>×</button>
            )}
          </div>
          <div className="sort-bar">
            <Filter size={14} />
            <select value={sortBy} onChange={e => setSortBy(e.target.value)}>
              <option value="gaps_desc">Most Gaps First</option>
              <option value="gaps_asc">Fewest Gaps First</option>
              <option value="name_asc">Name A–Z</option>
              <option value="name_desc">Name Z–A</option>
            </select>
          </div>
          <div className="sort-bar">
            <Filter size={14} />
            <select value={measureFilter} onChange={e => setMeasureFilter(e.target.value)} title="Filter members by measure">
              <option value="all">All Measures</option>
              {(stats?.gaps_by_measure || []).map(m => (
                <option key={m.measure_id} value={m.measure_id}>
                  {m.measure_id} — {m.measure_name} ({m.gap_count})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Category tabs */}
        <div className="category-tabs">
          {Object.entries(CATEGORY_META).map(([key, meta]) => (
            <button
              key={key}
              className={`cat-tab cat-tab--${key} ${category === key ? 'active' : ''}`}
              onClick={() => setCategory(key)}
            >
              <span className="cat-label">{meta.label}</span>
              <span className="cat-count">{counts[key]}</span>
            </button>
          ))}
        </div>

        {/* Member grid */}
        {paginated.length > 0 ? (
          <>
            <div className="members-grid">
              {paginated.map(member => {
                const cat = getCategory(demoOpenGapCount(member));
                return (
                  <div
                    key={member.member_id}
                    className={`member-tile member-tile--${cat}`}
                  >
                    <div className="tile-header">
                      <Avatar name={member.name} category={cat} />
                      <div className="tile-identity">
                        <h3 className="tile-name">{member.name}</h3>
                        <span className="tile-id">{member.member_id}</span>
                      </div>
                      <GapBadge gaps={member.open_gaps} />
                    </div>

                    <div className="tile-meta">
                      <div className="tile-row">
                        <span>Age</span>
                        <span>{member.age || '—'}</span>
                      </div>
                      <div className="tile-row">
                        <span>Gender</span>
                        <span>{member.gender || '—'}</span>
                      </div>
                      <div className="tile-row">
                        <span>PCP</span>
                        <span className="tile-pcp">{member.pcp_name || 'Unassigned'}</span>
                      </div>
                      {member.closed_gaps > 0 && (
                        <div className="tile-row">
                          <span>Closed</span>
                          <span className="tile-closed">
                            <TrendingUp size={12} /> {member.closed_gaps} gap{member.closed_gaps > 1 ? 's' : ''}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Outreach / Appointment / Closed badge — mutually
                        exclusive precedence so the tile shows the FURTHEST
                        stage of the journey only:
                          • all open gaps closed     → "Care Gaps Closed"
                          • appointment booked       → "Appt Booked"
                          • outreach sent (no appt)  → "Outreach Done" */}
                    {(() => {
                      const hadGaps = (member.open_gaps || 0) + (member.closed_gaps || 0) > 0;
                      const allClosed = hadGaps && (member.open_gaps || 0) === 0;
                      const hasAppt   = (member.appointment_count || 0) > 0;
                      const hasOutreach = (member.outreach_count || 0) > 0;
                      if (allClosed) {
                        return (
                          <div className="tile-badges">
                            <span className="closed-badge" title="All care gaps closed">
                              <CheckCircle size={12} /> Care Gaps Closed
                            </span>
                          </div>
                        );
                      }
                      if (hasAppt) {
                        return (
                          <div className="tile-badges">
                            <span className="appointment-badge" title="Has scheduled appointments">
                              <Calendar size={12} /> Appt Booked
                            </span>
                          </div>
                        );
                      }
                      if (hasOutreach) {
                        return (
                          <div className="tile-badges">
                            <span className="outreach-badge" title={member.last_outreach_date ? `Last outreach: ${member.last_outreach_date}` : 'Outreach sent'}>
                              <Mail size={12} /> Outreach Done
                            </span>
                          </div>
                        );
                      }
                      return null;
                    })()}

                    <div className="tile-footer">
                      <span className="tile-view-details" onClick={() => onMemberSelect(member)}>
                        View Details →
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            <Pagination
              page={page}
              totalPages={totalPages}
              total={filtered.length}
              pageSize={PAGE_SIZE}
              onPage={setPage}
            />
          </>
        ) : (
          <div className="no-results">
            {search
              ? <><p>No members match <strong>"{search}"</strong></p><button onClick={() => setSearch('')}>Clear search</button></>
              : <p>No members in this category.</p>
            }
          </div>
        )}
      </div>

      {showAddMember && (
        <AddMember
          onClose={() => setShowAddMember(false)}
          onSuccess={() => fetchDashboardData()}
        />
      )}
    </div>
  );
}

export default Dashboard;
