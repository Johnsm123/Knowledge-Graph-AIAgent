import { useState, useEffect } from 'react';
import {
  X, Plus, Reply, Forward, Trash2, Send,
  Inbox, RefreshCw, Mail, Search, Star, Archive,
} from 'lucide-react';
import axios from 'axios';
import './EmailPanel.css';

import { API_BASE } from '../lib/apiBase';
const SENDER_ADDRESS = 'DoNotReply@06a748f5-010f-4c29-973a-d4dbe949e546.azurecomm.net';

export default function EmailPanel({ member, onClose }) {
  const [folder, setFolder]           = useState('sent');   // 'inbox' | 'sent'
  const [emails, setEmails]           = useState({ inbox: [], sent: [] });
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [loading, setLoading]         = useState(true);
  const [composing, setComposing]     = useState(false);
  const [sending, setSending]         = useState(false);
  const [compose, setCompose]         = useState({ to: '', subject: '', body: '' });
  const [sendError, setSendError]     = useState('');
  const [sendSuccess, setSendSuccess] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => { fetchEmails(); }, []);

  const fetchEmails = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/email/${member.member_id}`);
      const all = res.data.emails || [];
      setEmails({
        inbox: all.filter(e => e.direction === 'received'),
        sent:  all.filter(e => e.direction === 'sent'),
      });
    } catch (err) {
      console.error('Failed to fetch emails:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    if (!compose.to.trim() || !compose.subject.trim() || !compose.body.trim()) {
      setSendError('Please fill in all fields (To, Subject, Message).');
      return;
    }
    setSending(true);
    setSendError('');
    setSendSuccess(false);
    try {
      await axios.post(`${API_BASE}/email/${member.member_id}/send`, compose);
      setSendSuccess(true);
      setComposing(false);
      setCompose({ to: '', subject: '', body: '' });
      await fetchEmails();
      setFolder('sent');
    } catch (err) {
      setSendError(err.response?.data?.error || 'Failed to send. Please try again.');
    } finally {
      setSending(false);
    }
  };

  const handleSelectEmail = async (email) => {
    setSelectedEmail(email);
    if (!email.is_read) {
      try {
        await axios.patch(`${API_BASE}/email/mark-read/${email.email_id}`);
        setEmails(prev => ({
          ...prev,
          [folder]: prev[folder].map(e =>
            e.email_id === email.email_id ? { ...e, is_read: true } : e
          ),
        }));
      } catch {}
    }
  };

  const openReply = () => {
    if (!selectedEmail) return;
    setCompose({
      to: selectedEmail.from_email,
      subject: `Re: ${selectedEmail.subject}`,
      body: `\n\n\n--- Original Message ---\nFrom: ${selectedEmail.from_email}\nDate: ${formatDateFull(selectedEmail.timestamp)}\n\n${selectedEmail.body}`,
    });
    setComposing(true);
  };

  const openForward = () => {
    if (!selectedEmail) return;
    setCompose({
      to: '',
      subject: `Fwd: ${selectedEmail.subject}`,
      body: `\n\n--- Forwarded Message ---\nFrom: ${selectedEmail.from_email}\nTo: ${selectedEmail.to_email}\nDate: ${formatDateFull(selectedEmail.timestamp)}\nSubject: ${selectedEmail.subject}\n\n${selectedEmail.body}`,
    });
    setComposing(true);
  };

  const currentList = (emails[folder] || []).filter(e => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      e.subject?.toLowerCase().includes(q) ||
      e.body?.toLowerCase().includes(q) ||
      e.to_email?.toLowerCase().includes(q) ||
      e.from_email?.toLowerCase().includes(q)
    );
  });

  const unreadCount = emails.inbox.filter(e => !e.is_read).length;

  return (
    <div className="ep-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="ep-panel">

        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="ep-header">
          <div className="ep-header-left">
            <div className="ep-header-icon"><Mail size={18} /></div>
            <div>
              <span className="ep-header-title">Mail</span>
              <span className="ep-header-subtitle">{member.name} · {member.member_id}</span>
            </div>
          </div>
          <button className="ep-btn-icon ep-close" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </div>

        {/* ── Toolbar ────────────────────────────────────────────────── */}
        <div className="ep-toolbar">
          <button
            className="ep-toolbar-btn ep-toolbar-btn--primary"
            onClick={() => { setCompose({ to: member.email || '', subject: '', body: '' }); setComposing(true); setSendError(''); setSendSuccess(false); }}
          >
            <Plus size={14} /> New Email
          </button>
          <div className="ep-toolbar-divider" />
          <button className="ep-toolbar-btn" onClick={openReply} disabled={!selectedEmail} title="Reply">
            <Reply size={14} /> Reply
          </button>
          <button className="ep-toolbar-btn" onClick={openForward} disabled={!selectedEmail} title="Forward">
            <Forward size={14} /> Forward
          </button>
          <button className="ep-toolbar-btn" onClick={fetchEmails} title="Refresh">
            <RefreshCw size={14} /> Refresh
          </button>
          <div className="ep-sender-pill">
            <Mail size={11} />
            <span>{SENDER_ADDRESS}</span>
          </div>
        </div>

        {/* ── Three-pane body ─────────────────────────────────────────── */}
        <div className="ep-body">

          {/* Sidebar */}
          <div className="ep-sidebar">
            <div className="ep-sidebar-top">
              <div className="ep-sidebar-label">FOLDERS</div>
              <button
                className={`ep-folder ${folder === 'inbox' ? 'ep-folder--active' : ''}`}
                onClick={() => { setFolder('inbox'); setSelectedEmail(null); setSearchQuery(''); }}
              >
                <Inbox size={15} />
                <span>Inbox</span>
                {unreadCount > 0 && <span className="ep-badge ep-badge--blue">{unreadCount}</span>}
              </button>
              <button
                className={`ep-folder ${folder === 'sent' ? 'ep-folder--active' : ''}`}
                onClick={() => { setFolder('sent'); setSelectedEmail(null); setSearchQuery(''); }}
              >
                <Send size={15} />
                <span>Sent Items</span>
                {emails.sent.length > 0 && (
                  <span className="ep-badge ep-badge--gray">{emails.sent.length}</span>
                )}
              </button>
            </div>

            <div className="ep-sidebar-member">
              <div className="ep-member-ava">
                {member.name.split(' ').map(n => n[0]).join('').slice(0, 2)}
              </div>
              <div className="ep-member-info">
                <span className="ep-member-name">{member.name}</span>
                <span className="ep-member-id">{member.member_id}</span>
              </div>
            </div>
          </div>

          {/* Email list */}
          <div className="ep-list">
            <div className="ep-list-header">
              <span className="ep-list-title">
                {folder === 'inbox' ? 'Inbox' : 'Sent Items'}
              </span>
              <span className="ep-list-count">{currentList.length} item{currentList.length !== 1 ? 's' : ''}</span>
            </div>

            <div className="ep-search-wrap">
              <Search size={14} className="ep-search-icon" />
              <input
                className="ep-search"
                type="text"
                placeholder="Search emails…"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>

            {loading ? (
              <div className="ep-center"><div className="ep-spinner" /></div>
            ) : currentList.length === 0 ? (
              <div className="ep-empty">
                {folder === 'inbox' ? <Inbox size={36} /> : <Send size={36} />}
                <p>{folder === 'inbox' ? 'No received emails yet' : 'No sent emails yet'}</p>
                <span>
                  {folder === 'inbox'
                    ? `Member replies will appear here`
                    : `Click "New Email" to compose`}
                </span>
              </div>
            ) : (
              <div className="ep-list-items">
                {currentList.map(email => (
                  <div
                    key={email.email_id}
                    className={`ep-list-item ${selectedEmail?.email_id === email.email_id ? 'ep-list-item--selected' : ''} ${!email.is_read && folder === 'inbox' ? 'ep-list-item--unread' : ''}`}
                    onClick={() => handleSelectEmail(email)}
                  >
                    <div className="ep-list-ava">
                      {(folder === 'sent'
                        ? email.to_email?.[0]
                        : email.from_email?.[0] || '?'
                      ).toUpperCase()}
                    </div>
                    <div className="ep-list-content">
                      <div className="ep-list-row1">
                        <span className="ep-list-name">
                          {folder === 'sent'
                            ? `To: ${email.to_email}`
                            : email.from_email}
                        </span>
                        <span className="ep-list-time">{formatDateShort(email.timestamp)}</span>
                      </div>
                      <div className="ep-list-subject">{email.subject}</div>
                      <div className="ep-list-preview">{email.body?.slice(0, 90)}…</div>
                    </div>
                    {!email.is_read && folder === 'inbox' && <div className="ep-unread-dot" />}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Reading pane */}
          <div className="ep-reading">
            {selectedEmail ? (
              <div className="ep-reading-content">
                <div className="ep-reading-header">
                  <h2 className="ep-reading-subject">{selectedEmail.subject}</h2>
                  <div className="ep-reading-meta">
                    <MetaRow label="From" value={selectedEmail.from_email} />
                    <MetaRow label="To"   value={selectedEmail.to_email} />
                    <MetaRow label="Date" value={formatDateFull(selectedEmail.timestamp)} />
                  </div>
                  <div className="ep-reading-actions">
                    <button className="ep-reading-btn" onClick={openReply}><Reply size={13} /> Reply</button>
                    <button className="ep-reading-btn" onClick={openForward}><Forward size={13} /> Forward</button>
                  </div>
                </div>
                <div className="ep-reading-body">
                  <pre className="ep-reading-text">{selectedEmail.body}</pre>
                </div>
              </div>
            ) : (
              <div className="ep-reading-empty">
                <Mail size={52} />
                <p>Select a message to read</p>
                <span>Click any email in the list to preview it here</span>
              </div>
            )}
          </div>
        </div>

        {/* ── Compose modal ──────────────────────────────────────────── */}
        {composing && (
          <div className="ep-compose-overlay">
            <div className="ep-compose">
              <div className="ep-compose-header">
                <span>New Message</span>
                <button onClick={() => { setComposing(false); setSendError(''); }}>
                  <X size={15} />
                </button>
              </div>

              <div className="ep-compose-fields">
                <ComposeField label="From">
                  <input type="text" value={SENDER_ADDRESS} disabled className="ep-field-input ep-field-input--disabled" />
                </ComposeField>
                <ComposeField label="To">
                  <input
                    type="email"
                    placeholder="recipient@example.com"
                    value={compose.to}
                    onChange={e => setCompose(p => ({ ...p, to: e.target.value }))}
                    className="ep-field-input"
                    autoFocus
                  />
                </ComposeField>
                <ComposeField label="Subject">
                  <input
                    type="text"
                    placeholder="Subject"
                    value={compose.subject}
                    onChange={e => setCompose(p => ({ ...p, subject: e.target.value }))}
                    className="ep-field-input"
                  />
                </ComposeField>
              </div>

              <textarea
                className="ep-compose-body"
                placeholder={`Write your message to ${member.name}…`}
                value={compose.body}
                onChange={e => setCompose(p => ({ ...p, body: e.target.value }))}
              />

              {sendError && <div className="ep-compose-error">{sendError}</div>}

              <div className="ep-compose-footer">
                <button
                  className="ep-compose-send-btn"
                  onClick={handleSend}
                  disabled={sending}
                >
                  {sending ? (
                    <><div className="ep-mini-spin" /> Sending…</>
                  ) : (
                    <><Send size={14} /> Send</>
                  )}
                </button>
                <button
                  className="ep-compose-discard-btn"
                  onClick={() => { setComposing(false); setSendError(''); }}
                >
                  <Trash2 size={14} /> Discard
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Send success toast */}
        {sendSuccess && (
          <div className="ep-toast" onAnimationEnd={() => setSendSuccess(false)}>
            Email sent successfully
          </div>
        )}
      </div>
    </div>
  );
}

function MetaRow({ label, value }) {
  return (
    <div className="ep-meta-row">
      <span className="ep-meta-label">{label}</span>
      <span className="ep-meta-value">{value}</span>
    </div>
  );
}

function ComposeField({ label, children }) {
  return (
    <div className="ep-compose-field">
      <label className="ep-compose-label">{label}</label>
      {children}
    </div>
  );
}

function formatDateShort(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  const diffDays = Math.floor((now - d) / 86400000);
  if (diffDays < 7) {
    return d.toLocaleDateString([], { weekday: 'short' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatDateFull(ts) {
  if (!ts) return '';
  return new Date(ts).toLocaleString([], {
    weekday: 'short', year: 'numeric', month: 'short',
    day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
