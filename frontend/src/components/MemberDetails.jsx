import { useState, useEffect, useRef, useMemo } from "react";
import {
  ArrowLeft,
  Mail,
  Calendar,
  FileText,
  MessageCircle,
  Send,
  X,
  Sparkles,
  Loader,
  GitCompare,
  Bot,
  CheckCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import axios from "axios";
import MemberComparison from "./MemberComparison";
import EmailPanel from "./EmailPanel";
import Neo4jGraph from "./Neo4jGraph";
import { useRealtimeEvents } from "../hooks/useRealtimeEvents";
import "./MemberDetails.css";

import { API_BASE } from "../lib/apiBase";

// Defined outside MemberDetails to keep a stable reference across re-renders.
// react-markdown v10 removed the `className` prop — use a wrapper div instead.
function MarkdownContent({ text, className = "" }) {
  if (!text) return null;
  return (
    <div className={`agent-markdown ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text.trim()}</ReactMarkdown>
    </div>
  );
}

// ── Per-agent structured renderers ───────────────────────────────────────────

// Parses lines into sections split by blank lines or header lines
function parseAgentSections(text) {
  if (!text) return [];
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const sections = [];
  let current = { heading: "", lines: [] };
  lines.forEach((line) => {
    const isHeading =
      /^[A-Z][A-Z\s\/\-&]{3,}$/.test(line) ||
      /^#+\s/.test(line) ||
      /^\*\*[^*]+\*\*$/.test(line) ||
      /^[A-Z][^a-z]{0,2}[A-Z].*:$/.test(line);
    if (isHeading) {
      if (current.lines.length) sections.push({ ...current });
      current = {
        heading: line
          .replace(/^#+\s*/, "")
          .replace(/\*\*/g, "")
          .replace(/:$/, ""),
        lines: [],
      };
    } else {
      current.lines.push(line);
    }
  });
  if (current.lines.length || current.heading) sections.push(current);
  return sections;
}

// Renders a single line — bold, code, bullet
function AgentLine({ line }) {
  // Table row detection: | col | col |
  if (line.startsWith("|")) return null; // handled by table parser
  // Bullet
  const isBullet = /^[-•*]\s/.test(line);
  const text = line
    .replace(/^[-•*]\s/, "")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  if (isBullet) {
    return (
      <div className="ap-bullet">
        <span className="ap-bullet-dot" />
        <span dangerouslySetInnerHTML={{ __html: text }} />
      </div>
    );
  }
  // Key: value line
  const kvMatch = line.match(/^([A-Za-z][\w\s\/\-()]+):\s*(.+)$/);
  if (kvMatch) {
    return (
      <div className="ap-kv">
        <span className="ap-kv-key">{kvMatch[1]}</span>
        <span
          className="ap-kv-val"
          dangerouslySetInnerHTML={{
            __html: kvMatch[2]
              .replace(/`([^`]+)`/g, "<code>$1</code>")
              .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>"),
          }}
        />
      </div>
    );
  }
  return <p className="ap-para" dangerouslySetInnerHTML={{ __html: text }} />;
}

// Parse markdown table from lines
function parseTable(lines) {
  const tableLines = lines.filter((l) => l.startsWith("|"));
  if (tableLines.length < 2) return null;
  const headers = tableLines[0]
    .split("|")
    .map((h) => h.trim())
    .filter(Boolean);
  const rows = tableLines.slice(2).map((r) =>
    r
      .split("|")
      .map((c) => c.trim())
      .filter(Boolean),
  );
  return { headers, rows };
}

function AgentTable({ headers, rows }) {
  return (
    <div className="ap-table-wrap">
      <table className="ap-table">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i}>{h.replace(/\*\*/g, "")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td
                  key={j}
                  dangerouslySetInnerHTML={{
                    __html: cell
                      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
                      .replace(/`([^`]+)`/g, "<code>$1</code>")
                      .replace(
                        /OPEN/g,
                        '<span class="ap-badge ap-badge--open">OPEN</span>',
                      )
                      .replace(
                        /CLOSED/g,
                        '<span class="ap-badge ap-badge--closed">CLOSED</span>',
                      )
                      .replace(
                        /COMPLIANT/g,
                        '<span class="ap-badge ap-badge--compliant">COMPLIANT</span>',
                      )
                      .replace(
                        /NON.COMPLIANT/g,
                        '<span class="ap-badge ap-badge--open">NON-COMPLIANT</span>',
                      )
                      .replace(
                        /EXCLUDED/g,
                        '<span class="ap-badge ap-badge--excluded">EXCLUDED</span>',
                      )
                      .replace(
                        /NOT EXCLUDED/g,
                        '<span class="ap-badge ap-badge--compliant">NOT EXCLUDED</span>',
                      )
                      .replace(
                        /High/g,
                        '<span class="ap-badge ap-badge--high">High</span>',
                      )
                      .replace(
                        /Medium/g,
                        '<span class="ap-badge ap-badge--medium">Medium</span>',
                      ),
                  }}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Main structured agent content renderer
function AgentContent({ agentName, text }) {
  if (!text) return null;
  const lines = text.split("\n").map((l) => l.trim());

  // Check for tables
  const hasTable = lines.some((l) => l.startsWith("|"));
  const table = hasTable ? parseTable(lines) : null;
  const nonTableLines = lines.filter(
    (l) => !l.startsWith("|") && !/^[-|]+$/.test(l),
  );

  const sections = parseAgentSections(nonTableLines.join("\n"));

  // Agent-specific accent colors
  const accentMap = {
    patient_analyst: "#2F78C4",
    hedis_measure_agent: "#7373D8",
    exclusion_agent: "#E9C71D",
    code_validator: "#05819B",
    care_gap_agent: "#B81F2D",
    recommendation_agent: "#2DB81F",
  };
  const accent = accentMap[agentName] || "#53565A";

  return (
    <div className="ap-content">
      {sections.map((sec, si) => (
        <div key={si} className="ap-section">
          {sec.heading && (
            <div
              className="ap-section-heading"
              style={{ borderLeftColor: accent }}
            >
              {sec.heading}
            </div>
          )}
          <div className="ap-section-body">
            {sec.lines.map((line, li) => (
              <AgentLine key={li} line={line} />
            ))}
          </div>
        </div>
      ))}
      {table && <AgentTable headers={table.headers} rows={table.rows} />}
    </div>
  );
}

// Agent panel configuration — order must match AGENT_ORDER in care_gap_agents.py
const AGENT_CONFIG = {
  patient_analyst: {
    icon: "👤",
    label: "Patient Profile Analysis",
    color: "#2F78C4",
  },
  hedis_measure_agent: {
    icon: "📏",
    label: "HEDIS Measures Review",
    color: "#7373D8",
  },
  exclusion_agent: { icon: "🚫", label: "Exclusion Check", color: "#E9C71D" },
  code_validator: {
    icon: "✅",
    label: "CPT Code Validation",
    color: "#05819B",
  },
  care_gap_agent: { icon: "📋", label: "Care Gap Report", color: "#B81F2D" },
  recommendation_agent: {
    icon: "💡",
    label: "Recommendations & Outreach",
    color: "#2DB81F",
  },
};
const AGENT_ORDER = Object.keys(AGENT_CONFIG);

function MemberDetails({ member, onBack }) {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");

  // AI suggestions state
  const [aiMetadata, setAiMetadata] = useState(null); // metadata event payload
  const [agentStreams, setAgentStreams] = useState({}); // { agentName: content }
  const [streamingAgent, setStreamingAgent] = useState(null); // currently running agent name
  const [loadingAI, setLoadingAI] = useState(false);
  const [aiDone, setAiDone] = useState(false);
  const eventSourceRef = useRef(null);

  // Chat state
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [messageInput, setMessageInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatBottomRef = useRef(null);

  // Email panel state
  const [emailPanelOpen, setEmailPanelOpen] = useState(false);

  // Compliance toast state
  const [compliantToast, setCompliantToast] = useState(false);

  // Other UI state
  const [showAppointmentModal, setShowAppointmentModal] = useState(false);
  const [selectedGap, setSelectedGap] = useState(null);
  const [showComparison, setShowComparison] = useState(false);

  // Appointment booking state
  const [appointmentDate, setAppointmentDate] = useState("");
  const [appointmentTime, setAppointmentTime] = useState("09:00");
  const [bookingLoading, setBookingLoading] = useState(false);
  const [bookingError, setBookingError] = useState("");
  // keyed by care_gap_id → { appointment_id, lab_number, lab_specialist, ... }
  const [bookings, setBookings] = useState({});
  const [viewBooking, setViewBooking] = useState(null); // booking object being viewed
  const [completingGap, setCompletingGap] = useState(false);
  const [completedGaps, setCompletedGaps] = useState(new Set()); // care_gap_ids closed this session
  const [completeError, setCompleteError] = useState("");
  const [forceClosing, setForceClosing] = useState(false);

  // Persona graph state (reference DB)
  const [personaGraph, setPersonaGraph] = useState(null);
  const [personaLoading, setPersonaLoading] = useState(false);

  useEffect(() => {
    if (member) {
      fetchMemberDetails();
      fetchPersonaGraph();
    }
  }, [member]);

  useRealtimeEvents({
    appointment_booked: (payload) => {
      if (payload?.member_id === member?.member_id) {
        fetchMemberDetails();
        fetchPersonaGraph();
      }
    },
    profile_updated: (payload) => {
      if (payload?.member_id === member?.member_id) {
        fetchMemberDetails();
        fetchPersonaGraph();
      }
    },
    care_gap_updated: (payload) => {
      if (payload?.member_id === member?.member_id) {
        fetchMemberDetails();
        fetchPersonaGraph();
      }
    },
  });
  // keep original useEffect deps intact below; no-op body preserves original semantics
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [member]);

  // Auto-scroll chat to bottom on new messages
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, chatLoading]);

  // Inject greeting when chat first opens
  useEffect(() => {
    if (chatOpen && chatMessages.length === 0 && details) {
      const openGapCount = details.open_gaps?.length || 0;
      setChatMessages([
        {
          id: Date.now(),
          role: "assistant",
          text: `Hi! I'm your AI care manager assistant for **${member.name}**.\n\nI have full access to their profile, ${openGapCount} open care gap${openGapCount !== 1 ? "s" : ""}, and claims history. Ask me anything about this member — gaps, outreach strategy, clinical guidance, or coverage.`,
          timestamp: new Date().toISOString(),
        },
      ]);
    }
  }, [chatOpen]);

  const fetchMemberDetails = async () => {
    try {
      setLoading(true);
      const response = await axios.get(
        `${API_BASE}/members/${member.member_id}/details`,
      );
      const data = response.data;
      setDetails(data);

      // Restore booking state from DB appointments so refresh doesn't lose state
      if (data.appointments?.length > 0) {
        const restoredBookings = {};
        const restoredCompleted = new Set();

        data.appointments.forEach((appt) => {
          // Use stored care_gap_id if available, else match by measure_id
          const care_gap_id =
            appt.care_gap_id ||
            data.open_gaps?.find((g) => g.measure_id === appt.measure_id)
              ?.care_gap_id ||
            data.closed_gaps?.find((g) => g.measure_id === appt.measure_id)
              ?.care_gap_id ||
            `AUTO-${member.member_id}-${appt.measure_id}`;

          restoredBookings[care_gap_id] = {
            appointment_id: appt.appointment_id,
            measure_name: appt.screening_name || appt.measure_id,
            care_gap_id,
            appointment_date: appt.appointment_date,
            appointment_time: appt.appointment_time,
            lab_number: appt.lab_number,
            lab_location: appt.lab_location,
            lab_specialist: appt.lab_specialist,
            cpt_codes: appt.cpt_codes,
            icd_codes: appt.icd_codes,
            status: appt.status,
            member_email: appt.member_email,
            member_name: appt.member_name,
            plan_id: appt.plan_id,
            insurance_type: appt.insurance_type,
            pcp_name: appt.pcp_name,
            email_sent: !!appt.member_email,
          };

          if (appt.status === "Completed") {
            restoredCompleted.add(care_gap_id);
          }
        });

        setBookings(restoredBookings);
        setCompletedGaps(restoredCompleted);
      }
    } catch (error) {
      console.error("Error fetching member details:", error);
    } finally {
      setLoading(false);
    }
  };

  // ── Fetch persona graph from reference DB ──────────────────────────────────
  const fetchPersonaGraph = async () => {
    try {
      setPersonaLoading(true);
      const res = await axios.get(
        `${API_BASE}/reference/member/${member.member_id}/personas`,
      );
      setPersonaGraph(res.data);
    } catch (err) {
      console.error("Persona graph fetch error:", err);
    } finally {
      setPersonaLoading(false);
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

    const es = new EventSource(
      `${API_BASE}/care-gaps/validate/${member.member_id}/stream`,
    );
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const { type, payload } = JSON.parse(event.data);

        if (type === "metadata") {
          setAiMetadata(payload);
          setLoadingAI(false); // counts are visible — spinner off
        } else if (type === "agent_start") {
          setStreamingAgent(payload.agent);
        } else if (type === "agent_done") {
          setAgentStreams((prev) => ({
            ...prev,
            [payload.agent]: payload.content,
          }));
          setStreamingAgent(null);
        } else if (type === "complete") {
          setAiDone(true);
          setStreamingAgent(null);
          es.close();
          // Auto-refresh graph after AI analysis + outreach
          fetchMemberDetails();
          fetchPersonaGraph();
        } else if (type === "error") {
          console.error("SSE error:", payload.message);
          setLoadingAI(false);
          es.close();
        }
      } catch (e) {
        console.error("SSE parse error:", e);
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
    setMessageInput("");

    const userMsg = {
      id: Date.now(),
      role: "user",
      text: userText,
      timestamp: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setChatLoading(true);

    try {
      // Build history from existing messages (exclude the greeting for brevity)
      const history = chatMessages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role, content: m.text }));

      const response = await axios.post(
        `${API_BASE}/chat/member/${member.member_id}`,
        {
          message: userText,
          history,
        },
      );

      setChatMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "assistant",
          text: response.data.reply,
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (error) {
      setChatMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: "assistant",
          text: "Sorry, I encountered an error connecting to the AI. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
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
        className={`agent-stream-panel ${isRunning ? "running" : "done"}`}
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
              <span
                style={{ marginLeft: 6, fontSize: "0.75rem", color: "#53565A" }}
              >
                Analyzing…
              </span>
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
            {agentName === "recommendation_agent" ? (
              <MarkdownContent text={content} />
            ) : (
              <AgentContent agentName={agentName} text={content} />
            )}
          </div>
        )}
      </div>
    );
  };

  const handleBookAppointment = (gap) => {
    setSelectedGap(gap);
    setAppointmentDate("");
    setAppointmentTime("09:00");
    setBookingError("");
    setShowAppointmentModal(true);
  };

  const confirmAppointment = async () => {
    if (!appointmentDate) {
      setBookingError("Please select a date.");
      return;
    }
    if (!appointmentTime) {
      setBookingError("Please select a time.");
      return;
    }
    setBookingLoading(true);
    setBookingError("");
    try {
      const res = await axios.post(`${API_BASE}/appointments/book`, {
        member_id: member.member_id,
        measure_id: selectedGap.measure_id,
        measure_name: selectedGap.measure_name,
        appointment_date: appointmentDate,
        appointment_time: appointmentTime,
        provider_id: details.profile.pcp_id || "",
        care_gap_id: selectedGap.care_gap_id,
      });
      if (res.data.status === "success") {
        setBookings((prev) => ({
          ...prev,
          [selectedGap.care_gap_id]: {
            ...res.data,
            measure_name: selectedGap.measure_name,
            care_gap_id: selectedGap.care_gap_id,
            member_name: member.name,
            plan_id: details.profile.plan_id,
            insurance_type: details.profile.insurance_type || "Commercial",
            pcp_name: details.profile.pcp_name,
          },
        }));
        setShowAppointmentModal(false);
        setSelectedGap(null);
        // Auto-refresh graph and timeline after booking
        fetchMemberDetails();
        fetchPersonaGraph();
      } else {
        setBookingError(res.data.error || "Booking failed. Please try again.");
      }
    } catch (err) {
      setBookingError(
        err.response?.data?.error || "Network error. Please try again.",
      );
    } finally {
      setBookingLoading(false);
    }
  };

  const handleCompleteScreening = async (booking) => {
    setCompletingGap(true);
    setCompleteError("");
    try {
      const res = await axios.post(
        `${API_BASE}/appointments/${booking.appointment_id}/complete`,
        { care_gap_id: booking.care_gap_id },
      );
      if (res.data.status === "success") {
        const claimId = res.data.claim_id;
        setViewBooking((prev) => ({
          ...prev,
          claim_id: claimId,
          cpt_codes: res.data.cpt_codes || prev.cpt_codes,
          icd_codes: res.data.icd_codes || prev.icd_codes,
          status: "Completed",
        }));
        setBookings((prev) => ({
          ...prev,
          [booking.care_gap_id]: {
            ...prev[booking.care_gap_id],
            claim_id: claimId,
            status: "Completed",
          },
        }));
        setCompletedGaps((prev) => new Set([...prev, booking.care_gap_id]));
        // Refresh member details and persona graph to reflect closed gap
        await fetchMemberDetails();
        await fetchPersonaGraph();
        // Show compliance banner if all gaps are now closed
        if (res.data.is_now_compliant) {
          setCompliantToast(true);
          setTimeout(() => setCompliantToast(false), 6000);
        }
      } else {
        setCompleteError(
          res.data.error || "Completion failed. Please try again.",
        );
      }
    } catch (err) {
      console.error("Complete screening error:", err);
      setCompleteError(
        err.response?.data?.error || "Network error. Please try again.",
      );
    } finally {
      setCompletingGap(false);
    }
  };

  const handleForceClose = async (booking) => {
    setForceClosing(true);
    setCompleteError("");
    try {
      const res = await axios.post(
        `${API_BASE}/appointments/${booking.appointment_id}/force-close`,
        { care_gap_id: booking.care_gap_id },
      );
      if (res.data.status === "success") {
        const claimId = res.data.claim_id;
        setViewBooking((prev) => ({
          ...prev,
          claim_id: claimId,
          cpt_codes: res.data.cpt_codes || prev.cpt_codes,
          icd_codes: res.data.icd_codes || prev.icd_codes,
          status: "Completed",
        }));
        setBookings((prev) => ({
          ...prev,
          [booking.care_gap_id]: {
            ...prev[booking.care_gap_id],
            claim_id: claimId,
            status: "Completed",
          },
        }));
        setCompletedGaps((prev) => new Set([...prev, booking.care_gap_id]));
        await fetchMemberDetails();
        await fetchPersonaGraph();
        if (res.data.is_now_compliant) {
          setCompliantToast(true);
          setTimeout(() => setCompliantToast(false), 6000);
        }
      } else {
        setCompleteError(res.data.error || "Force close failed.");
      }
    } catch (err) {
      console.error("Force close error:", err);
      setCompleteError(err.response?.data?.error || "Network error.");
    } finally {
      setForceClosing(false);
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
      {/* ── Compliance Toast ─────────────────────────────────────────────── */}
      {compliantToast && (
        <div className="compliant-toast">
          <CheckCircle size={20} />
          <div>
            <strong>{member.name} is now fully compliant!</strong>
            <span> All care gaps have been closed. Outreach recorded.</span>
          </div>
          <button
            className="toast-close"
            onClick={() => setCompliantToast(false)}
          >
            ✕
          </button>
        </div>
      )}

      <div className="details-header">
        <button className="back-button" onClick={onBack}>
          <ArrowLeft size={20} />
          Back to Dashboard
        </button>
      </div>

      <div className="member-profile-card">
        <div className="profile-avatar-large">
          {member.name
            .split(" ")
            .map((n) => n[0])
            .join("")}
        </div>
        <div className="profile-info">
          <h1>{member.name}</h1>
          <p className="member-id-large">{member.member_id}</p>
          <div className="profile-meta">
            <span>{details?.profile.age_str}</span>
            <span>•</span>
            <span>
              {(() => {
                const g = (details?.profile.gender || "").trim();
                if (!g) return "";
                const u = g.toUpperCase();
                if (u === "M" || u === "MALE") return "Male";
                if (u === "F" || u === "FEMALE") return "Female";
                return g;
              })()}
            </span>
          </div>
        </div>
        <div className="profile-actions">
          <button className="action-btn" onClick={() => setChatOpen(true)}>
            <Bot size={18} />
            AI Chat
          </button>
          <button
            className="action-btn"
            onClick={() => setEmailPanelOpen(true)}
          >
            <Mail size={18} />
            Email
          </button>
        </div>
      </div>

      <div className="details-tabs">
        <button
          className={activeTab === "overview" ? "active" : ""}
          onClick={() => setActiveTab("overview")}
        >
          Overview
        </button>
        <button
          className={activeTab === "patient-record" ? "active" : ""}
          onClick={() => setActiveTab("patient-record")}
        >
          Patient Record
        </button>
        <button
          className={activeTab === "appointments" ? "active" : ""}
          onClick={() => setActiveTab("appointments")}
        >
          Appointments ({details?.appointments?.length || 0})
        </button>
        <button
          className={activeTab === "outreach" ? "active" : ""}
          onClick={() => setActiveTab("outreach")}
        >
          Outreach History
        </button>
        <button
          className="refresh-btn"
          onClick={fetchMemberDetails}
          title="Refresh member data (shows portal-booked appointments)"
        >
          &#x21bb; Refresh
        </button>
      </div>

      <div className="details-content">
        {/* ── OVERVIEW TAB ───────────────────────────────────────────────── */}
        {activeTab === "overview" && (
          <div className="overview-tab">
            <div className="info-grid">
              <div className="info-card">
                <h3>Plan Information</h3>
                {(() => {
                  const ins = (
                    details?.profile?.insurance_type || "HMO"
                  ).toString();
                  const insTag =
                    ins
                      .replace(/[^A-Za-z]/g, "")
                      .slice(0, 3)
                      .toUpperCase() || "HMO";
                  const idTail = (member?.member_id || "M0000")
                    .replace(/^M/i, "")
                    .padStart(4, "0")
                    .slice(-4);
                  const planId =
                    details?.profile?.plan_id || `PLN-${insTag}-${idTail}`;
                  const copay =
                    (details?.profile?.copay ?? null) === null
                      ? 0
                      : details.profile.copay;
                  const recos = (details?.open_gaps || [])
                    .map((g) => g.measure_name)
                    .filter(Boolean)
                    .slice(0, 3);
                  const preventive =
                    details?.profile?.preventive_covered ||
                    (recos.length > 0
                      ? `100% covered: ${recos.join(", ")}`
                      : "Annual wellness, screenings & immunizations covered at 100%");
                  return (
                    <>
                      <div className="info-row">
                        <span className="label">Plan ID:</span>
                        <span className="value">{planId}</span>
                      </div>
                      <div className="info-row">
                        <span className="label">Copay:</span>
                        <span className="value">${copay}</span>
                      </div>
                      <div className="info-row">
                        <span className="label">Preventive Covered:</span>
                        <span className="value">{preventive}</span>
                      </div>
                    </>
                  );
                })()}
              </div>

              <div className="info-card">
                <h3>Primary Care Provider</h3>
                <div className="info-row">
                  <span className="label">Name:</span>
                  <span className="value">{details?.profile.pcp_name}</span>
                </div>
                <div className="info-row">
                  <span className="label">Specialty:</span>
                  <span className="value">
                    {details?.profile.pcp_specialty}
                  </span>
                </div>
                <div className="info-row">
                  <span className="label">Network:</span>
                  <span className="value">
                    {details?.profile.pcp_network_status}
                  </span>
                </div>
              </div>

              <div className="info-card">
                <h3>Care Gap Summary</h3>
                <div className="info-row">
                  <span className="label">Open Gaps:</span>
                  <span className="value highlight-red">
                    {details?.open_gaps?.length || 0}
                  </span>
                </div>
                <div className="info-row">
                  <span className="label">Closed Gaps:</span>
                  <span className="value highlight-green">
                    {details?.closed_gaps?.length || 0}
                  </span>
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
                      ? "Open Care Gaps — Action Required"
                      : "Care Gap Analysis"}
                  </h3>
                </div>

                {/* ── AI Streaming Panel ───────────────────────────────── */}
                {(aiMetadata || loadingAI) && (
                  <div className="ai-suggestions-panel">
                    <div className="ai-panel-header">
                      <Sparkles size={24} />
                      <h4>AI-Powered Care Gap Analysis</h4>
                      {!aiDone && streamingAgent && (
                        <span className="ai-status-badge">
                          <Loader
                            size={12}
                            className="spinning"
                            style={{ marginRight: 4 }}
                          />
                          Agent {AGENT_ORDER.indexOf(streamingAgent) + 1} of 6
                          running…
                        </span>
                      )}
                      {aiDone && (
                        <span className="ai-done-badge">
                          ✓ Analysis complete
                        </span>
                      )}
                    </div>

                    {/* Summary counts — show as soon as metadata arrives */}
                    {aiMetadata && (
                      <div className="ai-summary">
                        <div className="summary-stat">
                          <span className="stat-label">
                            Applicable Measures
                          </span>
                          <span className="stat-value">
                            {aiMetadata.applicable_measures?.length || 0}
                          </span>
                        </div>
                        <div className="summary-stat">
                          <span className="stat-label">Open Gaps</span>
                          <span className="stat-value red">
                            {aiMetadata.open_gaps_detected?.length || 0}
                          </span>
                        </div>
                        <div className="summary-stat">
                          <span className="stat-label">Compliant</span>
                          <span className="stat-value green">
                            {aiMetadata.compliant_measures?.length || 0}
                          </span>
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
                              className={`progress-step ${done ? "done" : running ? "running" : "pending"}`}
                              title={AGENT_CONFIG[name].label}
                            >
                              <span className="progress-step-icon">
                                {AGENT_CONFIG[name].icon}
                              </span>
                              <span className="progress-step-num">
                                {idx + 1}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Agent panels — only show recommendation agent output */}
                    <div className="agent-streams-container">
                      {renderAgentPanel("recommendation_agent")}
                    </div>

                    {/* Gap + compliant tables once we have metadata */}
                    {aiMetadata?.open_gaps_detected?.length > 0 && (
                      <div className="gaps-table-section">
                        <h5>📊 Open Gaps Detected</h5>
                        <table className="gaps-summary-table">
                          <thead>
                            <tr>
                              <th>Measure</th>
                              <th>Status</th>
                              <th>Priority</th>
                            </tr>
                          </thead>
                          <tbody>
                            {aiMetadata.open_gaps_detected.map((g, i) => (
                              <tr key={i}>
                                <td>
                                  <strong>{g}</strong>
                                </td>
                                <td>
                                  <span className="status-badge-table open">
                                    Open
                                  </span>
                                </td>
                                <td>
                                  <span className="priority-badge high">
                                    High
                                  </span>
                                </td>
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
                            <tr>
                              <th>Measure</th>
                              <th>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {aiMetadata.compliant_measures.map((m, i) => (
                              <tr key={i}>
                                <td>
                                  <strong>{m}</strong>
                                </td>
                                <td>
                                  <span className="status-badge-table compliant">
                                    Compliant
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                {/* Gap cards — only when gaps exist */}
                {details.open_gaps?.length > 0
                  ? details.open_gaps.map((gap) => {
                      const booking = bookings[gap.care_gap_id];
                      const isClosed = completedGaps.has(gap.care_gap_id);
                      return (
                        <div
                          key={gap.care_gap_id}
                          className={`quick-gap-card ${isClosed ? "quick-gap-card--closed" : ""}`}
                        >
                          <div className="gap-header">
                            <h4 style={{ flex: 1 }}>{gap.measure_name}</h4>
                            {(() => {
                              // tone: red = not booked, yellow = needs rebooking, green = booked or closed
                              let tone = "red";
                              let label = "Status: Not Booked";
                              if (isClosed) {
                                tone = "green";
                                label = "Status: Closed";
                              } else if (booking) {
                                const s = booking.status;
                                if (s === "Completed") {
                                  tone = "green";
                                  label = "Status: Completed";
                                } else if (
                                  s === "Cancelled_NoShow" ||
                                  s === "No Show"
                                ) {
                                  tone = "yellow";
                                  label = "Status: Needs Rebooking";
                                } else if (s === "Cancelled") {
                                  tone = "yellow";
                                  label = "Status: Cancelled";
                                } else {
                                  tone = "green";
                                  label = "Status: Booked";
                                }
                              }
                              const toneStyle = {
                                red: {
                                  background: "#B81F2D",
                                  color: "#fff",
                                  borderColor: "#B81F2D",
                                },
                                yellow: {
                                  background: "#F59E0B",
                                  color: "#fff",
                                  borderColor: "#F59E0B",
                                },
                                green: {
                                  background: "#10B981",
                                  color: "#fff",
                                  borderColor: "#10B981",
                                },
                              }[tone];
                              return (
                                <button
                                  className="btn-view-booking"
                                  style={{ ...toneStyle, marginLeft: "auto" }}
                                  onClick={() =>
                                    setViewBooking(
                                      booking || {
                                        care_gap_id: gap.care_gap_id,
                                        measure_id: gap.measure_id,
                                        screening_name: gap.measure_name,
                                        status: isClosed
                                          ? "Completed"
                                          : "Not Booked",
                                      },
                                    )
                                  }
                                >
                                  <Calendar size={16} />
                                  {label}
                                </button>
                              );
                            })()}
                            <span
                              className="gap-badge"
                              style={{ marginLeft: 8 }}
                            >
                              {gap.measure_id}
                            </span>
                          </div>
                        </div>
                      );
                    })
                  : !aiMetadata &&
                    !loadingAI && (
                      <div className="compliant-notice">
                        <span className="compliant-icon">✓</span>
                        <div>
                          <strong>Compliant with all quality measures</strong>
                          <p>
                            Run AI analysis to get a full compliance summary and
                            preventive care recommendations.
                          </p>
                        </div>
                      </div>
                    )}
              </div>
            )}
          </div>
        )}

        {/* ── PATIENT RECORD TAB ─────────────────────────────────────────── */}
        {activeTab === "patient-record" && (
          <PatientRecordTab
            memberId={member?.member_id}
            lifestyle={details?.lifestyle || {}}
            familyHistory={details?.family_history || []}
            medicalHistory={details?.medical_history || {}}
            claims={details?.claims || []}
            onRefresh={fetchMemberDetails}
          />
        )}

        {false && activeTab === "gaps" && (
          <div className="gaps-tab">
            {details?.open_gaps?.length > 0 ? (
              <div className="gaps-list">
                {details.open_gaps.map((gap) => (
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
                        <span className="value">
                          {gap.lookback_months} months
                        </span>
                      </div>
                      <div className="gap-info-row">
                        <span className="label">Required CPT Code:</span>
                        <span className="value code">
                          {gap.primary_cpt_code || gap.required_cpt_codes}
                        </span>
                      </div>
                      {gap.primary_icd10 && (
                        <div className="gap-info-row">
                          <span className="label">ICD-10 Code:</span>
                          <span className="value code">
                            {gap.primary_icd10}
                          </span>
                        </div>
                      )}
                      <div className="gap-resolution">
                        <h4>Resolution Guide:</h4>
                        <p>{gap.resolution_guide}</p>
                      </div>
                    </div>
                    <div className="gap-detail-footer">
                      {!bookings[gap.care_gap_id] ? (
                        <button
                          className="btn-primary"
                          onClick={() => handleBookAppointment(gap)}
                        >
                          <Calendar size={16} />
                          Schedule Service
                        </button>
                      ) : (
                        <button
                          className="btn-view-booking"
                          onClick={() =>
                            setViewBooking(bookings[gap.care_gap_id])
                          }
                        >
                          <Calendar size={16} />
                          View Booking
                        </button>
                      )}
                      <button
                        className="btn-secondary"
                        onClick={() => setChatOpen(true)}
                      >
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
                {details.closed_gaps.map((gap) => (
                  <div key={gap.care_gap_id} className="closed-gap-card">
                    <div className="closed-gap-info">
                      <div>
                        <h4>{gap.measure_name}</h4>
                        <span className="closed-gap-measure-id">
                          {gap.measure_id}
                        </span>
                      </div>
                      <span className="gap-status closed">CLOSED</span>
                    </div>
                    <div className="closed-gap-meta">
                      <div className="closed-meta-row">
                        <span className="closed-meta-label">Closed on:</span>
                        <span>{gap.closed_on || gap.service_date || "—"}</span>
                      </div>
                      {gap.claim_id && (
                        <div className="closed-meta-row">
                          <span className="closed-meta-label">Claim ID:</span>
                          <code className="claim-id-code">{gap.claim_id}</code>
                        </div>
                      )}
                      {gap.cpt_code && (
                        <div className="closed-meta-row">
                          <span className="closed-meta-label">
                            CPT Code(s):
                          </span>
                          <code className="closed-cpt-code">
                            {gap.cpt_code}
                          </code>
                        </div>
                      )}
                      {gap.icd_code && (
                        <div className="closed-meta-row">
                          <span className="closed-meta-label">ICD-10:</span>
                          <code>{gap.icd_code}</code>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── APPOINTMENTS TAB ────────────────────────────────────────── */}
        {activeTab === "appointments" && (
          <div className="appointments-tab">
            <div className="appointments-tab-header">
              <h3>All Appointments</h3>
              <p className="appointments-tab-sub">
                Appointments booked by the member via portal or by the care
                manager. Force close to generate claim, close the care gap, and
                mark the member compliant.
              </p>
            </div>
            {details?.appointments?.length > 0 ? (
              <div className="appointments-list">
                {details.appointments.map((appt) => {
                  const isCompleted = appt.status === "Completed";
                  const isNoShow =
                    appt.status === "No Show" ||
                    appt.status === "Cancelled_NoShow";
                  const isCancelled = appt.status === "Cancelled";
                  const isScheduled = !isCompleted && !isNoShow && !isCancelled;
                  const booking = bookings[appt.care_gap_id] || {
                    appointment_id: appt.appointment_id,
                    measure_name: appt.screening_name || appt.measure_id,
                    care_gap_id: appt.care_gap_id,
                    appointment_date: appt.appointment_date,
                    appointment_time: appt.appointment_time,
                    lab_number: appt.lab_number,
                    lab_location: appt.lab_location,
                    lab_specialist: appt.lab_specialist,
                    cpt_codes: appt.cpt_codes,
                    icd_codes: appt.icd_codes,
                    status: appt.status,
                    member_email: appt.member_email,
                    member_name: appt.member_name,
                    plan_id: appt.plan_id,
                    insurance_type: appt.insurance_type,
                    pcp_name: appt.pcp_name,
                    email_sent: !!appt.member_email,
                  };
                  const friendlyTime = (() => {
                    try {
                      const [h, m] = (appt.appointment_time || "").split(":");
                      const hr = parseInt(h);
                      return `${hr > 12 ? hr - 12 : hr || 12}:${m} ${hr >= 12 ? "PM" : "AM"}`;
                    } catch {
                      return appt.appointment_time || "";
                    }
                  })();
                  const cardClass = isCompleted
                    ? "appointment-card--completed"
                    : isNoShow
                      ? "appointment-card--noshow"
                      : isCancelled
                        ? "appointment-card--cancelled"
                        : "appointment-card--scheduled";
                  const statusLabel = isCompleted
                    ? "Completed"
                    : isNoShow
                      ? "Missed (No Show)"
                      : isCancelled
                        ? "Cancelled"
                        : "Scheduled";
                  const statusEmoji = isCompleted
                    ? "✅"
                    : isNoShow
                      ? "⚠️"
                      : isCancelled
                        ? "🚫"
                        : "📅";
                  return (
                    <div
                      key={appt.appointment_id}
                      className={`appointment-card ${cardClass}`}
                    >
                      <div className="appointment-card-left">
                        <div className="appointment-card-icon">
                          {statusEmoji}
                        </div>
                        <div className="appointment-card-info">
                          <div className="appointment-card-title">
                            {appt.screening_name || appt.measure_id}
                            <span className="appointment-card-measure">
                              {appt.measure_id}
                            </span>
                          </div>
                          <div className="appointment-card-meta">
                            {appt.appointment_date} at {friendlyTime}
                            &nbsp;&bull;&nbsp;{" "}
                            {appt.lab_specialist || "Specialist TBD"}
                            &nbsp;&bull;&nbsp;{" "}
                            {appt.lab_location || "Location TBD"}
                          </div>
                          <div className="appointment-card-codes">
                            <span>
                              CPT: <code>{appt.cpt_codes || "N/A"}</code>
                            </span>
                            <span>
                              ICD: <code>{appt.icd_codes || "N/A"}</code>
                            </span>
                            <span>
                              ID: <code>{appt.appointment_id}</code>
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="appointment-card-right">
                        <span
                          className={`appointment-status-badge ${isCompleted ? "completed" : isNoShow ? "noshow" : isCancelled ? "cancelled" : "scheduled"}`}
                        >
                          {statusLabel}
                        </span>
                        <div className="appointment-card-actions">
                          <button
                            className="btn-view-booking"
                            onClick={() => setViewBooking(booking)}
                          >
                            View Details
                          </button>
                          {isCompleted && (
                            <span
                              className="appt-auto-note"
                              title="Backend auto-close generates the claim and closes the gap once the appointment is marked Completed"
                            >
                              ✅ Manually-closed
                            </span>
                          )}
                          {isNoShow && (
                            <span
                              className="appt-rebook-note"
                              title="Member will rebook via email link — no portal action needed"
                            >
                              🔁 Awaiting member rebook
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="no-data">
                <h3>No Appointments</h3>
                <p>
                  No appointments have been booked yet. Appointments will appear
                  here when the member books through the portal or when you book
                  from the Care Gaps tab.
                </p>
              </div>
            )}
          </div>
        )}

        {false && activeTab === "claims" && (
          <div className="claims-tab">
            {details?.claims?.length > 0 ? (
              <div className="claims-table">
                <table>
                  <thead>
                    <tr>
                      <th>Claim ID</th>
                      <th>Measure</th>
                      <th>Service Date</th>
                      <th>CPT Code(s)</th>
                      <th>ICD-10 Code(s)</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {details.claims.map((claim, i) => (
                      <tr key={i}>
                        <td>
                          <code className="claim-id-code">
                            {claim.claim_id || "—"}
                          </code>
                        </td>
                        <td>
                          <span className="measure-badge">
                            {claim.measure_id || "—"}
                          </span>
                        </td>
                        <td>{claim.service_date || "—"}</td>
                        <td className="code-cell">
                          <code>{claim.cpt_code || "—"}</code>
                        </td>
                        <td className="code-cell">
                          <code>{claim.icd_code || "—"}</code>
                        </td>
                        <td>
                          <span className="status-badge">
                            {claim.status || "Processed"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="no-data">
                <FileText size={48} color="#97999B" />
                <h3>No Claims Found</h3>
                <p>No claims data available for this member.</p>
              </div>
            )}
          </div>
        )}

        {/* ── OUTREACH TAB ───────────────────────────────────────────────── */}
        {activeTab === "outreach" && (
          <OutreachTimeline
            outreach={details?.outreach_history || []}
            appointments={details?.appointments || []}
            member={member}
          />
        )}
      </div>

      {/* ── PERSONA GRAPH + LIFECYCLE — Overview only ────────────────────── */}
      {activeTab === "overview" && (
        <div className="persona-graph-section">
          <h4>
            <GitCompare size={18} />
            Care Gap Lifecycle — Persona Visualization
          </h4>
          <p
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              margin: "0 0 12px",
            }}
          >
            Real-time visualization showing this member's care gap journey:
            identification, AI analysis, outreach, appointment booking, and gap
            closure.
          </p>

          {personaLoading ? (
            <div className="graph-loading">
              <Loader size={16} className="spinning" /> Loading persona graph…
            </div>
          ) : personaGraph && personaGraph.nodes?.length > 0 ? (
            <>
              <Neo4jGraph
                nodes={personaGraph.nodes}
                edges={personaGraph.edges}
                width={800}
                height={450}
              />

              {/* ── Lifecycle Timeline ────────────────────────────────── */}
              {personaGraph.lifecycle && personaGraph.lifecycle.length > 0 && (
                <div className="lifecycle-section">
                  <h5 className="lifecycle-title">
                    Care Gap Lifecycle Timeline
                  </h5>
                  {personaGraph.lifecycle.map((gap) => {
                    const STAGES = [
                      {
                        key: "gap_identified",
                        label: "Gap Identified",
                        icon: "🔍",
                        color: "#B81F2D",
                        time: gap.identified_at,
                      },
                      {
                        key: "analysis_started",
                        label: "Analysis Started",
                        icon: "🤖",
                        color: "#F59E0B",
                        time: gap.analysis_started_at,
                      },
                      {
                        key: "analysis_complete",
                        label: "Analysis Complete",
                        icon: "📊",
                        color: "#FF8C00",
                        time: gap.analysis_completed_at,
                      },
                      {
                        key: "outreach_sent",
                        label: "Outreach Sent",
                        icon: "📧",
                        color: "#3B82F6",
                        time: gap.outreach_sent_at,
                      },
                      {
                        key: "appointment_booked",
                        label: "Appointment Booked",
                        icon: "📅",
                        color: "#8B5CF6",
                        time: gap.appointment_booked_at,
                      },
                      {
                        key: "gap_closed",
                        label: "Gap Closed",
                        icon: "✅",
                        color: "#10B981",
                        time: gap.closed_at,
                      },
                    ];
                    const currentIdx = STAGES.findIndex(
                      (s) => s.key === gap.stage,
                    );

                    return (
                      <div key={gap.gap_id} className="lifecycle-card">
                        <div className="lifecycle-card-header">
                          <span className="lifecycle-measure">
                            {gap.measure_name || gap.measure_id}
                          </span>
                          <span
                            className={`lifecycle-status ${gap.status === "Closed" ? "closed" : "open"}`}
                          >
                            {gap.status}
                          </span>
                        </div>

                        <div className="lifecycle-track">
                          {STAGES.map((stage, idx) => {
                            const reached = idx <= currentIdx;
                            const isCurrent = idx === currentIdx;
                            return (
                              <div
                                key={stage.key}
                                className={`lifecycle-step ${reached ? "reached" : ""} ${isCurrent ? "current" : ""}`}
                              >
                                {idx > 0 && (
                                  <div
                                    className="lifecycle-connector"
                                    style={{
                                      background: reached
                                        ? stage.color
                                        : "#E5E7EB",
                                    }}
                                  />
                                )}
                                <div
                                  className="lifecycle-dot"
                                  style={{
                                    background: reached
                                      ? stage.color
                                      : "#E5E7EB",
                                    boxShadow: isCurrent
                                      ? `0 0 0 4px ${stage.color}33`
                                      : "none",
                                  }}
                                >
                                  <span className="lifecycle-icon">
                                    {reached ? stage.icon : ""}
                                  </span>
                                </div>
                                <span
                                  className="lifecycle-label"
                                  style={{
                                    color: reached ? stage.color : "#9CA3AF",
                                  }}
                                >
                                  {stage.label}
                                </span>
                                {stage.time && (
                                  <span className="lifecycle-time">
                                    {new Date(stage.time).toLocaleDateString(
                                      "en-US",
                                      {
                                        month: "short",
                                        day: "numeric",
                                        hour: "2-digit",
                                        minute: "2-digit",
                                      },
                                    )}
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>

                        {gap.outreach_channel && (
                          <div className="lifecycle-detail">
                            Channel: {gap.outreach_channel}
                          </div>
                        )}
                        {gap.appointment_date && (
                          <div className="lifecycle-detail">
                            Appointment: {gap.appointment_date}{" "}
                            {gap.lab_location ? `at ${gap.lab_location}` : ""}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Persona detail card removed — persona info is already
                  represented inside the lifecycle graph itself. */}
            </>
          ) : (
            <div
              style={{
                padding: 16,
                fontSize: 13,
                color: "var(--text-secondary)",
              }}
            >
              No persona data yet. Run Auto Process or upload members to
              generate the care gap lifecycle visualization.
            </div>
          )}
        </div>
      )}

      {/* ── CONVERSATIONAL CHAT PANEL ────────────────────────────────────── */}
      {chatOpen && (
        <div className="chat-modal">
          <div className="chat-container">
            <div className="chat-header">
              <div className="chat-header-info">
                <Bot size={20} />
                <div>
                  <h3>AI Care Manager</h3>
                  <p className="chat-member-context">
                    {member.name} · {details?.open_gaps?.length || 0} open gaps
                  </p>
                </div>
              </div>
              <button className="close-chat" onClick={() => setChatOpen(false)}>
                <X size={20} />
              </button>
            </div>

            <div className="chat-messages">
              {chatMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`chat-message ${msg.role === "user" ? "care_manager" : "ai_agent"}`}
                >
                  <div className="message-bubble">
                    {msg.role === "assistant" && (
                      <div className="ai-badge">
                        <Bot size={12} />
                        AI Assistant
                      </div>
                    )}
                    <div className="message-content">
                      <MarkdownContent
                        text={msg.text}
                        className="chat-markdown"
                      />
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
                onChange={(e) => setMessageInput(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" && !e.shiftKey && handleSendMessage()
                }
                disabled={chatLoading}
              />
              <button
                onClick={handleSendMessage}
                disabled={chatLoading || !messageInput.trim()}
              >
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
                <p className="appt-modal-sub">
                  {selectedGap.measure_name} · {selectedGap.measure_id}
                </p>
              </div>
              <button
                className="appt-modal-close"
                onClick={() => {
                  setShowAppointmentModal(false);
                  setBookingError("");
                }}
              >
                <X size={18} />
              </button>
            </div>

            <div className="appt-modal-body">
              <div className="appt-member-row">
                <span className="appt-avatar">
                  {member.name
                    .split(" ")
                    .map((n) => n[0])
                    .join("")
                    .slice(0, 2)}
                </span>
                <div>
                  <strong>{member.name}</strong>
                  <span className="appt-member-id"> · {member.member_id}</span>
                </div>
              </div>

              <div className="appt-fields">
                <div className="appt-field-group">
                  <label>
                    <Calendar size={14} /> Appointment Date *
                  </label>
                  <input
                    type="date"
                    value={appointmentDate}
                    min={new Date().toISOString().split("T")[0]}
                    onChange={(e) => setAppointmentDate(e.target.value)}
                    className="appt-input"
                  />
                </div>
                <div className="appt-field-group">
                  <label>⏰ Appointment Time *</label>
                  <select
                    value={appointmentTime}
                    onChange={(e) => setAppointmentTime(e.target.value)}
                    className="appt-input"
                  >
                    {[
                      "08:00",
                      "08:30",
                      "09:00",
                      "09:30",
                      "10:00",
                      "10:30",
                      "11:00",
                      "11:30",
                      "12:00",
                      "12:30",
                      "13:00",
                      "13:30",
                      "14:00",
                      "14:30",
                      "15:00",
                      "15:30",
                      "16:00",
                      "16:30",
                    ].map((t) => {
                      const [h, m] = t.split(":");
                      const hr = parseInt(h);
                      const label = `${hr > 12 ? hr - 12 : hr}:${m} ${hr >= 12 ? "PM" : "AM"}`;
                      return (
                        <option key={t} value={t}>
                          {label}
                        </option>
                      );
                    })}
                  </select>
                </div>
              </div>

              <div className="appt-info-box">
                <p className="appt-info-title">
                  📧 Confirmation email will be sent to the member&apos;s
                  registered email address with:
                </p>
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
              <button
                className="btn-secondary"
                onClick={() => {
                  setShowAppointmentModal(false);
                  setBookingError("");
                }}
              >
                Cancel
              </button>
              <button
                className="btn-primary appt-confirm-btn"
                onClick={confirmAppointment}
                disabled={bookingLoading}
              >
                {bookingLoading ? (
                  <>
                    <span className="appt-spinner" /> Booking &amp; Sending
                    Email…
                  </>
                ) : (
                  <>
                    <Calendar size={15} /> Confirm &amp; Send Invite
                  </>
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
              <button
                className="appt-modal-close"
                onClick={() => setViewBooking(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="vb-body">
              {/* Status banner + status-aware countdown */}
              {(() => {
                const s = viewBooking.status;
                const isCompleted =
                  s === "Completed" ||
                  completedGaps.has(viewBooking.care_gap_id);
                const isCancelled =
                  s === "Cancelled" ||
                  s === "Cancelled_NoShow" ||
                  s === "No Show";
                const isNotBooked = !s || s === "Not Booked";
                const banner = isCompleted
                  ? "vb-status-done"
                  : isCancelled
                    ? "vb-status-cancelled"
                    : isNotBooked
                      ? "vb-status-waiting"
                      : "vb-status-scheduled";
                const bannerText = isCompleted
                  ? "✅ Screening Completed — Care Gap Closed"
                  : isCancelled
                    ? "🔁 Awaiting member to rebook (member-driven via email link)"
                    : isNotBooked
                      ? "📨 Outreach Done — Waiting for member to Rebook appointment"
                      : "📅 Appointment Scheduled";
                return (
                  <>
                    <div className={`vb-status-banner ${banner}`}>
                      {bannerText}
                    </div>
                    <BookingCountdown
                      status={s}
                      isCompleted={isCompleted}
                      isCancelled={isCancelled}
                      isNotBooked={isNotBooked}
                      appointmentDate={viewBooking.appointment_date}
                      appointmentTime={viewBooking.appointment_time}
                      memberId={member?.member_id}
                      measureId={
                        viewBooking.measure_id || viewBooking.care_gap_id
                      }
                    />
                  </>
                );
              })()}

              <div className="vb-grid">
                <div className="vb-section">
                  <div className="vb-section-title">📅 Appointment</div>
                  <div className="vb-row">
                    <span>Date</span>
                    <strong>{viewBooking.appointment_date}</strong>
                  </div>
                  <div className="vb-row">
                    <span>Time</span>
                    <strong>{viewBooking.appointment_time}</strong>
                  </div>
                  <div className="vb-row">
                    <span>Appointment ID</span>
                    <code>{viewBooking.appointment_id}</code>
                  </div>
                  <div className="vb-row">
                    <span>Email Sent</span>
                    <strong>
                      {viewBooking.email_sent
                        ? `✓ ${viewBooking.member_email}`
                        : "No email on file"}
                    </strong>
                  </div>
                </div>

                <div className="vb-section">
                  <div className="vb-section-title">
                    🏥 Lab &amp; Specialist
                  </div>
                  <div className="vb-row">
                    <span>Lab Number</span>
                    <strong>{viewBooking.lab_number}</strong>
                  </div>
                  <div className="vb-row">
                    <span>Location</span>
                    <strong>{viewBooking.lab_location}</strong>
                  </div>
                  <div className="vb-row">
                    <span>Specialist</span>
                    <strong>{viewBooking.lab_specialist}</strong>
                  </div>
                  <div className="vb-row">
                    <span>Referring PCP</span>
                    <strong>
                      {viewBooking.pcp_name || details?.profile?.pcp_name}
                    </strong>
                  </div>
                </div>

                <div className="vb-section">
                  <div className="vb-section-title">🩺 Screening Codes</div>
                  <div className="vb-row">
                    <span>Screening</span>
                    <strong>{viewBooking.measure_name}</strong>
                  </div>
                  <div className="vb-row">
                    <span>CPT Codes</span>
                    <code>{viewBooking.cpt_codes || "—"}</code>
                  </div>
                  <div className="vb-row">
                    <span>ICD-10 Codes</span>
                    <code>{viewBooking.icd_codes || "—"}</code>
                  </div>
                </div>

                <div className="vb-section">
                  <div className="vb-section-title">
                    💳 Insurance &amp; Claim
                  </div>
                  <div className="vb-row">
                    <span>Plan ID</span>
                    <code>
                      {viewBooking.plan_id || details?.profile?.plan_id}
                    </code>
                  </div>
                  <div className="vb-row">
                    <span>Insurance Type</span>
                    <strong>{viewBooking.insurance_type || "—"}</strong>
                  </div>
                  <div className="vb-row">
                    <span>Member ID</span>
                    <code>{member.member_id}</code>
                  </div>
                  {viewBooking.claim_id ? (
                    <div className="vb-row">
                      <span>Claim ID</span>
                      <code className="vb-claim-id">
                        {viewBooking.claim_id}
                      </code>
                    </div>
                  ) : (
                    <div className="vb-row vb-row-pending">
                      <span>Claim ID</span>
                      <em>Generated after screening complete</em>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="vb-footer">
              {completeError && (
                <div className="complete-error-msg">{completeError}</div>
              )}
              <div className="vb-footer-btns">
                <button
                  className="btn-secondary"
                  onClick={() => {
                    setViewBooking(null);
                    setCompleteError("");
                  }}
                >
                  Close
                </button>
                {(() => {
                  const s = viewBooking.status;
                  const isClosedGap = completedGaps.has(
                    viewBooking.care_gap_id,
                  );
                  const isCompleted = s === "Completed" || isClosedGap;
                  const isCancelled =
                    s === "Cancelled" ||
                    s === "Cancelled_NoShow" ||
                    s === "No Show";
                  const hasNoBooking = !s || s === "Not Booked";
                  // Only show Close + Force-Close when the appointment is actively
                  // Scheduled/Booked. Cancelled/No-Show is rebooked by the member
                  // via email — portal does nothing. Not-Booked / Completed: nothing.
                  if (isCompleted || isCancelled || hasNoBooking) {
                    if (isCancelled) {
                      return (
                        <span className="vb-status-note vb-status-note--rebook">
                          Appointment cancelled — member will rebook via email
                          link.
                        </span>
                      );
                    }
                    return null;
                  }
                  return (
                    <span className="vb-auto-note">
                      ✅ Once the member completes this appointment, manual
                      action required to generate the claim.
                    </span>
                  );
                })()}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── COMPARISON ────────────────────────────────────────────────────── */}
      {showComparison && (
        <MemberComparison
          member={member}
          onClose={() => setShowComparison(false)}
        />
      )}

      {/* ── EMAIL PANEL ────────────────────────────────────────────────────── */}
      {emailPanelOpen && (
        <EmailPanel member={member} onClose={() => setEmailPanelOpen(false)} />
      )}
    </div>
  );
}

// ── Outreach Timeline Wave Graph ─────────────────────────────────────────────
function OutreachTimeline({ outreach, appointments, member }) {
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [emailHtml, setEmailHtml] = useState({});
  const [expandedEmail, setExpandedEmail] = useState(null);

  // Merge outreach + appointment events into one sorted timeline
  const events = useMemo(() => {
    const list = [];

    appointments.forEach((a) => {
      list.push({
        id: a.appointment_id,
        date: a.appointment_date,
        type: a.status === "Completed" ? "completed" : "appointment",
        label: a.screening_name || a.measure_id,
        sub:
          a.status === "Completed"
            ? "Screening Completed"
            : "Appointment Scheduled",
        channel: "Email Invite",
        email: a.member_email,
        cpt: a.cpt_codes,
        icd: a.icd_codes,
        lab: a.lab_number,
        specialist: a.lab_specialist,
        location: a.lab_location,
        time: a.appointment_time,
        appt_id: a.appointment_id,
        measure: a.measure_id,
      });
    });

    outreach.forEach((o) => {
      list.push({
        id: o.outreach_id,
        date: o.date,
        type:
          o.status?.toLowerCase() === "completed" ? "completed" : "outreach",
        label: o.measure_name || o.measure_id || "Outreach",
        sub: o.channel,
        channel: o.channel,
        status: o.status,
      });
    });

    return list
      .filter((e) => e.date)
      .sort((a, b) => new Date(a.date) - new Date(b.date));
  }, [outreach, appointments]);

  // Fetch HTML email bodies once
  useEffect(() => {
    if (!appointments.some((a) => a.member_email)) return;
    axios
      .get(`${API_BASE}/email/${member.member_id}`)
      .then((res) => {
        const map = {};
        (res.data.emails || []).forEach((e) => {
          if (e.appointment_id && e.html_body)
            map[e.appointment_id] = e.html_body;
        });
        setEmailHtml(map);
      })
      .catch(() => {});
  }, [member.member_id]);

  if (events.length === 0) {
    return (
      <div className="no-data">
        <MessageCircle size={48} color="#97999B" />
        <h3>No Outreach History</h3>
        <p>No outreach or appointment activity recorded for this member.</p>
      </div>
    );
  }

  // ── SVG wave graph dimensions ──────────────────────────────────────────────
  const W = 900,
    H = 220,
    PAD = 60;
  const n = events.length;
  const xStep = n > 1 ? (W - PAD * 2) / (n - 1) : 0;

  // Y positions: wave pattern — alternate between 3 heights
  const yLevels = [H * 0.25, H * 0.55, H * 0.35];
  const getY = (i) => yLevels[i % yLevels.length];

  // Build smooth SVG path through all points
  const points = events.map((_, i) => ({
    x: n === 1 ? W / 2 : PAD + i * xStep,
    y: getY(i),
  }));

  const pathD = points.reduce((d, p, i) => {
    if (i === 0) return `M ${p.x} ${p.y}`;
    const prev = points[i - 1];
    const cpx = (prev.x + p.x) / 2;
    return `${d} C ${cpx} ${prev.y}, ${cpx} ${p.y}, ${p.x} ${p.y}`;
  }, "");

  // Color per event type
  const typeColor = {
    appointment: "#2F78C4",
    completed: "#2DB81F",
    outreach: "#7373D8",
  };
  const typeIcon = {
    appointment: "📅",
    completed: "✅",
    outreach: "📞",
  };

  const fmtDate = (d) => {
    if (!d) return "";
    try {
      return new Date(d).toLocaleDateString([], {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return d;
    }
  };

  return (
    <div className="ot-wrap">
      <div className="ot-header">
        <h3 className="ot-title">Outreach Activity Timeline</h3>
        <div className="ot-legend">
          {Object.entries(typeColor).map(([t, c]) => (
            <span key={t} className="ot-legend-item">
              <span className="ot-legend-dot" style={{ background: c }} />
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </span>
          ))}
        </div>
      </div>

      {/* ── Wave SVG ──────────────────────────────────────────────────── */}
      <div className="ot-svg-wrap">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="ot-svg"
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Gradient fill under the wave */}
          <defs>
            <linearGradient id="waveGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2F78C4" stopOpacity="0.18" />
              <stop offset="100%" stopColor="#2F78C4" stopOpacity="0.01" />
            </linearGradient>
          </defs>

          {/* Filled area under wave */}
          {points.length > 1 && (
            <path
              d={`${pathD} L ${points[points.length - 1].x} ${H} L ${points[0].x} ${H} Z`}
              fill="url(#waveGrad)"
            />
          )}

          {/* Wave line */}
          <path
            d={pathD}
            fill="none"
            stroke="#2F78C4"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ filter: "drop-shadow(0 2px 4px rgba(47,120,196,0.3))" }}
          />

          {/* Vertical drop lines + date labels */}
          {points.map((p, i) => (
            <g key={i}>
              <line
                x1={p.x}
                y1={p.y + 10}
                x2={p.x}
                y2={H - 18}
                stroke="#E8E8E6"
                strokeWidth="1"
                strokeDasharray="3,3"
              />
              <text
                x={p.x}
                y={H - 4}
                textAnchor="middle"
                fontSize="9"
                fill="#97999B"
                fontFamily="system-ui"
              >
                {fmtDate(events[i].date)}
              </text>
            </g>
          ))}

          {/* Event nodes */}
          {points.map((p, i) => {
            const ev = events[i];
            const col = typeColor[ev.type] || "#53565A";
            const isSelected = selectedEvent?.id === ev.id;
            return (
              <g
                key={ev.id}
                style={{ cursor: "pointer" }}
                onClick={() => setSelectedEvent(isSelected ? null : ev)}
              >
                {/* Pulse ring on selected */}
                {isSelected && (
                  <circle cx={p.x} cy={p.y} r={20} fill={col} opacity={0.15}>
                    <animate
                      attributeName="r"
                      values="16;24;16"
                      dur="1.8s"
                      repeatCount="indefinite"
                    />
                    <animate
                      attributeName="opacity"
                      values="0.2;0.05;0.2"
                      dur="1.8s"
                      repeatCount="indefinite"
                    />
                  </circle>
                )}
                {/* Outer ring */}
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={isSelected ? 14 : 11}
                  fill="white"
                  stroke={col}
                  strokeWidth={isSelected ? 3 : 2}
                  style={{
                    transition: "r 0.2s, stroke-width 0.2s",
                    filter: isSelected ? `drop-shadow(0 0 6px ${col})` : "none",
                  }}
                />
                {/* Inner fill */}
                <circle cx={p.x} cy={p.y} r={isSelected ? 8 : 6} fill={col} />
                {/* Icon */}
                <text x={p.x} y={p.y - 20} textAnchor="middle" fontSize="13">
                  {typeIcon[ev.type]}
                </text>
                {/* Label above icon */}
                <text
                  x={p.x}
                  y={p.y - 34}
                  textAnchor="middle"
                  fontSize="8.5"
                  fill="#53565A"
                  fontWeight="600"
                  fontFamily="system-ui"
                  style={{ maxWidth: 80 }}
                >
                  {ev.label?.length > 14
                    ? ev.label.slice(0, 13) + "…"
                    : ev.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* ── Event detail card ─────────────────────────────────────────── */}
      {selectedEvent && (
        <div
          className="ot-detail"
          style={{ borderColor: typeColor[selectedEvent.type] || "#E8E8E6" }}
        >
          <div className="ot-detail-header">
            <span className="ot-detail-icon">
              {typeIcon[selectedEvent.type]}
            </span>
            <div>
              <div className="ot-detail-title">{selectedEvent.label}</div>
              <div className="ot-detail-sub">
                {selectedEvent.sub} &nbsp;·&nbsp; {fmtDate(selectedEvent.date)}
              </div>
            </div>
            <span
              className="ot-detail-badge"
              style={{
                background: typeColor[selectedEvent.type] + "20",
                color: typeColor[selectedEvent.type],
              }}
            >
              {selectedEvent.type.charAt(0).toUpperCase() +
                selectedEvent.type.slice(1)}
            </span>
          </div>

          <div className="ot-detail-grid">
            {selectedEvent.channel && (
              <OtRow label="Channel" value={selectedEvent.channel} />
            )}
            {selectedEvent.time && (
              <OtRow label="Time" value={selectedEvent.time} />
            )}
            {selectedEvent.lab && (
              <OtRow label="Lab" value={selectedEvent.lab} />
            )}
            {selectedEvent.specialist && (
              <OtRow label="Specialist" value={selectedEvent.specialist} />
            )}
            {selectedEvent.location && (
              <OtRow label="Location" value={selectedEvent.location} />
            )}
            {selectedEvent.cpt && (
              <OtRow
                label="CPT Code"
                value={<code>{selectedEvent.cpt}</code>}
              />
            )}
            {selectedEvent.icd && (
              <OtRow label="ICD-10" value={<code>{selectedEvent.icd}</code>} />
            )}
            {selectedEvent.email && (
              <OtRow label="Sent To" value={selectedEvent.email} />
            )}
            {selectedEvent.status && (
              <OtRow label="Status" value={selectedEvent.status} />
            )}
          </div>

          {/* Email HTML preview toggle */}
          {selectedEvent.appt_id && (
            <div className="ot-email-section">
              <button
                className="ot-email-toggle"
                onClick={() =>
                  setExpandedEmail(
                    expandedEmail === selectedEvent.appt_id
                      ? null
                      : selectedEvent.appt_id,
                  )
                }
              >
                {expandedEmail === selectedEvent.appt_id
                  ? "▲ Hide Email Preview"
                  : "▼ View Appointment Email"}
              </button>
              {expandedEmail === selectedEvent.appt_id && (
                <div className="ot-email-frame">
                  {emailHtml[selectedEvent.appt_id] ? (
                    <iframe
                      srcDoc={emailHtml[selectedEvent.appt_id]}
                      title="Email Preview"
                      sandbox="allow-same-origin"
                      style={{
                        width: "100%",
                        height: 500,
                        border: "none",
                        display: "block",
                      }}
                    />
                  ) : (
                    <div className="ot-email-empty">
                      Email preview not available
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Compact event list below graph ───────────────────────────── */}
      <div className="ot-list">
        {events.map((ev, i) => (
          <div
            key={ev.id}
            className={`ot-list-item ${selectedEvent?.id === ev.id ? "ot-list-item--active" : ""}`}
            style={{ borderLeftColor: typeColor[ev.type] || "#E8E8E6" }}
            onClick={() =>
              setSelectedEvent(selectedEvent?.id === ev.id ? null : ev)
            }
          >
            <span className="ot-list-icon">{typeIcon[ev.type]}</span>
            <div className="ot-list-body">
              <span className="ot-list-label">{ev.label}</span>
              <span className="ot-list-meta">
                {ev.sub} &nbsp;·&nbsp; {fmtDate(ev.date)}
              </span>
            </div>
            <span
              className="ot-list-badge"
              style={{
                background: typeColor[ev.type] + "18",
                color: typeColor[ev.type],
              }}
            >
              {ev.type}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OtRow({ label, value }) {
  return (
    <div className="ot-row">
      <span className="ot-row-label">{label}</span>
      <span className="ot-row-value">{value}</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════
// Patient Record Tab — Lifestyle, Family History, Medical History, Risks
// ═══════════════════════════════════════════════════════════════════════

const PR_FAMILY_RELATIONS = [
  "Father",
  "Mother",
  "Brother",
  "Sister",
  "Son",
  "Daughter",
  "Paternal Grandfather",
  "Paternal Grandmother",
  "Maternal Grandfather",
  "Maternal Grandmother",
  "Paternal Uncle",
  "Paternal Aunt",
  "Maternal Uncle",
  "Maternal Aunt",
];

const PR_HEREDITARY_CONDITIONS = [
  "Diabetes Type 2",
  "Diabetes Type 1",
  "Hypertension",
  "Coronary Artery Disease",
  "Stroke",
  "High Cholesterol",
  "Breast Cancer",
  "Colorectal Cancer",
  "Prostate Cancer",
  "Ovarian Cancer",
  "Lung Cancer",
  "Alzheimer's Disease",
  "Parkinson's Disease",
  "Asthma",
  "COPD",
  "Thyroid Disease",
  "Kidney Disease",
  "Depression",
  "Bipolar Disorder",
  "Schizophrenia",
  "Osteoporosis",
  "Rheumatoid Arthritis",
  "Sickle Cell Disease",
  "Hemophilia",
  "Cystic Fibrosis",
  "Huntington's Disease",
];

// ── Booking countdown — status-aware reminder timers shown inside the
// Booking Details modal. The cooldown values mirror those in the backend
// outreach_scheduler.py (24h rebook cooldown, 7d weekly reminder).
function BookingCountdown({
  status,
  isCompleted,
  isCancelled,
  isNotBooked,
  appointmentDate,
  appointmentTime,
  memberId,
  measureId,
}) {
  // The countdown's *target* must be captured ONCE when the component
  // mounts. Previously the target was recomputed each render as
  // `now + INTERVAL`, so `target - now` always equalled INTERVAL — a static
  // value, not a counting timer.
  const REBOOK_INTERVAL_MS = 24 * 60 * 60 * 1000;
  const WEEKLY_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000;

  // Persist the *target timestamp* in localStorage keyed by member+measure+kind
  // so the countdown survives modal close/open cycles. Without this each open
  // would reset the timer to the full interval.
  const kind = isCompleted
    ? "done"
    : isCancelled
      ? "rebook"
      : isNotBooked
        ? "weekly"
        : "scheduled";
  const storageKey = `bookingTimer:${memberId || ""}:${measureId || ""}:${kind}`;

  const computeTarget = () => {
    if (isNotBooked) return Date.now() + WEEKLY_INTERVAL_MS;
    if (isCancelled) return Date.now() + REBOOK_INTERVAL_MS;
    if (appointmentDate) {
      try {
        const isoTime = appointmentTime || "09:00";
        return new Date(`${appointmentDate}T${isoTime}`).getTime();
      } catch {
        return null;
      }
    }
    return null;
  };

  const [now, setNow] = useState(Date.now());
  const [target, setTarget] = useState(() => {
    try {
      const cached = localStorage.getItem(storageKey);
      if (cached) {
        const t = parseInt(cached, 10);
        if (!Number.isNaN(t) && t > Date.now() - 31 * 86400000) return t;
      }
    } catch {}
    const t = computeTarget();
    try {
      if (t) localStorage.setItem(storageKey, String(t));
    } catch {}
    return t;
  });

  // Re-arm target when the modal is reused for a different status — but
  // ALSO honor an existing cached target so the countdown continues.
  useEffect(() => {
    try {
      const cached = localStorage.getItem(storageKey);
      if (cached) {
        const t = parseInt(cached, 10);
        if (!Number.isNaN(t)) {
          setTarget(t);
          return;
        }
      }
    } catch {}
    const t = computeTarget();
    if (t) {
      setTarget(t);
      try {
        localStorage.setItem(storageKey, String(t));
      } catch {}
    }
  }, [storageKey]);

  // Tick every second so the formatted countdown re-renders.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  if (isCompleted || !target) return null;

  const fmt = (ms) => {
    if (ms <= 0) return "00d 00h 00m 00s";
    const d = Math.floor(ms / 86400000);
    const h = Math.floor((ms % 86400000) / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${String(d).padStart(2, "0")}d ${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  };

  const remaining = target - now;

  if (!isNotBooked && !isCancelled) {
    const overdue = remaining <= 0;
    return (
      <div
        className={`vb-timer ${overdue ? "vb-timer--overdue" : "vb-timer--scheduled"}`}
      >
        {overdue ? (
          <>
            <div className="vb-timer-label">
              ⚠ Appointment time has passed — auto-cancellation pending
            </div>
            <div className="vb-timer-value">
              {fmt(-remaining)} since scheduled time
            </div>
            <div className="vb-timer-hint">
              If not closed, the system auto-marks as cancelled and emails a
              rebook link.
            </div>
          </>
        ) : (
          <>
            <div className="vb-timer-label">
              ⏳ Time to scheduled appointment
            </div>
            <div className="vb-timer-value">{fmt(remaining)}</div>
            <div className="vb-timer-hint">
              Member will be reminded automatically. Missed appointments
              auto-cancel and trigger a rebook email.
            </div>
          </>
        )}
      </div>
    );
  }

  if (isCancelled) {
    return (
      <div className="vb-timer vb-timer--rebook">
        <div className="vb-timer-label">
          🔁 Awaiting member rebook — next automatic reminder in
        </div>
        <div className="vb-timer-value">{fmt(remaining)}</div>
        <div className="vb-timer-hint">
          Rebook reminder emails are sent automatically every 24 hours until the
          member books a new appointment.
        </div>
      </div>
    );
  }

  if (isNotBooked) {
    return (
      <div className="vb-timer vb-timer--weekly">
        <div className="vb-timer-label">
          📨 Next weekly reminder email scheduled in
        </div>
        <div className="vb-timer-value">{fmt(remaining)}</div>
        <div className="vb-timer-hint">
          If the member does not book, an automatic reminder email with a "Book
          Appointment" link is sent every 7 days.
        </div>
      </div>
    );
  }

  return null;
}

function PatientRecordTab({
  memberId,
  lifestyle,
  familyHistory,
  medicalHistory,
  claims = [],
  onRefresh,
}) {
  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  const [draftLifestyle, setDraftLifestyle] = useState(lifestyle || {});
  const [draftFamily, setDraftFamily] = useState(familyHistory || []);
  const [draftMedical, setDraftMedical] = useState(medicalHistory || {});

  useEffect(() => {
    setDraftLifestyle(lifestyle || {});
  }, [lifestyle]);
  useEffect(() => {
    setDraftFamily(familyHistory || []);
  }, [familyHistory]);
  useEffect(() => {
    setDraftMedical(medicalHistory || {});
  }, [medicalHistory]);

  const handleSave = async () => {
    if (!memberId) return;
    setSaving(true);
    setSaveMsg("");
    try {
      // Normalize lifestyle numeric fields
      const lsPayload = { ...draftLifestyle };
      ["bmi", "height_cm", "weight_kg", "sleep_hours_avg"].forEach((k) => {
        if (lsPayload[k] === "" || lsPayload[k] == null) lsPayload[k] = null;
        else lsPayload[k] = Number(lsPayload[k]);
      });

      await Promise.all([
        fetch(`${API_BASE}/members/${memberId}/lifestyle`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(lsPayload),
        }),
        fetch(`${API_BASE}/members/${memberId}/family-history`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ family_members: draftFamily }),
        }),
        fetch(`${API_BASE}/members/${memberId}/medical-history`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draftMedical),
        }),
      ]);
      setSaveMsg("Saved");
      setEditMode(false);
      onRefresh && onRefresh();
    } catch (err) {
      setSaveMsg("Save failed: " + err.message);
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(""), 3000);
    }
  };

  const handleCancel = () => {
    setDraftLifestyle(lifestyle || {});
    setDraftFamily(familyHistory || []);
    setDraftMedical(medicalHistory || {});
    setEditMode(false);
  };

  return (
    <div className="patient-record-tab">
      {/* Header / edit toggle */}
      <div className="patient-record-header">
        <h3>Comprehensive Patient Record</h3>
        <div>
          {saveMsg && <span className="save-msg">{saveMsg}</span>}
          {!editMode ? (
            <button className="btn-edit" onClick={() => setEditMode(true)}>
              Edit
            </button>
          ) : (
            <>
              <button
                className="btn-cancel-sm"
                onClick={handleCancel}
                disabled={saving}
              >
                Cancel
              </button>
              <button
                className="btn-save-sm"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Lifestyle card */}
      <div className="pr-card">
        <div className="pr-card-title">🏃 Lifestyle</div>
        {editMode ? (
          <LifestyleEditor data={draftLifestyle} onChange={setDraftLifestyle} />
        ) : (
          <LifestyleView data={lifestyle} />
        )}
      </div>

      {/* Family / Ancestral History card */}
      <div className="pr-card">
        <div className="pr-card-title">🧬 Family / Ancestral History</div>
        {editMode ? (
          <FamilyHistoryEditor data={draftFamily} onChange={setDraftFamily} />
        ) : (
          <FamilyHistoryView data={familyHistory} />
        )}
      </div>

      {/* Medical History card */}
      <div className="pr-card">
        <div className="pr-card-title">📋 Medical History</div>
        {editMode ? (
          <MedicalHistoryEditor
            data={draftMedical}
            onChange={setDraftMedical}
          />
        ) : (
          <MedicalHistoryView data={medicalHistory} />
        )}
      </div>

      {/* Claims card */}
      <div className="pr-card">
        <div className="pr-card-title">🧾 Claims ({claims.length})</div>
        {claims.length > 0 ? (
          <div className="claims-table claims-table--uniform">
            <table>
              <thead>
                <tr>
                  <th>Claim ID</th>
                  <th>Measure</th>
                  <th>Service Date</th>
                  <th>CPT Code(s)</th>
                  <th>ICD-10 Code(s)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((claim, i) => (
                  <tr key={i}>
                    <td>{claim.claim_id || "—"}</td>
                    <td>{claim.measure_id || "—"}</td>
                    <td>{claim.service_date || "—"}</td>
                    <td>{claim.cpt_code || "—"}</td>
                    <td>{claim.icd_code || "—"}</td>
                    <td>{claim.status || "Processed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p
            style={{ color: "var(--text-secondary)", fontSize: 13, margin: 0 }}
          >
            No claims data available for this member.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Lifestyle View ──
function LifestyleView({ data }) {
  const d = data || {};
  const rows = [
    ["BMI", d.bmi],
    ["Height", d.height_cm ? `${d.height_cm} cm` : ""],
    ["Weight", d.weight_kg ? `${d.weight_kg} kg` : ""],
    ["Smoking", d.smoking_status],
    ["Alcohol", d.alcohol_use],
    ["Exercise", d.exercise_frequency],
    ["Diet", d.diet_type],
    ["Sleep (avg hrs)", d.sleep_hours_avg],
    ["Stress", d.stress_level],
  ];
  const hasAny = rows.some(
    ([, v]) => v !== undefined && v !== null && v !== "",
  );
  if (!hasAny)
    return (
      <p className="pr-empty">No lifestyle data recorded. Click Edit to add.</p>
    );
  return (
    <div className="pr-kv-grid">
      {rows.map(([k, v]) => (
        <div className="pr-kv" key={k}>
          <span className="pr-kv-label">{k}</span>
          <span className="pr-kv-value">{v || "—"}</span>
        </div>
      ))}
      {d.notes && (
        <div className="pr-notes">
          <strong>Notes:</strong> {d.notes}
        </div>
      )}
    </div>
  );
}

// ── Lifestyle Editor ──
function LifestyleEditor({ data, onChange }) {
  const set = (k, v) => {
    const next = { ...data, [k]: v };
    const h = parseFloat(k === "height_cm" ? v : next.height_cm);
    const w = parseFloat(k === "weight_kg" ? v : next.weight_kg);
    if (h > 0 && w > 0) next.bmi = (w / (h / 100) ** 2).toFixed(1);
    onChange(next);
  };
  return (
    <div className="pr-editor-grid">
      <PRInput
        label="Height (cm)"
        type="number"
        value={data.height_cm || ""}
        onChange={(v) => set("height_cm", v)}
      />
      <PRInput
        label="Weight (kg)"
        type="number"
        value={data.weight_kg || ""}
        onChange={(v) => set("weight_kg", v)}
      />
      <PRInput
        label="BMI (auto)"
        value={data.bmi || ""}
        onChange={(v) => set("bmi", v)}
      />
      <PRSelect
        label="Smoking"
        value={data.smoking_status || ""}
        options={["", "Never", "Former", "Current (Light)", "Current (Heavy)"]}
        onChange={(v) => set("smoking_status", v)}
      />
      <PRSelect
        label="Alcohol"
        value={data.alcohol_use || ""}
        options={["", "None", "Occasional", "Regular", "Heavy"]}
        onChange={(v) => set("alcohol_use", v)}
      />
      <PRSelect
        label="Exercise"
        value={data.exercise_frequency || ""}
        options={[
          "",
          "Sedentary",
          "Light",
          "Moderate",
          "Active",
          "Very Active",
        ]}
        onChange={(v) => set("exercise_frequency", v)}
      />
      <PRSelect
        label="Diet"
        value={data.diet_type || ""}
        options={[
          "",
          "Balanced",
          "Vegetarian",
          "Vegan",
          "Mediterranean",
          "Low-Carb / Keto",
          "High-Sodium",
          "Irregular",
        ]}
        onChange={(v) => set("diet_type", v)}
      />
      <PRInput
        label="Sleep (hrs)"
        type="number"
        value={data.sleep_hours_avg || ""}
        onChange={(v) => set("sleep_hours_avg", v)}
      />
      <PRSelect
        label="Stress"
        value={data.stress_level || ""}
        options={["", "Low", "Moderate", "High"]}
        onChange={(v) => set("stress_level", v)}
      />
      <div className="pr-editor-wide">
        <label>Notes</label>
        <textarea
          rows="2"
          value={data.notes || ""}
          onChange={(e) => set("notes", e.target.value)}
        />
      </div>
    </div>
  );
}

// ── Family history view ──
function FamilyHistoryView({ data }) {
  if (!data || data.length === 0) {
    return (
      <p className="pr-empty">No family history recorded. Click Edit to add.</p>
    );
  }
  return (
    <div className="pr-family-list">
      {data.map((fm, i) => (
        <div key={i} className="pr-family-item">
          <div className="pr-family-header">
            <strong>
              {fm.relation
                ? fm.relation.charAt(0).toUpperCase() + fm.relation.slice(1)
                : ""}
            </strong>
            {fm.name && <span className="pr-family-name">({fm.name})</span>}
            <span
              className={`pr-family-status ${fm.alive ? "alive" : "deceased"}`}
            >
              {fm.alive ? "Alive" : "Deceased"}{" "}
              {fm.age_or_age_at_death ? `· age ${fm.age_or_age_at_death}` : ""}
            </span>
          </div>
          {(fm.conditions || []).length > 0 && (
            <div className="pr-family-conditions">
              {(fm.conditions || []).map((c) => (
                <span key={c} className="pr-condition-chip">
                  {c}
                </span>
              ))}
            </div>
          )}
          {!fm.alive && fm.cause_of_death && (
            <div className="pr-family-meta">
              Cause of death: {fm.cause_of_death}
            </div>
          )}
          {fm.notes && <div className="pr-family-meta">{fm.notes}</div>}
        </div>
      ))}
    </div>
  );
}

// ── Family history editor ──
function FamilyHistoryEditor({ data, onChange }) {
  const update = (i, field, value) => {
    onChange(data.map((f, idx) => (idx === i ? { ...f, [field]: value } : f)));
  };
  const toggleCond = (i, c) => {
    onChange(
      data.map((f, idx) => {
        if (idx !== i) return f;
        const has = (f.conditions || []).includes(c);
        return {
          ...f,
          conditions: has
            ? f.conditions.filter((x) => x !== c)
            : [...(f.conditions || []), c],
        };
      }),
    );
  };
  const add = () =>
    onChange([...data, { relation: "", alive: true, conditions: [] }]);
  const remove = (i) => onChange(data.filter((_, idx) => idx !== i));

  return (
    <div>
      {data.length === 0 && (
        <p className="pr-empty-sm">No relatives yet. Click + Add.</p>
      )}
      {data.map((fm, i) => (
        <div key={i} className="pr-family-edit-card">
          <div className="pr-family-edit-header">
            <strong>Relative #{i + 1}</strong>
            <button
              className="btn-remove btn-remove-sm"
              onClick={() => remove(i)}
            >
              ×
            </button>
          </div>
          <div className="pr-editor-grid">
            <PRSelect
              label="Relation"
              value={fm.relation || ""}
              options={["", ...PR_FAMILY_RELATIONS]}
              onChange={(v) => update(i, "relation", v)}
            />
            <PRInput
              label="Name"
              value={fm.name || ""}
              onChange={(v) => update(i, "name", v)}
            />
            <PRInput
              label="Age / age at death"
              value={fm.age_or_age_at_death || ""}
              onChange={(v) => update(i, "age_or_age_at_death", v)}
            />
            <div className="pr-check">
              <label>
                <input
                  type="checkbox"
                  checked={!!fm.alive}
                  onChange={(e) => update(i, "alive", e.target.checked)}
                />{" "}
                Alive
              </label>
            </div>
            {!fm.alive && (
              <PRInput
                label="Cause of death"
                value={fm.cause_of_death || ""}
                onChange={(v) => update(i, "cause_of_death", v)}
                wide
              />
            )}
          </div>
          <div className="pr-cond-picker">
            <label>Known conditions</label>
            <div className="conditions-grid">
              {PR_HEREDITARY_CONDITIONS.map((c) => (
                <label
                  key={c}
                  className={`condition-chip ${(fm.conditions || []).includes(c) ? "condition-chip--selected" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={(fm.conditions || []).includes(c)}
                    onChange={() => toggleCond(i, c)}
                    style={{ display: "none" }}
                  />
                  {c}
                </label>
              ))}
            </div>
          </div>
        </div>
      ))}
      <button className="btn-add-row" onClick={add}>
        + Add Relative
      </button>
    </div>
  );
}

// ── Medical history view ──
function MedicalHistoryView({ data }) {
  const d = data || {};
  const sections = [
    [
      "Current Conditions",
      d.current_conditions,
      (x) => `${x.label || x.name} ${x.year ? `(${x.year})` : ""}`,
    ],
    [
      "Past Conditions",
      d.past_conditions,
      (x) => `${x.label || x.name} ${x.year ? `(${x.year})` : ""}`,
    ],
    [
      "Surgeries",
      d.surgeries,
      (x) => `${x.label || x.name} ${x.year ? `(${x.year})` : ""}`,
    ],
    [
      "Allergies",
      d.allergies,
      (x) =>
        `${x.label || x.substance}${x.severity ? ` — ${x.severity}` : ""}${x.reaction ? ` (${x.reaction})` : ""}`,
    ],
    [
      "Medications",
      d.medications,
      (x) =>
        `${x.label || x.name}${x.dose ? ` ${x.dose}` : ""}${x.purpose ? ` — ${x.purpose}` : ""}`,
    ],
    [
      "Immunizations",
      d.immunizations,
      (x) => `${x.label || x.name} ${x.year ? `(${x.year})` : ""}`,
    ],
  ];
  const hasAny = sections.some(([, items]) => (items || []).length > 0);
  if (!hasAny)
    return (
      <p className="pr-empty">
        No medical history recorded. Click Edit to add.
      </p>
    );
  return (
    <div className="pr-mh-grid">
      {sections.map(
        ([title, items, fmt]) =>
          (items || []).length > 0 && (
            <div key={title} className="pr-mh-section">
              <div className="pr-mh-title">{title}</div>
              <ul className="pr-mh-list">
                {items.map((it, i) => (
                  <li key={i}>{fmt(it)}</li>
                ))}
              </ul>
            </div>
          ),
      )}
    </div>
  );
}

// ── Medical history editor ──
function MedicalHistoryEditor({ data, onChange }) {
  const buckets = [
    {
      key: "current_conditions",
      title: "Current Conditions",
      fields: [
        ["name", "Condition"],
        ["onset_year", "Year"],
        ["notes", "Notes"],
      ],
    },
    {
      key: "past_conditions",
      title: "Past Conditions",
      fields: [
        ["name", "Condition"],
        ["onset_year", "Year"],
        ["notes", "Notes"],
      ],
    },
    {
      key: "surgeries",
      title: "Surgeries",
      fields: [
        ["name", "Procedure"],
        ["year", "Year"],
        ["notes", "Notes"],
      ],
    },
    {
      key: "allergies",
      title: "Allergies",
      fields: [
        ["substance", "Substance"],
        ["severity", "Severity"],
        ["reaction", "Reaction"],
      ],
    },
    {
      key: "medications",
      title: "Medications",
      fields: [
        ["name", "Medication"],
        ["dose", "Dose"],
        ["purpose", "Purpose"],
      ],
    },
    {
      key: "immunizations",
      title: "Immunizations",
      fields: [
        ["name", "Vaccine"],
        ["year", "Year"],
      ],
    },
  ];

  const addRow = (key) =>
    onChange({ ...data, [key]: [...(data[key] || []), {}] });
  const delRow = (key, i) =>
    onChange({
      ...data,
      [key]: (data[key] || []).filter((_, idx) => idx !== i),
    });
  const updRow = (key, i, f, v) =>
    onChange({
      ...data,
      [key]: (data[key] || []).map((row, idx) =>
        idx === i ? { ...row, [f]: v } : row,
      ),
    });

  return (
    <div>
      {buckets.map((b) => (
        <div key={b.key} className="pr-mh-editor">
          <div className="pr-mh-editor-title">{b.title}</div>
          {(data[b.key] || []).map((row, i) => (
            <div key={i} className="pr-mh-row">
              {b.fields.map(([fname, flabel]) => (
                <div key={fname} className="form-group">
                  <label>{flabel}</label>
                  <input
                    type="text"
                    value={row[fname] || ""}
                    onChange={(e) => updRow(b.key, i, fname, e.target.value)}
                  />
                </div>
              ))}
              <button
                className="btn-remove btn-remove-sm"
                onClick={() => delRow(b.key, i)}
              >
                ×
              </button>
            </div>
          ))}
          <button className="btn-add-row" onClick={() => addRow(b.key)}>
            + Add {b.title}
          </button>
        </div>
      ))}
    </div>
  );
}

// ── Tiny input/select helpers ──
function PRInput({ label, value, onChange, type = "text", wide = false }) {
  return (
    <div className={`form-group ${wide ? "pr-editor-wide" : ""}`}>
      <label>{label}</label>
      <input
        type={type}
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function PRSelect({ label, value, options, onChange }) {
  return (
    <div className="form-group">
      <label>{label}</label>
      <select value={value || ""} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o || "Select"}
          </option>
        ))}
      </select>
    </div>
  );
}

export default MemberDetails; 
