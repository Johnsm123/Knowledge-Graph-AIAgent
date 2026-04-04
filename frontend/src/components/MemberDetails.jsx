import { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Phone, Mail, Calendar, FileText, MessageCircle, Send, X, Sparkles, Loader, GitCompare, Bot } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import axios from 'axios';
import MemberComparison from './MemberComparison';
import EmailPanel from './EmailPanel';
import './MemberDetails.css';

const API_BASE = 'http://localhost:5001/api/v1';

// Defined outside MemberDetails to keep a stable reference across re-renders.
// react-markdown v10 removed the `className` prop — use a wrapper div instead.
function MarkdownContent({ text, className = '' }) {
  if (!text) return null;
  return (
    <div className={`agent-markdown ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {text.trim()}
      </ReactMarkdown>
    </div>
  );
}

// Agent panel configuration — order must match AGENT_ORDER in care_gap_agents.py
const AGENT_CONFIG = {
  patient_analyst:     { icon: '👤', label: 'Patient Profile Analysis',     color: '#3b82f6' },
  hedis_measure_agent: { icon: '📏', label: 'HEDIS Measures Review',         color: '#8b5cf6' },
  exclusion_agent:     { icon: '🚫', label: 'Exclusion Check',               color: '#f59e0b' },
  code_validator:      { icon: '✅', label: 'CPT Code Validation',           color: '#06b6d4' },
  care_gap_agent:      { icon: '📋', label: 'Care Gap Report',               color: '#ef4444' },
  recommendation_agent:{ icon: '💡', label: 'Recommendations & Outreach',    color: '#10b981' },
};
const AGENT_ORDER = Object.keys(AGENT_CONFIG);

function MemberDetails({ member, onBack }) {
  const [details, setDetails]             = useState(null);
  const [loading, setLoading]             = useState(true);
  const [activeTab, setActiveTab]         = useState('overview');

  // AI suggestions state
  const [aiMetadata, setAiMetadata]       = useState(null);   // metadata event payload
  const [agentStreams, setAgentStreams]    = useState({});     // { agentName: content }
  const [streamingAgent, setStreamingAgent] = useState(null); // currently running agent name
  const [loadingAI, setLoadingAI]         = useState(false);
  const [aiDone, setAiDone]               = useState(false);
  const eventSourceRef                    = useRef(null);

  // Chat state
  const [chatOpen, setChatOpen]           = useState(false);
  const [chatMessages, setChatMessages]   = useState([]);
  const [messageInput, setMessageInput]   = useState('');
  const [chatLoading, setChatLoading]     = useState(false);
  const chatBottomRef                     = useRef(null);

  // Email panel state
  const [emailPanelOpen, setEmailPanelOpen] = useState(false);

  // Other UI state
  const [showAppointmentModal, setShowAppointmentModal] = useState(false);
  const [selectedGap, setSelectedGap]     = useState(null);
  const [showComparison, setShowComparison] = useState(false);

  // Appointment booking state
  const [appointmentDate, setAppointmentDate] = useState('');
  const [appointmentTime, setAppointmentTime] = useState('09:00');
  const [bookingLoading, setBookingLoading]   = useState(false);
  const [bookingError, setBookingError]       = useState('');
  // keyed by care_gap_id → { appointment_id, lab_number, lab_specialist, ... }
  const [bookings, setBookings]               = useState({});
  const [viewBooking, setViewBooking]         = useState(null); // booking object being viewed
  const [completingGap, setCompletingGap]     = useState(false);
  const [completedGaps, setCompletedGaps]     = useState(new Set()); // care_gap_ids closed this session

  useEffect(() => {
    if (member) fetchMemberDetails();
    return () => {
      // Clean up any open SSE connection when unmounting
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [member]);

  // Auto-scroll chat to bottom on new messages
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, chatLoading]);

  // Inject greeting when chat first opens
  useEffect(() => {
    if (chatOpen && chatMessages.length === 0 && details) {
      const openGapCount = details.open_gaps?.length || 0;
      setChatMessages([{
        id: Date.now(),
        role: 'assistant',
        text: `Hi! I'm your AI care manager assistant for **${member.name}**.\n\nI have full access to their profile, ${openGapCount} open care gap${openGapCount !== 1 ? 's' : ''}, and claims history. Ask me anything about this member — gaps, outreach strategy, clinical guidance, or coverage.`,
        timestamp: new Date().toISOString(),
      }]);
    }
  }, [chatOpen]);

  const fetchMemberDetails = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_BASE}/members/${member.member_id}/details`);
      setDetails(response.data);
    } catch (error) {
      console.error('Error fetching member details:', error);
    } finally {
      setLoading(false);
    }
  };

  // ── AI Suggestions via SSE ─────────────────────────────────────────────────

  const getAISuggestions = () => {
    // Close any existing stream
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setLoadingAI(true);
    setAiMetadata(null);
    setAgentStreams({});
    setStreamingAgent(null);
    setAiDone(false);

    const es = new EventSource(`${API_BASE}/care-gaps/validate/${member.member_id}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const { type, payload } = JSON.parse(event.data);

        if (type === 'metadata') {
          setAiMetadata(payload);
          setLoadingAI(false);   // counts are visible — spinner off

        } else if (type === 'agent_start') {
          setStreamingAgent(payload.agent);

        } else if (type === 'agent_done') {
          setAgentStreams(prev => ({ ...prev, [payload.agent]: payload.content }));
          setStreamingAgent(null);

        } else if (type === 'complete') {
          setAiDone(true);
          setStreamingAgent(null);
          es.close();

        } else if (type === 'error') {
          console.error('SSE error:', payload.message);
          setLoadingAI(false);
          es.close();
        }
      } catch (e) {
        console.error('SSE parse error:', e);
      }
    };

    es.onerror = () => {
      setLoadingAI(false);
      setStreamingAgent(null);
      es.close();
    };
  };

  // ── Conversational Chat ────────────────────────────────────────────────────

  const handleSendMessage = async () => {
    if (!messageInput.trim() || chatLoading) return;

    const userText = messageInput.trim();
    setMessageInput('');

    const userMsg = {
      id: Date.now(),
      role: 'user',
      text: userText,
      timestamp: new Date().toISOString(),
    };
    setChatMessages(prev => [...prev, userMsg]);
    setChatLoading(true);

    try {
      // Build history from existing messages (exclude the greeting for brevity)
      const history = chatMessages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role, content: m.text }));

      const response = await axios.post(`${API_BASE}/chat/member/${member.member_id}`, {
        message: userText,
        history,
      });

      setChatMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'assistant',
        text: response.data.reply,
        timestamp: new Date().toISOString(),
      }]);
    } catch (error) {
      setChatMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'assistant',
        text: 'Sorry, I encountered an error connecting to the AI. Please try again.',
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setChatLoading(false);
    }
  };

  // ── Rendering helpers ──────────────────────────────────────────────────────

  const renderAgentPanel = (agentName) => {
    const cfg = AGENT_CONFIG[agentName];
    const content = agentStreams[agentName];
    const isRunning = streamingAgent === agentName;
    const isPending = !content && !isRunning;

    if (isPending) return null;

    return (
      <div
        key={agentName}
        className={`agent-stream-panel ${isRunning ? 'running' : 'done'}`}
        style={{ borderLeftColor: cfg.color }}
      >
        <div className="agent-panel-header">
          <span className="agent-icon" style={{ background: cfg.color }}>
            {cfg.icon}
          </span>
          <div className="agent-panel-title">
            <span className="agent-label">{cfg.label}</span>
            <span className="agent-name-badge">{agentName}</span>
          </div>
          {isRunning && (
            <div className="agent-running-badge">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span style={{ marginLeft: 6, fontSize: '0.75rem', color: '#64748b' }}>Analyzing…</span>
            </div>
          )}
        </div>
        {isRunning ? (
          <div className="agent-skeleton">
            <div className="skeleton-line long" />
            <div className="skeleton-line medium" />
            <div className="skeleton-line short" />
          </div>
        ) : (
          <div className="agent-panel-content">
            <MarkdownContent text={content} />
          </div>
        )}
      </div>
    );
  };

  const handleBookAppointment = (gap) => {
    setSelectedGap(gap);
    setAppointmentDate('');
    setAppointmentTime('09:00');
    setBookingError('');
    setShowAppointmentModal(true);
  };

  const confirmAppointment = async () => {
    if (!appointmentDate) { setBookingError('Please select a date.'); return; }
    if (!appointmentTime) { setBookingError('Please select a time.'); return; }
    setBookingLoading(true);
    setBookingError('');
    try {
      const res = await axios.post(`${API_BASE}/appointments/book`, {
        member_id:        member.member_id,
        measure_id:       selectedGap.measure_id,
        measure_name:     selectedGap.measure_name,
        appointment_date: appointmentDate,
        appointment_time: appointmentTime,
        provider_id:      details.profile.pcp_id || '',
        care_gap_id:      selectedGap.care_gap_id,
      });
      if (res.data.status === 'success') {
        setBookings(prev => ({
          ...prev,
          [selectedGap.care_gap_id]: {
            ...res.data,
            measure_name:     selectedGap.measure_name,
            care_gap_id:      selectedGap.care_gap_id,
            member_name:      member.name,
            plan_id:          details.profile.plan_id,
            insurance_type:   details.profile.insurance_type || 'Commercial',
            pcp_name:         details.profile.pcp_name,
          },
        }));
        setShowAppointmentModal(false);
        setSelectedGap(null);
      } else {
        setBookingError(res.data.error || 'Booking failed. Please try again.');
      }
    } catch (err) {
      setBookingError(err.response?.data?.error || 'Network error. Please try again.');
    } finally {
      setBookingLoading(false);
    }
  };

  const handleCompleteScreening = async (booking) => {
    setCompletingGap(true);
    try {
      const res = await axios.post(
        `${API_BASE}/appointments/${booking.appointment_id}/complete`,
        { care_gap_id: booking.care_gap_id }
      );
      if (res.data.status === 'success') {
        setViewBooking(prev => ({ ...prev, claim_id: res.data.claim_id, status: 'Completed' }));
        setBookings(prev => ({
          ...prev,
          [booking.care_gap_id]: { ...prev[booking.care_gap_id], claim_id: res.data.claim_id, status: 'Completed' },
        }));
        setCompletedGaps(prev => new Set([...prev, booking.care_gap_id]));
        // Refresh member details to reflect closed gap
        await fetchMemberDetails();
      }
    } catch (err) {
      console.error('Complete screening error:', err);
    } finally {
      setCompletingGap(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading member details…</p>
      </div>
    );
  }

  return (
    <div className="member-details">
      <div className="details-header">
        <button className="back-button" onClick={onBack}>
          <ArrowLeft size={20} />
          Back to Dashboard
        </button>
      </div>

      <div className="member-profile-card">
        <div className="profile-avatar-large">
          {member.name.split(' ').map(n => n[0]).join('')}
        </div>
        <div className="profile-info">
          <h1>{member.name}</h1>
          <p className="member-id-large">{member.member_id}</p>
          <div className="profile-meta">
            <span>{details?.profile.age_str}</span>
            <span>•</span>
            <span>{details?.profile.gender}</span>
            <span>•</span>
            <span>DOB: {details?.profile.dob}</span>
          </div>
        </div>
        <div className="profile-actions">
          <button className="action-btn" onClick={() => setShowComparison(true)}>
            <GitCompare size={18} />
            Compare
          </button>
          <button className="action-btn" onClick={() => setChatOpen(true)}>
            <Bot size={18} />
            AI Chat
          </button>
          <button className="action-btn">
            <Phone size={18} />
            Call
          </button>
          <button className="action-btn" onClick={() => setEmailPanelOpen(true)}>
            <Mail size={18} />
            Email
          </button>
        </div>
      </div>

      <div className="details-tabs">
        <button className={activeTab === 'overview' ? 'active' : ''} onClick={() => setActiveTab('overview')}>
          Overview
        </button>
        <button className={activeTab === 'gaps' ? 'active' : ''} onClick={() => setActiveTab('gaps')}>
          Care Gaps ({details?.open_gaps?.length || 0})
        </button>
        <button className={activeTab === 'claims' ? 'active' : ''} onClick={() => setActiveTab('claims')}>
          Claims ({details?.claims?.length || 0})
        </button>
        <button className={activeTab === 'outreach' ? 'active' : ''} onClick={() => setActiveTab('outreach')}>
          Outreach History
        </button>
      </div>

      <div className="details-content">

        {/* ── OVERVIEW TAB ───────────────────────────────────────────────── */}
        {activeTab === 'overview' && (
          <div className="overview-tab">
            <div className="info-grid">
              <div className="info-card">
                <h3>Plan Information</h3>
                <div className="info-row">
                  <span className="label">Plan ID:</span>
                  <span className="value">{details?.profile.plan_id}</span>
                </div>
                <div className="info-row">
                  <span className="label">Copay:</span>
                  <span className="value">${details?.profile.copay}</span>
                </div>
                <div className="info-row">
                  <span className="label">Preventive Covered:</span>
                  <span className="value">{details?.profile.preventive_covered}</span>
                </div>
              </div>

              <div className="info-card">
                <h3>Primary Care Provider</h3>
                <div className="info-row">
                  <span className="label">Name:</span>
                  <span className="value">{details?.profile.pcp_name}</span>
                </div>
                <div className="info-row">
                  <span className="label">Specialty:</span>
                  <span className="value">{details?.profile.pcp_specialty}</span>
                </div>
                <div className="info-row">
                  <span className="label">Network:</span>
                  <span className="value">{details?.profile.pcp_network_status}</span>
                </div>
              </div>

              <div className="info-card">
                <h3>Care Gap Summary</h3>
                <div className="info-row">
                  <span className="label">Open Gaps:</span>
                  <span className="value highlight-red">{details?.open_gaps?.length || 0}</span>
                </div>
                <div className="info-row">
                  <span className="label">Closed Gaps:</span>
                  <span className="value highlight-green">{details?.closed_gaps?.length || 0}</span>
                </div>
                <div className="info-row">
                  <span className="label">Total Claims:</span>
                  <span className="value">{details?.claims?.length || 0}</span>
                </div>
              </div>
            </div>

            {details && (
              <div className="quick-gaps">
                <div className="quick-gaps-header">
                  <h3>
                    {details.open_gaps?.length > 0
                      ? 'Open Care Gaps — Action Required'
                      : 'Care Gap Analysis'}
                  </h3>
                  <button
                    className="btn-ai-suggestions"
                    onClick={getAISuggestions}
                    disabled={loadingAI || (streamingAgent !== null)}
                  >
                    {loadingAI ? (
                      <>
                        <Loader size={16} className="spinning" />
                        Analyzing…
                      </>
                    ) : (
                      <>
                        <Sparkles size={16} />
                        {aiMetadata ? 'Re-run AI Analysis' : 'Get AI Suggestions'}
                      </>
                    )}
                  </button>
                </div>

                {/* ── AI Streaming Panel ───────────────────────────────── */}
                {(aiMetadata || loadingAI) && (
                  <div className="ai-suggestions-panel">
                    <div className="ai-panel-header">
                      <Sparkles size={24} />
                      <h4>AI-Powered Care Gap Analysis</h4>
                      {!aiDone && streamingAgent && (
                        <span className="ai-status-badge">
                          <Loader size={12} className="spinning" style={{ marginRight: 4 }} />
                          Agent {AGENT_ORDER.indexOf(streamingAgent) + 1} of 6 running…
                        </span>
                      )}
                      {aiDone && (
                        <span className="ai-done-badge">✓ Analysis complete</span>
                      )}
                    </div>

                    {/* Summary counts — show as soon as metadata arrives */}
                    {aiMetadata && (
                      <div className="ai-summary">
                        <div className="summary-stat">
                          <span className="stat-label">Applicable Measures</span>
                          <span className="stat-value">{aiMetadata.applicable_measures?.length || 0}</span>
                        </div>
                        <div className="summary-stat">
                          <span className="stat-label">Open Gaps</span>
                          <span className="stat-value red">{aiMetadata.open_gaps_detected?.length || 0}</span>
                        </div>
                        <div className="summary-stat">
                          <span className="stat-label">Compliant</span>
                          <span className="stat-value green">{aiMetadata.compliant_measures?.length || 0}</span>
                        </div>
                      </div>
                    )}

                    {/* Progress bar */}
                    {!aiDone && (
                      <div className="agent-progress-bar">
                        {AGENT_ORDER.map((name, idx) => {
                          const done = !!agentStreams[name];
                          const running = streamingAgent === name;
                          return (
                            <div
                              key={name}
                              className={`progress-step ${done ? 'done' : running ? 'running' : 'pending'}`}
                              title={AGENT_CONFIG[name].label}
                            >
                              <span className="progress-step-icon">{AGENT_CONFIG[name].icon}</span>
                              <span className="progress-step-num">{idx + 1}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Agent panels — appear as each agent finishes */}
                    <div className="agent-streams-container">
                      {AGENT_ORDER.map(name => renderAgentPanel(name))}
                    </div>

                    {/* Gap + compliant tables once we have metadata */}
                    {aiMetadata?.open_gaps_detected?.length > 0 && (
                      <div className="gaps-table-section">
                        <h5>📊 Open Gaps Detected</h5>
                        <table className="gaps-summary-table">
                          <thead>
                            <tr><th>Measure</th><th>Status</th><th>Priority</th></tr>
                          </thead>
                          <tbody>
                            {aiMetadata.open_gaps_detected.map((g, i) => (
                              <tr key={i}>
                                <td><strong>{g}</strong></td>
                                <td><span className="status-badge-table open">Open</span></td>
                                <td><span className="priority-badge high">High</span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {aiMetadata?.compliant_measures?.length > 0 && (
                      <div className="gaps-table-section">
                        <h5>✅ Compliant Measures</h5>
                        <table className="gaps-summary-table">
                          <thead>
                            <tr><th>Measure</th><th>Status</th></tr>
                          </thead>
                          <tbody>
                            {aiMetadata.compliant_measures.map((m, i) => (
                              <tr key={i}>
                                <td><strong>{m}</strong></td>
                                <td><span className="status-badge-table compliant">Compliant</span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                {/* Gap cards — only when gaps exist */}
                {details.open_gaps?.length > 0 ? (
                  details.open_gaps.map(gap => {
                    const booking = bookings[gap.care_gap_id];
                    const isClosed = completedGaps.has(gap.care_gap_id);
                    return (
                      <div key={gap.care_gap_id} className={`quick-gap-card ${isClosed ? 'quick-gap-card--closed' : ''}`}>
                        <div className="gap-header">
                          <h4>{gap.measure_name}</h4>
                          <div style={{ display: 'flex', gap: 8 }}>
                            <span className="gap-badge">{gap.measure_id}</span>
                            {isClosed && <span className="gap-badge gap-badge--closed">✓ Closed</span>}
                            {booking && !isClosed && <span className="gap-badge gap-badge--booked">📅 Scheduled</span>}
                          </div>
                        </div>
                        <p className="gap-description">{gap.resolution_guide}</p>
                        <div className="gap-actions">
                          {!booking ? (
                            <button className="btn-primary" onClick={() => handleBookAppointment(gap)}>
                              <Calendar size={16} />
                              Book Appointment
                            </button>
                          ) : (
                            <button className="btn-view-booking" onClick={() => setViewBooking(booking)}>
                              <Calendar size={16} />
                              View Booking
                            </button>
                          )}
                          <button className="btn-secondary">View Guidelines</button>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  !aiMetadata && !loadingAI && (
                    <div className="compliant-notice">
                      <span className="compliant-icon">✓</span>
                      <div>
                        <strong>Compliant with all quality measures</strong>
                        <p>Run AI analysis to get a full compliance summary and preventive care recommendations.</p>
                      </div>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        )}

        {/* ── GAPS TAB ───────────────────────────────────────────────────── */}
        {activeTab === 'gaps' && (
          <div className="gaps-tab">
            {details?.open_gaps?.length > 0 ? (
              <div className="gaps-list">
                {details.open_gaps.map(gap => (
                  <div key={gap.care_gap_id} className="gap-detail-card">
                    <div className="gap-detail-header">
                      <div>
                        <h3>{gap.measure_name}</h3>
                        <span className="gap-id">{gap.care_gap_id}</span>
                      </div>
                      <span className="gap-status open">OPEN</span>
                    </div>
                    <div className="gap-detail-body">
                      <div className="gap-info-row">
                        <span className="label">Measure ID:</span>
                        <span className="value">{gap.measure_id}</span>
                      </div>
                      <div className="gap-info-row">
                        <span className="label">Created On:</span>
                        <span className="value">{gap.created_on}</span>
                      </div>
                      <div className="gap-info-row">
                        <span className="label">Lookback Period:</span>
                        <span className="value">{gap.lookback_months} months</span>
                      </div>
                      <div className="gap-info-row">
                        <span className="label">Required CPT Codes:</span>
                        <span className="value code">{gap.required_cpt_codes}</span>
                      </div>
                      <div className="gap-resolution">
                        <h4>Resolution Guide:</h4>
                        <p>{gap.resolution_guide}</p>
                      </div>
                    </div>
                    <div className="gap-detail-footer">
                      {!bookings[gap.care_gap_id] ? (
                        <button className="btn-primary" onClick={() => handleBookAppointment(gap)}>
                          <Calendar size={16} />
                          Schedule Service
                        </button>
                      ) : (
                        <button className="btn-view-booking" onClick={() => setViewBooking(bookings[gap.care_gap_id])}>
                          <Calendar size={16} />
                          View Booking
                        </button>
                      )}
                      <button className="btn-secondary" onClick={() => setChatOpen(true)}>
                        <Bot size={16} />
                        Ask AI Assistant
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="no-data">
                <h3>No Open Care Gaps</h3>
                <p>This member is compliant with all quality measures.</p>
              </div>
            )}

            {details?.closed_gaps?.length > 0 && (
              <div className="closed-gaps-section">
                <h3>Closed Care Gaps</h3>
                {details.closed_gaps.map(gap => (
                  <div key={gap.care_gap_id} className="closed-gap-card">
                    <div className="closed-gap-info">
                      <h4>{gap.measure_name}</h4>
                      <span className="gap-status closed">CLOSED</span>
                    </div>
                    <p>Closed on: {gap.closed_on}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── CLAIMS TAB ─────────────────────────────────────────────────── */}
        {activeTab === 'claims' && (
          <div className="claims-tab">
            {details?.claims?.length > 0 ? (
              <div className="claims-table">
                <table>
                  <thead>
                    <tr>
                      <th>Service Date</th>
                      <th>CPT Code</th>
                      <th>ICD Code</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {details.claims.map((claim, i) => (
                      <tr key={i}>
                        <td>{claim.service_date}</td>
                        <td><code>{claim.cpt_code}</code></td>
                        <td><code>{claim.icd_code}</code></td>
                        <td><span className="status-badge">Processed</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="no-data">
                <FileText size={48} color="#94a3b8" />
                <h3>No Claims Found</h3>
                <p>No claims data available for this member.</p>
              </div>
            )}
          </div>
        )}

        {/* ── OUTREACH TAB ───────────────────────────────────────────────── */}
        {activeTab === 'outreach' && (
          <div className="outreach-tab">
            {details?.outreach_history?.length > 0 ? (
              <div className="outreach-timeline">
                {details.outreach_history.map(o => (
                  <div key={o.outreach_id} className="outreach-item">
                    <div className="outreach-icon">
                      <MessageCircle size={20} />
                    </div>
                    <div className="outreach-content">
                      <div className="outreach-header">
                        <h4>{o.channel}</h4>
                        <span className="outreach-date">{o.date}</span>
                      </div>
                      <p>Care Gap: {o.measure_name}</p>
                      <span className={`outreach-status ${o.status.toLowerCase()}`}>{o.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="no-data">
                <MessageCircle size={48} color="#94a3b8" />
                <h3>No Outreach History</h3>
                <p>No outreach attempts recorded for this member.</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── CONVERSATIONAL CHAT PANEL ────────────────────────────────────── */}
      {chatOpen && (
        <div className="chat-modal">
          <div className="chat-container">
            <div className="chat-header">
              <div className="chat-header-info">
                <Bot size={20} />
                <div>
                  <h3>AI Care Manager</h3>
                  <p className="chat-member-context">{member.name} · {details?.open_gaps?.length || 0} open gaps</p>
                </div>
              </div>
              <button className="close-chat" onClick={() => setChatOpen(false)}>
                <X size={20} />
              </button>
            </div>

            <div className="chat-messages">
              {chatMessages.map(msg => (
                <div key={msg.id} className={`chat-message ${msg.role === 'user' ? 'care_manager' : 'ai_agent'}`}>
                  <div className="message-bubble">
                    {msg.role === 'assistant' && (
                      <div className="ai-badge">
                        <Bot size={12} />
                        AI Assistant
                      </div>
                    )}
                    <div className="message-content">
                      <MarkdownContent text={msg.text} className="chat-markdown" />
                    </div>
                    <span className="message-time">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}

              {chatLoading && (
                <div className="chat-message ai_agent">
                  <div className="message-bubble typing">
                    <div className="typing-indicator">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </div>
                  </div>
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>

            <div className="chat-input">
              <input
                type="text"
                placeholder={`Ask about ${member.name}…`}
                value={messageInput}
                onChange={e => setMessageInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                disabled={chatLoading}
              />
              <button onClick={handleSendMessage} disabled={chatLoading || !messageInput.trim()}>
                <Send size={18} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── APPOINTMENT BOOKING MODAL ─────────────────────────────────────── */}
      {showAppointmentModal && selectedGap && (
        <div className="modal-overlay">
          <div className="appt-modal">
            <div className="appt-modal-header">
              <div>
                <h3>Schedule Screening</h3>
                <p className="appt-modal-sub">{selectedGap.measure_name} · {selectedGap.measure_id}</p>
              </div>
              <button className="appt-modal-close" onClick={() => { setShowAppointmentModal(false); setBookingError(''); }}>
                <X size={18} />
              </button>
            </div>

            <div className="appt-modal-body">
              <div className="appt-member-row">
                <span className="appt-avatar">{member.name.split(' ').map(n => n[0]).join('').slice(0,2)}</span>
                <div>
                  <strong>{member.name}</strong>
                  <span className="appt-member-id"> · {member.member_id}</span>
                </div>
              </div>

              <div className="appt-fields">
                <div className="appt-field-group">
                  <label><Calendar size={14} /> Appointment Date *</label>
                  <input
                    type="date"
                    value={appointmentDate}
                    min={new Date().toISOString().split('T')[0]}
                    onChange={e => setAppointmentDate(e.target.value)}
                    className="appt-input"
                  />
                </div>
                <div className="appt-field-group">
                  <label>⏰ Appointment Time *</label>
                  <select value={appointmentTime} onChange={e => setAppointmentTime(e.target.value)} className="appt-input">
                    {["08:00","08:30","09:00","09:30","10:00","10:30","11:00","11:30",
                      "12:00","12:30","13:00","13:30","14:00","14:30","15:00","15:30","16:00","16:30"].map(t => {
                      const [h, m] = t.split(':');
                      const hr = parseInt(h);
                      const label = `${hr > 12 ? hr-12 : hr}:${m} ${hr >= 12 ? 'PM' : 'AM'}`;
                      return <option key={t} value={t}>{label}</option>;
                    })}
                  </select>
                </div>
              </div>

              <div className="appt-info-box">
                <p className="appt-info-title">📧 Confirmation email will be sent to the member&apos;s registered email address with:</p>
                <ul className="appt-info-list">
                  <li>Lab number and specialist assignment</li>
                  <li>Screening CPT &amp; ICD codes</li>
                  <li>Pre-appointment instructions</li>
                  <li>Insurance and plan information</li>
                </ul>
              </div>

              {bookingError && <div className="appt-error">{bookingError}</div>}
            </div>

            <div className="appt-modal-footer">
              <button className="btn-secondary" onClick={() => { setShowAppointmentModal(false); setBookingError(''); }}>
                Cancel
              </button>
              <button className="btn-primary appt-confirm-btn" onClick={confirmAppointment} disabled={bookingLoading}>
                {bookingLoading ? (
                  <><span className="appt-spinner" /> Booking &amp; Sending Email…</>
                ) : (
                  <><Calendar size={15} /> Confirm &amp; Send Invite</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── VIEW BOOKING MODAL ────────────────────────────────────────────── */}
      {viewBooking && (
        <div className="modal-overlay">
          <div className="vb-modal">
            <div className="vb-header">
              <div>
                <h3>Booking Details</h3>
                <p className="vb-sub">{viewBooking.measure_name}</p>
              </div>
              <button className="appt-modal-close" onClick={() => setViewBooking(null)}><X size={18} /></button>
            </div>

            <div className="vb-body">
              {/* Status banner */}
              <div className={`vb-status-banner ${viewBooking.status === 'Completed' ? 'vb-status-done' : 'vb-status-scheduled'}`}>
                {viewBooking.status === 'Completed'
                  ? '✅ Screening Completed — Care Gap Closed'
                  : '📅 Appointment Scheduled'}
              </div>

              <div className="vb-grid">
                <div className="vb-section">
                  <div className="vb-section-title">📅 Appointment</div>
                  <div className="vb-row"><span>Date</span><strong>{viewBooking.appointment_date}</strong></div>
                  <div className="vb-row"><span>Time</span><strong>{viewBooking.appointment_time}</strong></div>
                  <div className="vb-row"><span>Appointment ID</span><code>{viewBooking.appointment_id}</code></div>
                  <div className="vb-row"><span>Email Sent</span><strong>{viewBooking.email_sent ? `✓ ${viewBooking.member_email}` : 'No email on file'}</strong></div>
                </div>

                <div className="vb-section">
                  <div className="vb-section-title">🏥 Lab &amp; Specialist</div>
                  <div className="vb-row"><span>Lab Number</span><strong>{viewBooking.lab_number}</strong></div>
                  <div className="vb-row"><span>Location</span><strong>{viewBooking.lab_location}</strong></div>
                  <div className="vb-row"><span>Specialist</span><strong>{viewBooking.lab_specialist}</strong></div>
                  <div className="vb-row"><span>Referring PCP</span><strong>{viewBooking.pcp_name || details?.profile?.pcp_name}</strong></div>
                </div>

                <div className="vb-section">
                  <div className="vb-section-title">🩺 Screening Codes</div>
                  <div className="vb-row"><span>Screening</span><strong>{viewBooking.measure_name}</strong></div>
                  <div className="vb-row"><span>CPT Codes</span><code>{viewBooking.cpt_codes || '—'}</code></div>
                  <div className="vb-row"><span>ICD-10 Codes</span><code>{viewBooking.icd_codes || '—'}</code></div>
                </div>

                <div className="vb-section">
                  <div className="vb-section-title">💳 Insurance &amp; Claim</div>
                  <div className="vb-row"><span>Plan ID</span><code>{viewBooking.plan_id || details?.profile?.plan_id}</code></div>
                  <div className="vb-row"><span>Insurance Type</span><strong>{viewBooking.insurance_type || '—'}</strong></div>
                  <div className="vb-row"><span>Member ID</span><code>{member.member_id}</code></div>
                  {viewBooking.claim_id
                    ? <div className="vb-row"><span>Claim ID</span><code className="vb-claim-id">{viewBooking.claim_id}</code></div>
                    : <div className="vb-row vb-row-pending"><span>Claim ID</span><em>Generated after screening complete</em></div>
                  }
                </div>
              </div>
            </div>

            <div className="vb-footer">
              <button className="btn-secondary" onClick={() => setViewBooking(null)}>Close</button>
              {viewBooking.status !== 'Completed' && !completedGaps.has(viewBooking.care_gap_id) && (
                <button
                  className="btn-complete-screening"
                  onClick={() => handleCompleteScreening(viewBooking)}
                  disabled={completingGap}
                >
                  {completingGap
                    ? <><span className="appt-spinner" /> Processing…</>
                    : <>✅ Mark Screening Complete &amp; Close Gap</>
                  }
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── COMPARISON ────────────────────────────────────────────────────── */}
      {showComparison && (
        <MemberComparison member={member} onClose={() => setShowComparison(false)} />
      )}

      {/* ── EMAIL PANEL ────────────────────────────────────────────────────── */}
      {emailPanelOpen && (
        <EmailPanel member={member} onClose={() => setEmailPanelOpen(false)} />
      )}
    </div>
  );
}

export default MemberDetails;
