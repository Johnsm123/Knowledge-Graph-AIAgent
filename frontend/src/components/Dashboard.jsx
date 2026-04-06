import { useState, useEffect } from 'react';
import {
  Users, AlertCircle, CheckCircle, TrendingUp, Activity, UserPlus,
  Search, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight,
  SortAsc, SortDesc, Filter, Zap, Loader, Mail,
} from 'lucide-react';
import axios from 'axios';
import AddMember from './AddMember';
import './Dashboard.css';

const API_BASE = 'http://localhost:5001/api/v1';
const PAGE_SIZE = 12;

// ── Category helpers ──────────────────────────────────────────────────────────
const getCategory = (openGaps) => {
  if (openGaps >= 3) return 'critical';
  if (openGaps >= 1) return 'moderate';
  return 'compliant';
};

const CATEGORY_META = {
  all:       { label: 'All Members',      color: '#0033A1', bg: '#e8eeff' },
  critical:  { label: 'Critical',         color: '#dc2626', bg: '#fee2e2' },
  moderate:  { label: 'Needs Attention',  color: '#d97706', bg: '#fef3c7' },
  compliant: { label: 'Compliant',        color: '#059669', bg: '#d1fae5' },
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
  const [category,      setCategory]      = useState('all');
  const [search,        setSearch]        = useState('');
  const [sortBy,        setSortBy]        = useState('gaps_desc');
  const [page,          setPage]          = useState(1);
  const [showAddMember, setShowAddMember] = useState(false);
  // Auto-process state: { [member_id]: { status, message, step } }
  const [processing, setProcessing]       = useState({});

  useEffect(() => { fetchDashboardData(); }, []);
  useEffect(() => { setPage(1); }, [category, search, sortBy]);

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
          setProcessing(prev => ({
            ...prev,
            [memberId]: {
              status: 'done',
              step: 'complete',
              message: data.email_sent ? 'Email Sent' : (data.status === 'compliant' ? 'Compliant' : 'Done'),
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
      if (category === 'critical')  return m.open_gaps >= 3;
      if (category === 'moderate')  return m.open_gaps >= 1 && m.open_gaps < 3;
      if (category === 'compliant') return m.open_gaps === 0;
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
    critical:  members.filter(m => m.open_gaps >= 3).length,
    moderate:  members.filter(m => m.open_gaps >= 1 && m.open_gaps < 3).length,
    compliant: members.filter(m => m.open_gaps === 0).length,
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

      {/* ── Gaps by measure ── */}
      {stats?.gaps_by_measure?.length > 0 && (
        <div className="gaps-by-measure">
          <h2>Open Gaps by Measure</h2>
          <div className="measure-chips-track">
            {stats.gaps_by_measure.map(m => {
              const pct = Math.round((m.gap_count / (stats?.members_with_gaps || 1)) * 100);
              return (
                <div key={m.measure_id} className="measure-chip">
                  <div className="chip-top">
                    <span className="chip-id">{m.measure_id}</span>
                    <span className="chip-count">{m.gap_count}</span>
                  </div>
                  <div className="chip-bar">
                    <div className="chip-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="chip-label">{m.measure_name}</span>
                </div>
              );
            })}
          </div>
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
            <button className="add-member-btn" onClick={() => setShowAddMember(true)}>
              <UserPlus size={17} /> Add Member
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
                const cat = getCategory(member.open_gaps);
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

                    <div className="tile-footer">
                      {/* Auto-process status or button */}
                      {processing[member.member_id]?.status === 'running' ? (
                        <button className="btn-auto-process running" disabled>
                          <Loader size={14} className="spinning" />
                          {processing[member.member_id].message}
                        </button>
                      ) : processing[member.member_id]?.status === 'done' ? (
                        <span className="auto-process-done">
                          <CheckCircle size={14} />
                          {processing[member.member_id].message}
                          {processing[member.member_id].emailSent && ' ✉'}
                        </span>
                      ) : processing[member.member_id]?.status === 'error' ? (
                        <button className="btn-auto-process error" onClick={(e) => handleAutoProcess(e, member.member_id)}>
                          <Zap size={14} />
                          Retry
                        </button>
                      ) : member.open_gaps > 0 ? (
                        <button className="btn-auto-process" onClick={(e) => handleAutoProcess(e, member.member_id)}>
                          <Zap size={14} />
                          Auto Process
                        </button>
                      ) : null}
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
