import { useState, useEffect } from 'react';
import { Users, AlertCircle, CheckCircle, TrendingUp, Activity } from 'lucide-react';
import axios from 'axios';
import './Dashboard.css';

const API_BASE = 'http://localhost:5001/api/v1';

function Dashboard({ onMemberSelect }) {
  const [stats, setStats] = useState(null);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      const [statsRes, membersRes] = await Promise.all([
        axios.get(`${API_BASE}/dashboard/stats`),
        axios.get(`${API_BASE}/members`)
      ]);
      setStats(statsRes.data);
      setMembers(membersRes.data.members);
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredMembers = members.filter(member => {
    if (filter === 'gaps') return member.open_gaps > 0;
    if (filter === 'compliant') return member.open_gaps === 0;
    return true;
  });

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading dashboard...</p>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <div className="stats-grid">
        <div className="stat-card total">
          <div className="stat-icon">
            <Users size={32} />
          </div>
          <div className="stat-content">
            <h3>Total Members</h3>
            <p className="stat-value">{stats?.total_members || 0}</p>
          </div>
        </div>

        <div className="stat-card gaps">
          <div className="stat-icon">
            <AlertCircle size={32} />
          </div>
          <div className="stat-content">
            <h3>Members with Gaps</h3>
            <p className="stat-value">{stats?.members_with_gaps || 0}</p>
            <p className="stat-subtitle">{stats?.total_open_gaps || 0} total open gaps</p>
          </div>
        </div>

        <div className="stat-card compliant">
          <div className="stat-icon">
            <CheckCircle size={32} />
          </div>
          <div className="stat-content">
            <h3>Compliant Members</h3>
            <p className="stat-value">{stats?.compliant_members || 0}</p>
            <p className="stat-subtitle">No open care gaps</p>
          </div>
        </div>

        <div className="stat-card outreach">
          <div className="stat-icon">
            <Activity size={32} />
          </div>
          <div className="stat-content">
            <h3>Outreach Activity</h3>
            <p className="stat-value">{stats?.outreach_stats?.total_outreach || 0}</p>
            <p className="stat-subtitle">
              {stats?.outreach_stats?.completed || 0} completed
            </p>
          </div>
        </div>
      </div>

      {stats?.gaps_by_measure && stats.gaps_by_measure.length > 0 && (
        <div className="gaps-by-measure">
          <h2>Open Gaps by Measure</h2>
          <div className="measure-bars">
            {stats.gaps_by_measure.map(measure => (
              <div key={measure.measure_id} className="measure-bar">
                <div className="measure-info">
                  <span className="measure-name">{measure.measure_id}</span>
                  <span className="measure-count">{measure.gap_count} gaps</span>
                </div>
                <div className="measure-progress">
                  <div 
                    className="measure-fill"
                    style={{ 
                      width: `${(measure.gap_count / stats.total_open_gaps) * 100}%` 
                    }}
                  ></div>
                </div>
                <p className="measure-description">{measure.measure_name}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="filter-section">
        <h2>Members</h2>
        <div className="filter-buttons">
          <button 
            className={filter === 'all' ? 'active' : ''}
            onClick={() => setFilter('all')}
          >
            All Members ({members.length})
          </button>
          <button 
            className={filter === 'gaps' ? 'active' : ''}
            onClick={() => setFilter('gaps')}
          >
            With Gaps ({members.filter(m => m.open_gaps > 0).length})
          </button>
          <button 
            className={filter === 'compliant' ? 'active' : ''}
            onClick={() => setFilter('compliant')}
          >
            Compliant ({members.filter(m => m.open_gaps === 0).length})
          </button>
        </div>
      </div>

      <div className="members-grid">
        {filteredMembers.map(member => (
          <div 
            key={member.member_id}
            className={`member-tile ${member.open_gaps > 0 ? 'has-gaps' : 'compliant'}`}
            onClick={() => onMemberSelect(member)}
          >
            <div className="member-header">
              <div className="member-avatar">
                {member.name.split(' ').map(n => n[0]).join('')}
              </div>
              <div className="member-info">
                <h3>{member.name}</h3>
                <p className="member-id">{member.member_id}</p>
              </div>
            </div>

            <div className="member-details">
              <div className="detail-row">
                <span className="label">Age:</span>
                <span className="value">{member.age}</span>
              </div>
              <div className="detail-row">
                <span className="label">Gender:</span>
                <span className="value">{member.gender}</span>
              </div>
              <div className="detail-row">
                <span className="label">PCP:</span>
                <span className="value">{member.pcp_name || 'Not assigned'}</span>
              </div>
            </div>

            <div className="member-status">
              {member.open_gaps > 0 ? (
                <div className="status-badge gaps">
                  <AlertCircle size={16} />
                  <span>{member.open_gaps} Open Gap{member.open_gaps > 1 ? 's' : ''}</span>
                </div>
              ) : (
                <div className="status-badge compliant">
                  <CheckCircle size={16} />
                  <span>Compliant</span>
                </div>
              )}
              {member.closed_gaps > 0 && (
                <div className="status-badge closed">
                  <TrendingUp size={16} />
                  <span>{member.closed_gaps} Closed</span>
                </div>
              )}
            </div>

            <button className="view-details-btn">
              View Details →
            </button>
          </div>
        ))}
      </div>

      {filteredMembers.length === 0 && (
        <div className="no-results">
          <p>No members found matching the selected filter.</p>
        </div>
      )}
    </div>
  );
}

export default Dashboard;
