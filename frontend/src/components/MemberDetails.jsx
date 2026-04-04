import { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Phone, Mail, Calendar, FileText, MessageCircle, Send, X, Sparkles, Loader, GitCompare, Bot } from 'lucide-react';
import axios from 'axios';
import MemberComparison from './MemberComparison';
import './MemberDetails.css';

const API_BASE = 'http://localhost:5001/api/v1';

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

  // Other UI state
  const [showAppointmentModal, setShowAppointmentModal] = useState(false);
  const [selectedGap, setSelectedGap]     = useState(null);
  const [showComparison, setShowComparison] = useState(false);

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

  const formatText = (text) => {
    if (!text) return null;
    const lines = text.split('\n').filter(l => l.trim());
    return (
      <div className="formatted-response">
        {lines.map((line, idx) => {
          if (line.trim().match(/^[-•*]\s/)) {
            return (
              <div key={idx} className="bullet-point">
                <span className="bullet">•</span>
                <span>{line.replace(/^[-•*]\s/, '')}</span>
              </div>
            );
          } else if (line.trim().match(/^\d+[\.\)]\s/)) {
            return (
              <div key={idx} className="numbered-point">
                <span className="number">{line.match(/^\d+/)[0]}</span>
                <span>{line.replace(/^\d+[\.\)]\s/, '')}</span>
              </div>
            );
          } else if (line.includes(':') && line.split(':')[0].length < 50) {
            const [key, ...rest] = line.split(':');
            return (
              <div key={idx} className="key-value">
                <strong>{key}:</strong> {rest.join(':').trim()}
              </div>
            );
          } else {
            return <p key={idx} className="response-paragraph">{line}</p>;
          }
        })}
      </div>
    );
  };

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
            {formatText(content)}
          </div>
        )}
      </div>
    );
  };

  const handleBookAppointment = (gap) => {
    setSelectedGap(gap);
    setShowAppointmentModal(true);
  };

  const confirmAppointment = async (appointmentDate) => {
    try {
      await axios.post(`${API_BASE}/appointments/book`, {
        member_id: member.member_id,
        measure_id: selectedGap.measure_id,
        appointment_date: appointmentDate,
        provider_id: details.profile.pcp_id,
      });
      alert('Appointment booked successfully!');
      setShowAppointmentModal(false);
      setSelectedGap(null);
    } catch (error) {
      console.error('Error booking appointment:', error);
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
          <button className="action-btn">
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

            {details?.open_gaps && details.open_gaps.length > 0 && (
              <div className="quick-gaps">
                <div className="quick-gaps-header">
                  <h3>Open Care Gaps — Action Required</h3>
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

                {details.open_gaps.map(gap => (
                  <div key={gap.care_gap_id} className="quick-gap-card">
                    <div className="gap-header">
                      <h4>{gap.measure_name}</h4>
                      <span className="gap-badge">{gap.measure_id}</span>
                    </div>
                    <p className="gap-description">{gap.resolution_guide}</p>
                    <div className="gap-actions">
                      <button className="btn-primary" onClick={() => handleBookAppointment(gap)}>
                        <Calendar size={16} />
                        Book Appointment
                      </button>
                      <button className="btn-secondary">View Guidelines</button>
                    </div>
                  </div>
                ))}
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
                      <button className="btn-primary" onClick={() => handleBookAppointment(gap)}>
                        <Calendar size={16} />
                        Schedule Service
                      </button>
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
                      {formatText(msg.text)}
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

      {/* ── APPOINTMENT MODAL ─────────────────────────────────────────────── */}
      {showAppointmentModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Book Appointment</h3>
            <p>Schedule {selectedGap?.measure_name} for {member.name}</p>
            <input type="date" className="date-input" />
            <div className="modal-actions">
              <button className="btn-primary" onClick={() => confirmAppointment(new Date())}>
                Confirm
              </button>
              <button className="btn-secondary" onClick={() => setShowAppointmentModal(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── COMPARISON ────────────────────────────────────────────────────── */}
      {showComparison && (
        <MemberComparison member={member} onClose={() => setShowComparison(false)} />
      )}
    </div>
  );
}

export default MemberDetails;
