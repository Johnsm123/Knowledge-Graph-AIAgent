import { useState, useEffect } from 'react';
import { BarChart, Bar, LineChart, Line, ComposedChart, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import axios from 'axios';
import './Analytics.css';
import { useRealtimeEvents } from '../hooks/useRealtimeEvents';

import { API_BASE } from '../lib/apiBase';

const COLORS = {
  primary: '#000048',
  secondary: '#2F78C4',
  success: '#2DB81F',
  danger: '#B81F2D',
  warning: '#E9C71D',
  info: '#05819B',
  purple: '#7373D8',
  pink: '#85A0F9'
};

function Analytics() {
  const [stats, setStats] = useState(null);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAnalyticsData();
  }, []);

  useRealtimeEvents({
    appointment_booked: () => fetchAnalyticsData(),
    care_gap_updated:   () => fetchAnalyticsData(),
    profile_updated:    () => fetchAnalyticsData(),
  });

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

  // Prepare data for charts.
  // Demo scope: BCS / CCS / COL cancer screenings + AAP (adults' access to
  // preventive/ambulatory health services). Mirrors CARE_GAP_ENABLED_MEASURES
  // on the backend.
  const DEMO_MEASURE_IDS = new Set(['BCS', 'CCS', 'COL', 'AAP']);
  const gapDistributionData = (stats?.gaps_by_measure || [])
    .filter(measure => DEMO_MEASURE_IDS.has(measure.measure_id))
    .map(measure => {
      const earliest = measure.earliest_created || measure.latest_created || null;
      let daysOpen = null;
      if (earliest) {
        const ms = Date.now() - new Date(earliest).getTime();
        if (!Number.isNaN(ms)) daysOpen = Math.max(0, Math.round(ms / (1000 * 60 * 60 * 24)));
      }
      return {
        name: measure.measure_id,
        value: measure.gap_count,
        fullName: measure.measure_name,
        earliest_created: earliest,
        latest_created: measure.latest_created || null,
        days_open: daysOpen,
      };
    });

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
      </div>

      {/* Charts Grid */}
      <div className="charts-grid">
        {/* Gap Distribution by Measure */}
        <div className="chart-card large">
          <div className="chart-header">
            <h3>Care Gap Distribution by Measure</h3>
            <p>Total open gaps and how long ago each measure was first opened</p>
          </div>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={gapDistributionData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="name" stroke="#64748b" />
              <YAxis yAxisId="left" stroke="#64748b" label={{ value: 'Open Gaps', angle: -90, position: 'insideLeft', fill: '#64748b' }} />
              <YAxis yAxisId="right" orientation="right" stroke={COLORS.warning} label={{ value: 'Days Since First Opened', angle: 90, position: 'insideRight', fill: COLORS.warning }} />
              <Tooltip
                contentStyle={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: '8px' }}
                formatter={(value, name, props) => {
                  if (name === 'Open Gaps') return [value, props.payload.fullName];
                  if (name === 'Days Since First Opened') {
                    const d = props.payload.earliest_created;
                    return [`${value} days${d ? ` (since ${String(d).slice(0, 10)})` : ''}`, name];
                  }
                  return [value, name];
                }}
              />
              <Legend />
              <Bar yAxisId="left" dataKey="value" name="Open Gaps" fill={COLORS.primary} radius={[8, 8, 0, 0]} />
              <Line yAxisId="right" type="monotone" dataKey="days_open" name="Days Since First Opened" stroke={COLORS.warning} strokeWidth={2} dot={{ r: 4, fill: COLORS.warning }} />
            </ComposedChart>
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
