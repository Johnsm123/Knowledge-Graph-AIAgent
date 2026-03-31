import { useState, useEffect } from 'react';
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { TrendingUp, Users, Activity, Target, Download } from 'lucide-react';
import axios from 'axios';
import './Analytics.css';

const API_BASE = 'http://localhost:5001/api/v1';

const COLORS = {
  primary: '#0033A1',
  secondary: '#005EB8',
  success: '#10b981',
  danger: '#ef4444',
  warning: '#f59e0b',
  info: '#3b82f6',
  purple: '#8b5cf6',
  pink: '#ec4899'
};

function Analytics() {
  const [stats, setStats] = useState(null);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAnalyticsData();
  }, []);

  const fetchAnalyticsData = async () => {
    try {
      setLoading(true);
      const [statsRes, membersRes] = await Promise.all([
        axios.get(`${API_BASE}/dashboard/stats`),
        axios.get(`${API_BASE}/members`)
      ]);
      setStats(statsRes.data);
      setMembers(membersRes.data.members);
    } catch (error) {
      console.error('Error fetching analytics data:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading analytics...</p>
      </div>
    );
  }

  // Prepare data for charts
  const gapDistributionData = stats?.gaps_by_measure?.map(measure => ({
    name: measure.measure_id,
    value: measure.gap_count,
    fullName: measure.measure_name
  })) || [];

  const complianceData = [
    { name: 'Compliant', value: stats?.compliant_members || 0, color: COLORS.success },
    { name: 'With Gaps', value: stats?.members_with_gaps || 0, color: COLORS.danger }
  ];

  const ageDistribution = members.reduce((acc, member) => {
    const age = parseInt(member.age?.split(' ')[0]) || 0;
    let group;
    if (age < 30) group = '18-29';
    else if (age < 45) group = '30-44';
    else if (age < 60) group = '45-59';
    else if (age < 75) group = '60-74';
    else group = '75+';
    
    acc[group] = (acc[group] || 0) + 1;
    return acc;
  }, {});

  const ageDistributionData = Object.entries(ageDistribution).map(([name, value]) => ({
    name,
    value
  }));

  const genderDistribution = members.reduce((acc, member) => {
    acc[member.gender] = (acc[member.gender] || 0) + 1;
    return acc;
  }, {});

  const genderDistributionData = Object.entries(genderDistribution).map(([name, value]) => ({
    name: name === 'M' ? 'Male' : 'Female',
    value
  }));

  const gapStatusData = [
    { name: 'Open Gaps', value: stats?.total_open_gaps || 0 },
    { name: 'Closed Gaps', value: members.reduce((sum, m) => sum + (m.closed_gaps || 0), 0) }
  ];

  const outreachData = [
    { name: 'Total', value: stats?.outreach_stats?.total_outreach || 0 },
    { name: 'Completed', value: stats?.outreach_stats?.completed || 0 },
    { name: 'Scheduled', value: stats?.outreach_stats?.scheduled || 0 }
  ];

  const topMembersWithGaps = members
    .filter(m => m.open_gaps > 0)
    .sort((a, b) => b.open_gaps - a.open_gaps)
    .slice(0, 10);

  return (
    <div className="analytics-container">
      <div className="analytics-header">
        <div>
          <h1>Analytics Dashboard</h1>
          <p>Comprehensive care gap analytics and insights</p>
        </div>
        <button className="export-btn">
          <Download size={18} />
          Export Report
        </button>
      </div>

      {/* Key Metrics */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-icon" style={{ background: '#dbeafe' }}>
            <Users size={24} color={COLORS.info} />
          </div>
          <div className="metric-content">
            <p className="metric-label">Total Members</p>
            <h2 className="metric-value">{stats?.total_members || 0}</h2>
            <p className="metric-change positive">Active enrollment</p>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon" style={{ background: '#fee2e2' }}>
            <Target size={24} color={COLORS.danger} />
          </div>
          <div className="metric-content">
            <p className="metric-label">Open Care Gaps</p>
            <h2 className="metric-value">{stats?.total_open_gaps || 0}</h2>
            <p className="metric-change negative">Requires attention</p>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon" style={{ background: '#d1fae5' }}>
            <TrendingUp size={24} color={COLORS.success} />
          </div>
          <div className="metric-content">
            <p className="metric-label">Compliance Rate</p>
            <h2 className="metric-value">
              {stats?.total_members ? Math.round((stats.compliant_members / stats.total_members) * 100) : 0}%
            </h2>
            <p className="metric-change positive">
              {stats?.compliant_members || 0} compliant members
            </p>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon" style={{ background: '#e0e7ff' }}>
            <Activity size={24} color={COLORS.purple} />
          </div>
          <div className="metric-content">
            <p className="metric-label">Outreach Success</p>
            <h2 className="metric-value">
              {stats?.outreach_stats?.total_outreach 
                ? Math.round((stats.outreach_stats.completed / stats.outreach_stats.total_outreach) * 100) 
                : 0}%
            </h2>
            <p className="metric-change positive">
              {stats?.outreach_stats?.completed || 0} completed
            </p>
          </div>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="charts-grid">
        {/* Gap Distribution by Measure */}
        <div className="chart-card large">
          <div className="chart-header">
            <h3>Care Gap Distribution by Measure</h3>
            <p>Total open gaps across HEDIS measures</p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={gapDistributionData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip 
                contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: '8px' }}
                formatter={(value, name, props) => [value, props.payload.fullName]}
              />
              <Bar dataKey="value" fill={COLORS.primary} radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Member Compliance */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>Member Compliance Status</h3>
            <p>Compliant vs Non-Compliant</p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={complianceData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                {complianceData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Age Distribution */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>Age Distribution</h3>
            <p>Members by age group</p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={ageDistributionData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: '8px' }} />
              <Bar dataKey="value" fill={COLORS.secondary} radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Gender Distribution */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>Gender Distribution</h3>
            <p>Member demographics</p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={genderDistributionData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                {genderDistributionData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={index === 0 ? COLORS.info : COLORS.pink} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Gap Status */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>Gap Status Overview</h3>
            <p>Open vs Closed gaps</p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={gapStatusData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis type="number" stroke="#64748b" />
              <YAxis dataKey="name" type="category" stroke="#64748b" />
              <Tooltip contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: '8px' }} />
              <Bar dataKey="value" fill={COLORS.warning} radius={[0, 8, 8, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Outreach Performance */}
        <div className="chart-card">
          <div className="chart-header">
            <h3>Outreach Performance</h3>
            <p>Activity and completion rates</p>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={outreachData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: '8px' }} />
              <Bar dataKey="value" fill={COLORS.purple} radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Members with Gaps */}
      <div className="table-card">
        <div className="chart-header">
          <h3>Top 10 Members with Open Gaps</h3>
          <p>Members requiring immediate attention</p>
        </div>
        <div className="table-container">
          <table className="analytics-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Member ID</th>
                <th>Name</th>
                <th>Age</th>
                <th>Gender</th>
                <th>Open Gaps</th>
                <th>PCP</th>
              </tr>
            </thead>
            <tbody>
              {topMembersWithGaps.map((member, index) => (
                <tr key={member.member_id}>
                  <td>
                    <span className={`rank-badge ${index < 3 ? 'top' : ''}`}>
                      #{index + 1}
                    </span>
                  </td>
                  <td><code>{member.member_id}</code></td>
                  <td><strong>{member.name}</strong></td>
                  <td>{member.age}</td>
                  <td>{member.gender === 'M' ? 'Male' : 'Female'}</td>
                  <td>
                    <span className="gap-count-badge">{member.open_gaps}</span>
                  </td>
                  <td>{member.pcp_name || 'Not assigned'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default Analytics;
