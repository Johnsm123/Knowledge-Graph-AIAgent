import { useState, useEffect } from 'react';
import { X, TrendingUp, TrendingDown, Users, Target, CheckCircle, AlertCircle, Award, Lightbulb } from 'lucide-react';
import axios from 'axios';
import './MemberComparison.css';

const API_BASE = 'http://localhost:5001/api/v1';

function MemberComparison({ member, onClose }) {
  const [comparisonData, setComparisonData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchComparisonData();
  }, [member]);

  const fetchComparisonData = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_BASE}/members/${member.member_id}/compare`);
      setComparisonData(response.data);
    } catch (error) {
      console.error('Error fetching comparison data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getPerformanceColor = (percentile) => {
    if (percentile >= 75) return 'excellent';
    if (percentile >= 50) return 'good';
    if (percentile >= 25) return 'fair';
    return 'poor';
  };

  const getPerformanceLabel = (percentile) => {
    if (percentile >= 90) return 'Excellent - Top 10%';
    if (percentile >= 75) return 'Top Performer';
    if (percentile >= 50) return 'Above Average';
    if (percentile >= 25) return 'Below Average';
    return 'Needs Improvement';
  };

  if (loading) {
    return (
      <div className="comparison-modal">
        <div className="comparison-content loading">
          <div className="spinner"></div>
          <p>Analyzing member data...</p>
        </div>
      </div>
    );
  }

  const metrics = comparisonData?.comparison_metrics;
  const current = comparisonData?.current_member;

  return (
    <div className="comparison-modal">
      <div className="comparison-content">
        <div className="comparison-header">
          <div className="header-left">
            <h2>Member Comparison Analysis</h2>
            <p className="header-subtitle">
              Comparing {current?.name} with {metrics?.total_similar_members} similar members
            </p>
          </div>
          <button className="close-btn" onClick={onClose}>
            <X size={24} />
          </button>
        </div>

        <div className="comparison-body">
          {/* Performance Overview */}
          <div className="performance-overview">
            <div className="overview-card current-member">
              <div className="card-header">
                <Users size={24} />
                <h3>Current Member</h3>
              </div>
              <div className="member-stats">
                <div className="stat-item">
                  <span className="stat-label">Open Gaps</span>
                  <span className="stat-value red">{metrics?.current_open_gaps}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Closed Gaps</span>
                  <span className="stat-value green">{metrics?.current_closed_gaps}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Performance Rank</span>
                  <span className={`stat-value ${getPerformanceColor(metrics?.percentile_rank)}`}>
                    {getPerformanceLabel(metrics?.percentile_rank)}
                  </span>
                </div>
              </div>
              <div className="percentile-bar">
                <div className="percentile-label">Percentile Rank</div>
                <div className="percentile-track">
                  <div 
                    className={`percentile-fill ${getPerformanceColor(metrics?.percentile_rank)}`}
                    style={{ width: `${metrics?.percentile_rank}%` }}
                  >
                    <span className="percentile-value">{metrics?.percentile_rank}%</span>
                  </div>
                </div>
                <div className="percentile-hint">Higher is better (fewer open gaps)</div>
              </div>
            </div>

            <div className="overview-card comparison-stats">
              <div className="card-header">
                <Target size={24} />
                <h3>Peer Comparison</h3>
              </div>
              <div className="comparison-metrics">
                <div className="metric-row">
                  <span className="metric-label">Average Open Gaps (Peers)</span>
                  <span className="metric-value">{metrics?.avg_open_gaps_similar}</span>
                  {metrics?.current_open_gaps > metrics?.avg_open_gaps_similar ? (
                    <TrendingDown className="trend-icon worse" size={20} />
                  ) : (
                    <TrendingUp className="trend-icon better" size={20} />
                  )}
                </div>
                <div className="metric-row">
                  <span className="metric-label">Average Closed Gaps (Peers)</span>
                  <span className="metric-value">{metrics?.avg_closed_gaps_similar}</span>
                  {metrics?.current_closed_gaps < metrics?.avg_closed_gaps_similar ? (
                    <TrendingDown className="trend-icon worse" size={20} />
                  ) : (
                    <TrendingUp className="trend-icon better" size={20} />
                  )}
                </div>
                <div className="metric-row">
                  <span className="metric-label">Better Performers</span>
                  <span className="metric-value">{metrics?.better_performers_count}</span>
                  <Award className="trend-icon" size={20} />
                </div>
              </div>
            </div>
          </div>

          {/* Better Performers Section */}
          {comparisonData?.better_performers && comparisonData.better_performers.length > 0 && (
            <div className="better-performers-section">
              <div className="section-header">
                <Award size={24} />
                <h3>Top Performing Similar Members</h3>
                <p>Learn from members with better care gap management</p>
              </div>
              <div className="performers-grid">
                {comparisonData.better_performers.slice(0, 6).map((performer) => (
                  <div key={performer.member_id} className="performer-card">
                    <div className="performer-avatar">
                      {performer.name.split(' ').map(n => n[0]).join('')}
                    </div>
                    <div className="performer-info">
                      <h4>{performer.name}</h4>
                      <p className="performer-id">{performer.member_id}</p>
                      <div className="performer-stats">
                        <div className="stat-badge success">
                          <CheckCircle size={14} />
                          {performer.open_gaps} Open
                        </div>
                        <div className="stat-badge info">
                          {performer.closed_gaps} Closed
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Current Gaps Analysis */}
          {comparisonData?.current_gaps && comparisonData.current_gaps.length > 0 ? (
            <div className="gaps-analysis-section">
              <div className="section-header">
                <AlertCircle size={24} />
                <h3>Current Care Gaps Requiring Action</h3>
                <p>Focus areas for improvement</p>
              </div>
              <div className="gaps-list">
                {comparisonData.current_gaps.map((gap) => (
                  <div key={gap.care_gap_id} className="gap-analysis-card">
                    <div className="gap-card-header">
                      <div className="gap-title">
                        <h4>{gap.measure_name}</h4>
                        <span className="gap-badge">{gap.measure_id}</span>
                      </div>
                      <span className="gap-status open">OPEN</span>
                    </div>
                    <div className="gap-card-body">
                      <div className="gap-detail">
                        <span className="detail-label">Created:</span>
                        <span className="detail-value">{gap.created_on}</span>
                      </div>
                      <div className="gap-detail">
                        <span className="detail-label">Lookback Period:</span>
                        <span className="detail-value">{gap.lookback_months} months</span>
                      </div>
                      <div className="gap-detail">
                        <span className="detail-label">Required CPT Codes:</span>
                        <span className="detail-value code">{gap.cpt_codes}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="compliant-member-section">
              <div className="section-header">
                <CheckCircle size={24} />
                <h3>Fully Compliant Member</h3>
                <p>No open care gaps - Excellent performance!</p>
              </div>
              <div className="compliant-message">
                <div className="compliant-icon">🎉</div>
                <h4>Outstanding Care Gap Management</h4>
                <p>This member has no open care gaps and is fully compliant with all applicable quality measures. They serve as an excellent example for other members.</p>
              </div>
            </div>
          )}

          {/* Improvement Guidelines */}
          {comparisonData?.improvement_guidelines && comparisonData.improvement_guidelines.length > 0 && (
            <div className="guidelines-section">
              <div className="section-header">
                <Lightbulb size={24} />
                <h3>Improvement Guidelines & Best Practices</h3>
                <p>Evidence-based recommendations to close care gaps</p>
              </div>
              <div className="guidelines-list">
                {comparisonData.improvement_guidelines.map((guideline, index) => (
                  <div key={index} className="guideline-card">
                    <div className="guideline-header">
                      <div className="guideline-icon">
                        <Target size={20} />
                      </div>
                      <h4>{guideline.measure_name}</h4>
                    </div>
                    
                    {guideline.numerator_criteria && (
                      <div className="guideline-section">
                        <h5>📋 Compliance Criteria</h5>
                        <p>{guideline.numerator_criteria}</p>
                      </div>
                    )}

                    {guideline.best_practices && guideline.best_practices.length > 0 && (
                      <div className="guideline-section">
                        <h5>✨ Best Practices</h5>
                        <ul className="practices-list">
                          {guideline.best_practices.map((practice, idx) => (
                            <li key={idx}>
                              <CheckCircle size={16} className="practice-icon" />
                              {practice}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {guideline.acceptable_documentation && guideline.acceptable_documentation.length > 0 && (
                      <div className="guideline-section">
                        <h5>📄 Acceptable Documentation</h5>
                        <ul className="documentation-list">
                          {guideline.acceptable_documentation.map((doc, idx) => (
                            <li key={idx}>{doc}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="guideline-action">
                      <button className="btn-action-primary">
                        <Target size={16} />
                        Create Action Plan
                      </button>
                      <button className="btn-action-secondary">
                        View Full Guidelines
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Key Recommendations - Only show if member has open gaps */}
          {metrics?.current_open_gaps > 0 && (
            <div className="recommendations-section">
              <div className="section-header">
                <TrendingUp size={24} />
                <h3>Key Recommendations</h3>
              </div>
              <div className="recommendations-grid">
                <div className="recommendation-card priority-high">
                  <div className="rec-icon">🎯</div>
                  <h4>Immediate Actions</h4>
                  <ul>
                    <li>Schedule preventive screenings for all open gaps</li>
                    <li>Contact member within 48 hours for outreach</li>
                    <li>Verify member contact information is current</li>
                  </ul>
                </div>
                <div className="recommendation-card priority-medium">
                  <div className="rec-icon">📞</div>
                  <h4>Outreach Strategy</h4>
                  <ul>
                    <li>Use multi-channel approach (phone, SMS, email)</li>
                    <li>Emphasize $0 copay for preventive services</li>
                    <li>Offer flexible appointment scheduling</li>
                  </ul>
                </div>
                <div className="recommendation-card priority-low">
                  <div className="rec-icon">📊</div>
                  <h4>Long-term Goals</h4>
                  <ul>
                    <li>Establish regular preventive care schedule</li>
                    <li>Build relationship with primary care provider</li>
                    <li>Track and celebrate gap closure milestones</li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="comparison-footer">
          <button className="btn-close" onClick={onClose}>Close Analysis</button>
          <button className="btn-export">Export Report</button>
        </div>
      </div>
    </div>
  );
}

export default MemberComparison;
