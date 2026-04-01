import { useState, useEffect } from 'react';
import { ArrowLeft, Phone, Mail, Calendar, FileText, MessageCircle, Send, X, Sparkles, Loader, GitCompare } from 'lucide-react';
import axios from 'axios';
import MemberComparison from './MemberComparison';
import './MemberDetails.css';

const API_BASE = 'http://localhost:5001/api/v1';

function MemberDetails({ member, onBack }) {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [messageInput, setMessageInput] = useState('');
  const [showAppointmentModal, setShowAppointmentModal] = useState(false);
  const [selectedGap, setSelectedGap] = useState(null);
  const [aiSuggestions, setAiSuggestions] = useState(null);
  const [loadingAI, setLoadingAI] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [showComparison, setShowComparison] = useState(false);

  useEffect(() => {
    if (member) {
      fetchMemberDetails();
    }
  }, [member]);

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

  const handleSendMessage = async () => {
    if (!messageInput.trim()) return;

    const newMessage = {
      id: Date.now(),
      sender: 'care_manager',
      text: messageInput,
      timestamp: new Date().toISOString()
    };

    setChatMessages([...chatMessages, newMessage]);
    const userMessage = messageInput;
    setMessageInput('');
    setSendingMessage(true);

    try {
      await axios.post(`${API_BASE}/chat/send`, {
        member_id: member.member_id,
        message: userMessage,
        sender: 'care_manager'
      });

      // Get AI agent response
      const aiResponse = await axios.post(`${API_BASE}/care-gaps/validate/${member.member_id}`);
      
      // Extract relevant response from agents
      let agentReply = '';
      if (aiResponse.data.agent_responses) {
        const responses = aiResponse.data.agent_responses;
        agentReply = `AI Care Manager:\n\n`;
        
        if (responses.care_gap_validator) {
          agentReply += `📋 Gap Analysis:\n${responses.care_gap_validator}\n\n`;
        }
        
        if (responses.outreach_advisor) {
          agentReply += `📞 Outreach Plan:\n${responses.outreach_advisor}\n\n`;
        }
        
        if (responses.benefit_checker) {
          agentReply += `💰 Coverage Info:\n${responses.benefit_checker}`;
        }
      } else {
        agentReply = 'I\'ve reviewed the member\'s care gaps. Let me help you with the outreach plan.';
      }

      setTimeout(() => {
        const autoReply = {
          id: Date.now() + 1,
          sender: 'ai_agent',
          text: agentReply,
          timestamp: new Date().toISOString()
        };
        setChatMessages(prev => [...prev, autoReply]);
        setSendingMessage(false);
      }, 1500);
    } catch (error) {
      console.error('Error sending message:', error);
      const errorReply = {
        id: Date.now() + 1,
        sender: 'ai_agent',
        text: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date().toISOString()
      };
      setChatMessages(prev => [...prev, errorReply]);
      setSendingMessage(false);
    }
  };

  const formatAgentResponse = (text) => {
    if (!text) return null;

    // Split by lines
    const lines = text.split('\n').filter(line => line.trim());
    
    return (
      <div className="formatted-response">
        {lines.map((line, idx) => {
          // Check if line is a bullet point
          if (line.trim().match(/^[-•*]\s/)) {
            return (
              <div key={idx} className="bullet-point">
                <span className="bullet">•</span>
                <span>{line.replace(/^[-•*]\s/, '')}</span>
              </div>
            );
          }
          // Check if line is a numbered list
          else if (line.trim().match(/^\d+[\.\)]\s/)) {
            return (
              <div key={idx} className="numbered-point">
                <span className="number">{line.match(/^\d+/)[0]}</span>
                <span>{line.replace(/^\d+[\.\)]\s/, '')}</span>
              </div>
            );
          }
          // Check if line contains a colon (key-value pair)
          else if (line.includes(':') && line.split(':')[0].length < 50) {
            const [key, ...valueParts] = line.split(':');
            const value = valueParts.join(':').trim();
            return (
              <div key={idx} className="key-value">
                <strong>{key}:</strong> {value}
              </div>
            );
          }
          // Regular paragraph
          else {
            return <p key={idx} className="response-paragraph">{line}</p>;
          }
        })}
      </div>
    );
  };

  const getAISuggestions = async () => {
    setLoadingAI(true);
    try {
      const response = await axios.post(`${API_BASE}/care-gaps/validate/${member.member_id}`);
      setAiSuggestions(response.data);
    } catch (error) {
      console.error('Error getting AI suggestions:', error);
      alert('Failed to get AI suggestions. Please try again.');
    } finally {
      setLoadingAI(false);
    }
  };

  const handleBookAppointment = async (gap) => {
    setSelectedGap(gap);
    setShowAppointmentModal(true);
  };

  const confirmAppointment = async (appointmentDate) => {
    try {
      await axios.post(`${API_BASE}/appointments/book`, {
        member_id: member.member_id,
        measure_id: selectedGap.measure_id,
        appointment_date: appointmentDate,
        provider_id: details.profile.pcp_id
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
        <p>Loading member details...</p>
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
            <MessageCircle size={18} />
            Chat
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
        <button 
          className={activeTab === 'overview' ? 'active' : ''}
          onClick={() => setActiveTab('overview')}
        >
          Overview
        </button>
        <button 
          className={activeTab === 'gaps' ? 'active' : ''}
          onClick={() => setActiveTab('gaps')}
        >
          Care Gaps ({details?.open_gaps?.length || 0})
        </button>
        <button 
          className={activeTab === 'claims' ? 'active' : ''}
          onClick={() => setActiveTab('claims')}
        >
          Claims ({details?.claims?.length || 0})
        </button>
        <button 
          className={activeTab === 'outreach' ? 'active' : ''}
          onClick={() => setActiveTab('outreach')}
        >
          Outreach History
        </button>
      </div>

      <div className="details-content">
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
                  <h3>Open Care Gaps - Action Required</h3>
                  <button 
                    className="btn-ai-suggestions"
                    onClick={getAISuggestions}
                    disabled={loadingAI}
                  >
                    {loadingAI ? (
                      <>
                        <Loader size={16} className="spinning" />
                        Getting AI Suggestions...
                      </>
                    ) : (
                      <>
                        <Sparkles size={16} />
                        Get AI Suggestions
                      </>
                    )}
                  </button>
                </div>
                
                {aiSuggestions && (
                  <div className="ai-suggestions-panel">
                    <div className="ai-panel-header">
                      <Sparkles size={24} />
                      <h4>AI-Powered Care Gap Analysis</h4>
                    </div>
                    
                    <div className="ai-summary">
                      <div className="summary-stat">
                        <span className="stat-label">Applicable Measures</span>
                        <span className="stat-value">{aiSuggestions.applicable_measures?.length || 0}</span>
                      </div>
                      <div className="summary-stat">
                        <span className="stat-label">Open Gaps</span>
                        <span className="stat-value red">{aiSuggestions.open_gaps_detected?.length || 0}</span>
                      </div>
                      <div className="summary-stat">
                        <span className="stat-label">Compliant</span>
                        <span className="stat-value green">{aiSuggestions.compliant_measures?.length || 0}</span>
                      </div>
                    </div>

                    {aiSuggestions.agent_responses?.care_gap_validator && (
                      <div className="ai-section validator">
                        <div className="section-header">
                          <div className="section-icon">📋</div>
                          <h5>Gap Validation Analysis</h5>
                        </div>
                        <div className="section-content">
                          {formatAgentResponse(aiSuggestions.agent_responses.care_gap_validator)}
                        </div>
                      </div>
                    )}
                    
                    {aiSuggestions.agent_responses?.outreach_advisor && (
                      <div className="ai-section outreach">
                        <div className="section-header">
                          <div className="section-icon">📞</div>
                          <h5>Outreach Strategy & Action Plan</h5>
                        </div>
                        <div className="section-content">
                          {formatAgentResponse(aiSuggestions.agent_responses.outreach_advisor)}
                        </div>
                      </div>
                    )}
                    
                    {aiSuggestions.agent_responses?.benefit_checker && (
                      <div className="ai-section benefits">
                        <div className="section-header">
                          <div className="section-icon">💰</div>
                          <h5>Benefit Coverage Information</h5>
                        </div>
                        <div className="section-content">
                          {formatAgentResponse(aiSuggestions.agent_responses.benefit_checker)}
                        </div>
                      </div>
                    )}

                    {aiSuggestions.open_gaps_detected && aiSuggestions.open_gaps_detected.length > 0 && (
                      <div className="gaps-table-section">
                        <h5>📊 Open Gaps Summary</h5>
                        <table className="gaps-summary-table">
                          <thead>
                            <tr>
                              <th>Measure</th>
                              <th>Status</th>
                              <th>Priority</th>
                            </tr>
                          </thead>
                          <tbody>
                            {aiSuggestions.open_gaps_detected.map((gap, idx) => (
                              <tr key={idx}>
                                <td><strong>{gap}</strong></td>
                                <td><span className="status-badge-table open">Open</span></td>
                                <td><span className="priority-badge high">High</span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {aiSuggestions.compliant_measures && aiSuggestions.compliant_measures.length > 0 && (
                      <div className="gaps-table-section">
                        <h5>✅ Compliant Measures</h5>
                        <table className="gaps-summary-table">
                          <thead>
                            <tr>
                              <th>Measure</th>
                              <th>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {aiSuggestions.compliant_measures.map((measure, idx) => (
                              <tr key={idx}>
                                <td><strong>{measure}</strong></td>
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
                      <button 
                        className="btn-primary"
                        onClick={() => handleBookAppointment(gap)}
                      >
                        <Calendar size={16} />
                        Book Appointment
                      </button>
                      <button className="btn-secondary">
                        View Guidelines
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'gaps' && (
          <div className="gaps-tab">
            {details?.open_gaps && details.open_gaps.length > 0 ? (
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
                      <button 
                        className="btn-primary"
                        onClick={() => handleBookAppointment(gap)}
                      >
                        <Calendar size={16} />
                        Schedule Service
                      </button>
                      <button className="btn-secondary" onClick={() => setChatOpen(true)}>
                        <MessageCircle size={16} />
                        Contact Member
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="no-data">
                <CheckCircle size={48} color="#10b981" />
                <h3>No Open Care Gaps</h3>
                <p>This member is compliant with all quality measures.</p>
              </div>
            )}

            {details?.closed_gaps && details.closed_gaps.length > 0 && (
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

        {activeTab === 'claims' && (
          <div className="claims-tab">
            {details?.claims && details.claims.length > 0 ? (
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
                    {details.claims.map((claim, index) => (
                      <tr key={index}>
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

        {activeTab === 'outreach' && (
          <div className="outreach-tab">
            {details?.outreach_history && details.outreach_history.length > 0 ? (
              <div className="outreach-timeline">
                {details.outreach_history.map(outreach => (
                  <div key={outreach.outreach_id} className="outreach-item">
                    <div className="outreach-icon">
                      <MessageCircle size={20} />
                    </div>
                    <div className="outreach-content">
                      <div className="outreach-header">
                        <h4>{outreach.channel}</h4>
                        <span className="outreach-date">{outreach.date}</span>
                      </div>
                      <p>Care Gap: {outreach.measure_name}</p>
                      <span className={`outreach-status ${outreach.status.toLowerCase()}`}>
                        {outreach.status}
                      </span>
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

      {chatOpen && (
        <div className="chat-modal">
          <div className="chat-container">
            <div className="chat-header">
              <h3>Chat with {member.name}</h3>
              <button className="close-chat" onClick={() => setChatOpen(false)}>
                <X size={20} />
              </button>
            </div>
            <div className="chat-messages">
              {chatMessages.length === 0 && (
                <div className="chat-empty">
                  <p>Start a conversation with AI Care Manager</p>
                  <p className="chat-hint">Ask about care gaps, outreach plans, or coverage</p>
                </div>
              )}
              {chatMessages.map(msg => (
                <div key={msg.id} className={`chat-message ${msg.sender}`}>
                  <div className="message-bubble">
                    {msg.sender === 'ai_agent' && (
                      <div className="ai-badge">
                        <Sparkles size={12} />
                        AI Care Manager
                      </div>
                    )}
                    <div className="message-content">
                      {formatAgentResponse(msg.text)}
                    </div>
                    <span className="message-time">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}
              {sendingMessage && (
                <div className="chat-message ai_agent">
                  <div className="message-bubble typing">
                    <Loader size={16} className="spinning" />
                    AI is analyzing...
                  </div>
                </div>
              )}
            </div>
            <div className="chat-input">
              <input
                type="text"
                placeholder="Type your message..."
                value={messageInput}
                onChange={(e) => setMessageInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
              />
              <button onClick={handleSendMessage}>
                <Send size={20} />
              </button>
            </div>
          </div>
        </div>
      )}

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

      {showComparison && (
        <MemberComparison 
          member={member}
          onClose={() => setShowComparison(false)}
        />
      )}
    </div>
  );
}

export default MemberDetails;
