import { useState, useEffect } from 'react';
import { ArrowLeft, Phone, Mail, Calendar, FileText, MessageCircle, Send, X } from 'lucide-react';
import axios from 'axios';
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
    setMessageInput('');

    try {
      await axios.post(`${API_BASE}/chat/send`, {
        member_id: member.member_id,
        message: messageInput,
        sender: 'care_manager'
      });

      setTimeout(() => {
        const autoReply = {
          id: Date.now() + 1,
          sender: 'member',
          text: 'Thank you for reaching out. I will review this information.',
          timestamp: new Date().toISOString()
        };
        setChatMessages(prev => [...prev, autoReply]);
      }, 2000);
    } catch (error) {
      console.error('Error sending message:', error);
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
            <span>{details?.profile.gender === 'M' ? 'Male' : 'Female'}</span>
            <span>•</span>
            <span>DOB: {details?.profile.dob}</span>
          </div>
        </div>
        <div className="profile-actions">
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
                <h3>Open Care Gaps - Action Required</h3>
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
                  <p>Start a conversation with the member</p>
                </div>
              )}
              {chatMessages.map(msg => (
                <div key={msg.id} className={`chat-message ${msg.sender}`}>
                  <div className="message-bubble">
                    <p>{msg.text}</p>
                    <span className="message-time">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}
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
    </div>
  );
}

export default MemberDetails;
