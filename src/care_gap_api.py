"""
REST API endpoints for Care Gap workflows.
Run: python -m src.care_gap_api
"""
import json
import logging
import time as _time_mod
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from src.care_gap_data_loader import load_all
from src.care_gap_agents import CareGapAgentSystem
from src.care_gap_neo4j import (
    get_member_open_gaps, get_member_profile, get_measure_comprehensive,
    get_member_claims_cpt_codes, check_member_exclusions,
    get_member_extended_profile, merge_lifestyle,
    replace_family_history, replace_medical_history,
)
from src.neo4j_connection import get_knowledge_graph, get_reference_graph

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend
agent_system = None
logger = logging.getLogger(__name__)


def get_agents():
    global agent_system
    if agent_system is None:
        agent_system = CareGapAgentSystem()
    return agent_system


def _send_email_with_retry(client, message, max_retries=4):
    """Send email via Azure Communication Services with retry on rate-limiting."""
    for attempt in range(max_retries):
        try:
            poller = client.begin_send(message)
            return poller.result()
        except Exception as exc:
            if "TooManyRequests" in str(exc) and attempt < max_retries - 1:
                wait = max(1, (attempt + 1) * 2)
                logger.warning(f"[EMAIL] Rate limited (attempt {attempt + 1}/{max_retries}), retrying in {wait}s")
                _time_mod.sleep(wait)
            else:
                raise


@app.route("/api/v1/care-gaps/load-data", methods=["POST"])
def load_data():
    """Load/reload Excel data into Neo4j. Safe to call multiple times (MERGE)."""
    try:
        load_all()
        return jsonify({"status": "success", "message": "Data loaded into Neo4j"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/care-gaps/validate/<member_id>", methods=["POST"])
def validate_member(member_id):
    """
    Run full care gap validation for a member.
    - Checks QualityMeasures golden reference
    - Validates claims against lookback window + CPT codes
    - Auto-creates CareGap nodes for detected gaps
    - Returns agent suggestions for outreach
    """
    try:
        result = get_agents().validate_and_suggest(member_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/care-gaps/<member_id>", methods=["GET"])
def get_open_gaps(member_id):
    """Get all open care gaps for a member with resolution guides from golden reference."""
    try:
        gaps = get_member_open_gaps(member_id)
        profile = get_member_profile(member_id)
        return jsonify({"member_id": member_id, "profile": profile, "open_gaps": gaps})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members", methods=["GET"])
def get_all_members():
    """Get all members with their care gap status and outreach info."""
    try:
        kg = get_knowledge_graph()
        members = kg.run_query("""
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m,
                 count(DISTINCT CASE WHEN g.is_open = true  THEN g.care_gap_id ELSE null END) AS open_gaps,
                 count(DISTINCT CASE WHEN g.is_open = false THEN g.care_gap_id ELSE null END) AS closed_gaps
            OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
            OPTIONAL MATCH (o:Outreach)-[:CONTACTS]->(m)
            WITH m, open_gaps, closed_gaps, p,
                 count(DISTINCT o) AS outreach_count,
                 max(o.date) AS last_outreach_date
            OPTIONAL MATCH (m)-[:HAS_APPOINTMENT]->(a:Appointment)
            WITH m, open_gaps, closed_gaps, p, outreach_count, last_outreach_date,
                 count(DISTINCT a) AS appointment_count
            RETURN m.member_id as member_id,
                   m.name as name,
                   m.age_str as age,
                   m.gender as gender,
                   m.dob as dob,
                   open_gaps,
                   closed_gaps,
                   p.name as pcp_name,
                   p.provider_id as pcp_id,
                   outreach_count,
                   last_outreach_date,
                   appointment_count
            ORDER BY open_gaps DESC, m.name
        """, {})
        return jsonify({"members": members, "total": len(members)})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/details", methods=["GET"])
def get_member_details(member_id):
    """Get comprehensive member details including profile, gaps, claims, and outreach."""
    try:
        from src.care_gap_agents import detect_care_gaps
        kg = get_knowledge_graph()

        # Only run gap detection if member has no closed gaps yet.
        # Once a gap is closed via a claim, detect_care_gaps would re-open it
        # because the claim's CPT code may not match the full lookback check.
        # The claim created by close_care_gap_with_claim already marks is_open=false
        # so we trust that state and skip re-detection for members with closed gaps.
        closed_count = kg.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = false AND g.claim_id IS NOT NULL
            RETURN count(g) AS cnt
        """, {"mid": member_id})
        if not closed_count or closed_count[0]["cnt"] == 0:
            detect_care_gaps(member_id)

        # Get member profile
        profile = get_member_profile(member_id)
        
        # Get care gaps
        gaps = get_member_open_gaps(member_id)
        
        # Get all claims
        claims = get_member_claims_cpt_codes(member_id)
        
        # Get outreach history
        outreach = kg.run_query("""
            MATCH (o:Outreach)-[:CONTACTS]->(m:Member {member_id: $member_id})
            OPTIONAL MATCH (o)-[:TARGETS]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            RETURN o.outreach_id as outreach_id,
                   o.channel as channel,
                   o.date as date,
                   o.status as status,
                   o.care_manager_id as care_manager_id,
                   g.care_gap_id as care_gap_id,
                   q.measure_id as measure_id,
                   q.name as measure_name
            ORDER BY o.date DESC
        """, {"member_id": member_id})
        
        # Get closed gaps — include claim info so the UI can show claim_id and codes
        closed_gaps = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            WHERE g.is_open = false
            OPTIONAL MATCH (c:Claim {claim_id: g.claim_id})
            RETURN g.care_gap_id  as care_gap_id,
                   g.closed_on    as closed_on,
                   g.claim_id     as claim_id,
                   q.measure_id   as measure_id,
                   q.name         as measure_name,
                   c.cpt_code     as cpt_code,
                   c.icd_code     as icd_code,
                   c.service_date as service_date
            ORDER BY g.closed_on DESC
        """, {"member_id": member_id})
        
        # Load appointments so frontend can restore booking state after refresh
        appointments = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})-[:HAS_APPOINTMENT]->(a:Appointment)
            OPTIONAL MATCH (m)-[:ENROLLED_IN]->(b:BenefitPlan)
            OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
            RETURN a.appointment_id   AS appointment_id,
                   a.measure_id        AS measure_id,
                   a.appointment_date  AS appointment_date,
                   a.appointment_time  AS appointment_time,
                   a.lab_number        AS lab_number,
                   a.lab_specialist    AS lab_specialist,
                   a.lab_location      AS lab_location,
                   a.screening_name    AS screening_name,
                   a.cpt_codes         AS cpt_codes,
                   a.icd_codes         AS icd_codes,
                   a.status            AS status,
                   a.care_gap_id       AS care_gap_id,
                   m.email             AS member_email,
                   m.name              AS member_name,
                   b.plan_id           AS plan_id,
                   m.insurance_type    AS insurance_type,
                   p.name              AS pcp_name
            ORDER BY a.appointment_date DESC
        """, {"member_id": member_id})

        # Extended patient record (lifestyle / family history / medical history)
        extended = get_member_extended_profile(member_id)

        return jsonify({
            "member_id": member_id,
            "profile": profile,
            "open_gaps": gaps,
            "closed_gaps": closed_gaps,
            "claims": claims,
            "outreach_history": outreach,
            "appointments": appointments,
            "lifestyle": extended.get("lifestyle", {}),
            "family_history": extended.get("family_history", []),
            "medical_history": extended.get("medical_history", {}),
            "hereditary_risks": extended.get("hereditary_risks", []),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/lifestyle", methods=["PUT"])
def update_member_lifestyle(member_id):
    """Upsert lifestyle record for an existing member."""
    try:
        data = request.json or {}
        merge_lifestyle(member_id, data)
        return jsonify({"status": "success", "member_id": member_id})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/family-history", methods=["PUT"])
def update_member_family_history(member_id):
    """Replace family-history entries for an existing member."""
    try:
        data = request.json or {}
        entries = data.get("family_members", data if isinstance(data, list) else [])
        if isinstance(data, list):
            entries = data
        replace_family_history(member_id, entries or [])
        return jsonify({"status": "success", "member_id": member_id, "count": len(entries or [])})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/medical-history", methods=["PUT"])
def update_member_medical_history(member_id):
    """Replace medical-history entries for an existing member."""
    try:
        data = request.json or {}
        replace_medical_history(member_id, data)
        return jsonify({"status": "success", "member_id": member_id})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/patient-record", methods=["GET"])
def get_member_patient_record(member_id):
    """Return the extended patient record (lifestyle + family + medical) alone."""
    try:
        return jsonify({
            "status": "success",
            "member_id": member_id,
            **get_member_extended_profile(member_id),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/dashboard/stats", methods=["GET"])
def get_dashboard_stats():
    """Get dashboard statistics."""
    try:
        kg = get_knowledge_graph()
        
        # Total members
        total_members = kg.run_query("MATCH (m:Member) RETURN count(m) as count", {})[0]["count"]
        
        # Members with open gaps
        members_with_gaps = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            RETURN count(DISTINCT m) as count
        """, {})[0]["count"]
        
        # Members without gaps (compliant)
        compliant_members = total_members - members_with_gaps
        
        # Total open gaps — count distinct (member, measure) pairs to avoid
        # double-counting when both an Excel-loaded gap and an AUTO- gap exist
        # for the same member+measure.  Use g.measure_id (stored on the node)
        # so this works even when the RELATES_TO→QualityMeasure link is absent.
        total_open_gaps = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            RETURN count(DISTINCT m.member_id + '|' + coalesce(g.measure_id, g.care_gap_id)) as count
        """, {})[0]["count"]

        # Gaps by measure — count distinct members per measure.
        # Prefer RELATES_TO for name; fall back to g.measure_id for the ID.
        gaps_by_measure = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            OPTIONAL MATCH (g)-[:RELATES_TO]->(q:QualityMeasure)
            WITH coalesce(g.measure_id, q.measure_id, 'UNKNOWN') AS measure_id,
                 coalesce(q.name, g.measure_id, 'Unknown Measure')  AS measure_name,
                 m.member_id AS member_id
            RETURN measure_id, measure_name,
                   count(DISTINCT member_id) as gap_count
            ORDER BY gap_count DESC
        """, {})
        
        # Recent outreach
        recent_outreach = kg.run_query("""
            MATCH (o:Outreach)
            RETURN count(o) as total_outreach,
                   count(CASE WHEN o.status = 'Completed' THEN 1 END) as completed,
                   count(CASE WHEN o.status = 'Scheduled' THEN 1 END) as scheduled
        """, {})[0]
        
        return jsonify({
            "total_members": total_members,
            "members_with_gaps": members_with_gaps,
            "compliant_members": compliant_members,
            "total_open_gaps": total_open_gaps,
            "gaps_by_measure": gaps_by_measure,
            "outreach_stats": recent_outreach
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/chat/send", methods=["POST"])
def send_chat_message():
    """Send chat message to member (simulated for now)."""
    try:
        data = request.json
        member_id = data.get("member_id")
        message = data.get("message")
        sender = data.get("sender", "care_manager")
        
        # In production, this would integrate with SMS/Email service
        # For now, we'll just log and return success
        logger.info(f"Chat message to {member_id}: {message}")
        
        return jsonify({
            "status": "success",
            "message": "Message sent successfully",
            "timestamp": "2025-01-15T10:30:00Z"
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


def _get_hedis_codes(measure_id: str):
    """
    Return the single primary CPT code and primary ICD-10 code for a measure.
    Uses primary_cpt and primary_icd10 fields from the golden reference.
    These are the specific codes used for appointment booking and claim creation.
    """
    from src.hedis_golden_reference import HEDIS_MEASURES
    mdata = HEDIS_MEASURES.get(measure_id, {})
    cpt_code = mdata.get("primary_cpt", "")
    icd_code = mdata.get("primary_icd10", "")
    return cpt_code, icd_code


@app.route("/api/v1/appointments/book", methods=["POST"])
def book_appointment():
    """
    Book a screening appointment:
    - Assigns lab number and specialist by measure type
    - Persists an Appointment node in Neo4j
    - Sends a professional medical invitation email via ACS to the member
    """
    try:
        from src.care_gap_neo4j import merge_appointment, get_appointment
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg
        import uuid
        from datetime import datetime

        data = request.json or {}
        member_id    = data.get("member_id", "")
        measure_id   = data.get("measure_id", "")
        measure_name = data.get("measure_name", measure_id)
        appt_date    = data.get("appointment_date", "")
        appt_time    = data.get("appointment_time", "09:00")
        provider_id  = data.get("provider_id", "")
        care_gap_id  = data.get("care_gap_id", "")

        if not all([member_id, measure_id, appt_date]):
            return jsonify({"status": "error", "error": "member_id, measure_id and appointment_date are required"}), 400

        # ── Lab assignment by measure ─────────────────────────────────────
        LAB_MAP = {
            "BCS": {"lab_number": "LAB-02", "lab_specialist": "Dr. Sarah Mitchell",
                    "lab_location": "Radiology & Mammography Unit, 2nd Floor",
                    "specialty": "Diagnostic Radiology"},
            "CCS": {"lab_number": "LAB-01", "lab_specialist": "Dr. James Rodriguez",
                    "lab_location": "Cytology & Gynecology Lab, 1st Floor",
                    "specialty": "Gynecologic Oncology"},
            "COL": {"lab_number": "LAB-03", "lab_specialist": "Dr. Emily Chen",
                    "lab_location": "Gastroenterology & Endoscopy Suite, 3rd Floor",
                    "specialty": "Gastroenterology"},
            "CBP": {"lab_number": "LAB-04", "lab_specialist": "Dr. Michael Thompson",
                    "lab_location": "Cardiology Clinic, 4th Floor",
                    "specialty": "Cardiology"},
            "CDC": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                    "lab_location": "Diabetes & Endocrinology Center, 2nd Floor",
                    "specialty": "Endocrinology"},
            "KED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                    "lab_location": "Renal & Nephrology Lab, 2nd Floor",
                    "specialty": "Nephrology"},
            "LSC": {"lab_number": "LAB-04", "lab_specialist": "Dr. Michael Thompson",
                    "lab_location": "Internal Medicine Lab, 4th Floor",
                    "specialty": "Internal Medicine"},
        }
        lab_info = LAB_MAP.get(measure_id, {
            "lab_number": "LAB-01", "lab_specialist": "On-Call Specialist",
            "lab_location": "General Screening Lab, 1st Floor",
            "specialty": "General Medicine",
        })

        # ── CPT / ICD codes from HEDIS golden reference (Python dict) ───────
        # _get_hedis_codes reads directly from HEDIS_MEASURES (ground truth),
        # covering both top-level 'codes' dict and screening_options for
        # multi-path measures (COL, CCS).  No Neo4j round-trip needed.
        cpt_codes, icd_codes = _get_hedis_codes(measure_id)

        # ── Persist to Neo4j ─────────────────────────────────────────────
        appointment_id = f"APT-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
        merge_appointment(
            appointment_id=appointment_id,
            member_id=member_id,
            measure_id=measure_id,
            appointment_date=appt_date,
            appointment_time=appt_time,
            lab_number=lab_info["lab_number"],
            lab_specialist=lab_info["lab_specialist"],
            lab_location=lab_info["lab_location"],
            screening_name=measure_name,
            cpt_codes=cpt_codes,
            icd_codes=icd_codes,
            provider_id=provider_id,
            care_gap_id=care_gap_id,
        )

        appt = get_appointment(appointment_id)

        # ── Format date/time for email ────────────────────────────────────
        try:
            dt = datetime.strptime(appt_date, "%Y-%m-%d")
            friendly_date = dt.strftime("%A, %B %d, %Y")
        except Exception:
            friendly_date = appt_date
        try:
            hh, mm = appt_time.split(":")
            h = int(hh)
            ampm = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            friendly_time = f"{h12}:{mm} {ampm}"
        except Exception:
            friendly_time = appt_time

        member_email = (appt or {}).get("member_email", "")
        member_name  = (appt or {}).get("member_name", member_id)
        plan_id      = (appt or {}).get("plan_id", "N/A")
        insurance    = (appt or {}).get("insurance_type", "Commercial")
        pcp_name     = (appt or {}).get("pcp_name", "Your Provider")

        # ── Send professional email (member-facing, no backend info) ─────
        if member_email and cfg.azure_communication_connection_string:
            sender = cfg.azure_communication_sender
            subject = f"Appointment Confirmation: {measure_name} — {friendly_date}"
            body_html = f"""
<html><body style="font-family: Arial, sans-serif; color: #1a1a2e; max-width:680px; margin:auto;">
<div style="background:#0033A1; padding:20px 32px; border-radius:8px 8px 0 0;">
  <h1 style="color:white; margin:0; font-size:22px;">HealthCare Management Portal</h1>
  <p style="color:#b3c7f7; margin:4px 0 0;">Appointment Confirmation</p>
</div>
<div style="border:1px solid #dce3f5; border-top:none; padding:32px; border-radius:0 0 8px 8px;">
  <p style="font-size:16px;">Dear <strong>{member_name}</strong>,</p>
  <p>Your screening appointment has been successfully scheduled. Please review the details below and keep this email for your records.</p>

  <table style="width:100%; border-collapse:collapse; margin:24px 0; background:#f0f4ff; border-radius:6px; overflow:hidden;">
    <tr style="background:#0033A1; color:white;">
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">Appointment Details</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">Screening</td><td style="padding:10px 16px;">{measure_name}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Date</td><td style="padding:10px 16px;">{friendly_date}</td></tr>
    <tr><td style="padding:10px 16px; font-weight:600;">Time</td><td style="padding:10px 16px;">{friendly_time}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Confirmation #</td><td style="padding:10px 16px;">{appointment_id}</td></tr>
  </table>

  <table style="width:100%; border-collapse:collapse; margin:24px 0; background:#f0f4ff; border-radius:6px; overflow:hidden;">
    <tr style="background:#005EB8; color:white;">
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">Where to Go</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">Location</td><td style="padding:10px 16px;">{lab_info['lab_location']}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Specialist</td><td style="padding:10px 16px;">{lab_info['lab_specialist']}</td></tr>
    <tr><td style="padding:10px 16px; font-weight:600;">Referring Provider</td><td style="padding:10px 16px;">{pcp_name}</td></tr>
  </table>

  <table style="width:100%; border-collapse:collapse; margin:24px 0; background:#f0f4ff; border-radius:6px; overflow:hidden;">
    <tr style="background:#1a6b3c; color:white;">
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">Your Coverage</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">Insurance</td><td style="padding:10px 16px;">{insurance}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Preventive screenings are typically covered at no cost under your plan.</td></tr>
  </table>

  <div style="background:#fff8e1; border-left:4px solid #f59e0b; padding:16px; border-radius:4px; margin:24px 0;">
    <strong>Before Your Visit:</strong>
    <ul style="margin:8px 0; padding-left:20px; color:#555;">
      <li>Please arrive 15 minutes before your scheduled time.</li>
      <li>Bring a valid photo ID and your insurance card.</li>
      <li>Wear comfortable, loose-fitting clothing.</li>
      <li>To reschedule, contact us at least 24 hours in advance.</li>
    </ul>
  </div>

  <p style="color:#555;">If you have any questions, please contact your care management team.</p>
  <hr style="border:none; border-top:1px solid #dce3f5; margin:24px 0;">
  <p style="color:#888; font-size:12px;">This is an automated message from the HealthCare Management Portal.</p>
</div>
</body></html>"""

            try:
                client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
                message = {
                    "senderAddress": sender,
                    "recipients": {"to": [{"address": member_email}]},
                    "content": {"subject": subject, "html": body_html},
                }
                _send_email_with_retry(client, message)
                logger.info(f"Appointment email sent to {member_email} for {appointment_id}")
            except Exception as email_err:
                logger.warning(f"Email send failed for {appointment_id}: {email_err}")

        # Persist appointment email in Neo4j so it appears in Outreach History
        if member_email:
            from src.care_gap_neo4j import merge_email
            from datetime import datetime as _dt
            import uuid as _uuid2
            email_id = f"APPT-EMAIL-{appointment_id}"
            # Store a plain-text summary as body (HTML stored separately)
            plain_body = (
                f"Appointment Confirmation: {measure_name}\n"
                f"Date: {friendly_date} at {friendly_time}\n"
                f"Location: {lab_info['lab_location']}\n"
                f"Specialist: {lab_info['lab_specialist']}\n"
                f"Confirmation #: {appointment_id}"
            )
            merge_email(
                email_id=email_id,
                member_id=member_id,
                subject=f"Appointment Confirmation: {measure_name} - {friendly_date}",
                body=plain_body,
                from_email=cfg.azure_communication_sender if cfg.azure_communication_connection_string else "system@healthportal.com",
                to_email=member_email,
                timestamp=_dt.now().isoformat(),
                direction="sent",
                is_read=True,
            )
            # Also store the HTML body on the email node for rich preview
            from src.neo4j_connection import get_knowledge_graph as _gkg2
            _gkg2().execute_write(
                "MATCH (e:Email {email_id: $eid}) SET e.html_body = $html, "
                "e.email_type = 'appointment_confirmation', e.appointment_id = $appt_id, "
                "e.measure_id = $mid, e.care_gap_id = $cgid",
                {"eid": email_id, "html": body_html, "appt_id": appointment_id,
                 "mid": measure_id, "cgid": care_gap_id}
            )

        # ── Sync: appointment booked in persona DB ──────────────
        if care_gap_id:
            try:
                from src.persona_sync import sync_appointment_booked
                logger.info(f"[BOOK] Syncing appointment to persona DB: member={member_id}, gap={care_gap_id}, appt={appointment_id}")
                sync_appointment_booked(
                    member_id=member_id, care_gap_id=care_gap_id,
                    appointment_id=appointment_id,
                    appointment_date=friendly_date,
                    lab_location=lab_info["lab_location"],
                )
            except Exception as e:
                logger.error(f"[BOOK] Persona sync failed for gap {care_gap_id}: {e}")
        else:
            logger.warning(f"[BOOK] No care_gap_id provided — skipping persona sync for {member_id}/{measure_id}")

        # ── Send WhatsApp appointment confirmation ─────────────────
        whatsapp_sent = False
        member_phone = (appt or {}).get("member_phone", "")
        if member_phone:
            try:
                from src.whatsapp_service import send_appointment_confirmation
                wa_result = send_appointment_confirmation(
                    to_phone=member_phone,
                    member_name=member_name,
                    measure_name=measure_name,
                    appointment_date=friendly_date,
                    appointment_time=friendly_time,
                    appointment_id=appointment_id,
                    lab_location=lab_info["lab_location"],
                    lab_specialist=lab_info["lab_specialist"],
                )
                whatsapp_sent = wa_result.get("success", False)
                if whatsapp_sent:
                    logger.info(f"WhatsApp appointment confirmation sent for {appointment_id}")
                else:
                    logger.warning(f"WhatsApp send failed for {appointment_id}: {wa_result.get('error', 'unknown')}")
            except Exception as wa_err:
                logger.warning(f"WhatsApp send failed for {appointment_id}: {wa_err}")

        return jsonify({
            "status": "success",
            "appointment_id": appointment_id,
            "care_gap_id": care_gap_id,
            "lab_number": lab_info["lab_number"],
            "lab_specialist": lab_info["lab_specialist"],
            "lab_location": lab_info["lab_location"],
            "specialty": lab_info["specialty"],
            "cpt_codes": cpt_codes,
            "icd_codes": icd_codes,
            "appointment_date": appt_date,
            "appointment_time": appt_time,
            "member_email": member_email,
            "email_sent": bool(member_email),
            "whatsapp_sent": whatsapp_sent,
        })
    except Exception as e:
        logger.error(f"book_appointment error: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/appointments/<appointment_id>", methods=["GET"])
def get_appointment_details(appointment_id):
    """Retrieve full appointment record including plan and member info."""
    try:
        from src.care_gap_neo4j import get_appointment
        appt = get_appointment(appointment_id)
        if not appt:
            return jsonify({"status": "error", "error": "Appointment not found"}), 404
        return jsonify(appt)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    """
    Mark screening as completed:
    - Generates a Claim node in Neo4j
    - Closes the linked CareGap (is_open=false)
    """
    try:
        from src.care_gap_neo4j import get_appointment, close_care_gap_with_claim
        import uuid
        from datetime import date

        data = request.json or {}
        care_gap_id = data.get("care_gap_id", "")

        appt = get_appointment(appointment_id)
        if not appt:
            return jsonify({"status": "error", "error": "Appointment not found"}), 404

        service_date = appt.get("appointment_date", str(date.today()))
        claim_id = f"CLM-{appt['member_id']}-{appt['measure_id']}-{uuid.uuid4().hex[:8].upper()}"

        # Use primary codes from golden reference — always single specific codes
        cpt_code, icd_code = _get_hedis_codes(appt["measure_id"])
        # Override with member's actual ICD from the gap node if available
        gap_icd = ""
        if care_gap_id:
            kg = get_knowledge_graph()
            gap_rows = kg.run_query("""
                MATCH (g:CareGap {care_gap_id: $gid})
                RETURN g.primary_icd10 AS icd
            """, {"gid": care_gap_id})
            if gap_rows and gap_rows[0].get("icd"):
                gap_icd = gap_rows[0]["icd"]
        if gap_icd:
            icd_code = gap_icd

        close_care_gap_with_claim(
            care_gap_id=care_gap_id,
            member_id=appt["member_id"],
            measure_id=appt["measure_id"],
            provider_id=appt.get("provider_id", ""),
            cpt_code=cpt_code,
            icd_code=icd_code,
            service_date=service_date,
            claim_id=claim_id,
            plan_id=appt.get("plan_id", ""),
        )

        # Mark appointment as completed
        from src.care_gap_neo4j import merge_outreach
        import uuid as _uuid
        kg = get_knowledge_graph()
        kg.execute_write("""
            MATCH (a:Appointment {appointment_id: $appt_id})
            SET a.status = 'Completed'
        """, {"appt_id": appointment_id})

        # Create an Outreach record for this completed screening so the
        # dashboard "Outreach Activity" count increases when a gap is closed.
        outreach_id = f"OUT-{appt['member_id']}-{appt['measure_id']}-{_uuid.uuid4().hex[:6].upper()}"
        merge_outreach(
            outreach_id=outreach_id,
            care_gap_id=care_gap_id,
            member_id=appt["member_id"],
            care_manager_id="SYSTEM",
            channel="Appointment",
            date=service_date,
            status="Completed",
        )

        # Check if the member is now fully compliant (no more open gaps)
        remaining = kg.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            RETURN count(g) AS cnt
        """, {"mid": appt["member_id"]})[0]["cnt"]
        is_now_compliant = (remaining == 0)

        # Sync: gap closed in persona DB
        if care_gap_id:
            try:
                from src.persona_sync import sync_gap_closed
                logger.info(f"[COMPLETE] Syncing gap closure to persona DB: member={appt['member_id']}, gap={care_gap_id}")
                sync_gap_closed(member_id=appt["member_id"],
                                care_gap_id=care_gap_id)
            except Exception as e:
                logger.error(f"[COMPLETE] Persona sync failed for gap {care_gap_id}: {e}")
        else:
            logger.warning(f"[COMPLETE] No care_gap_id — skipping persona sync for {appointment_id}")

        return jsonify({
            "status":           "success",
            "claim_id":         claim_id,
            "care_gap_id":      care_gap_id,
            "cpt_codes":        cpt_code,
            "icd_codes":        icd_code,
            "is_now_compliant": is_now_compliant,
            "message":          "Screening completed and care gap closed" + (
                " — Member is now fully compliant!" if is_now_compliant else ""
            ),
        })
    except Exception as e:
        logger.error(f"complete_appointment error: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/measures/<measure_id>", methods=["GET"])
def get_measure_details(measure_id):
    """Get comprehensive measure details from golden reference."""
    try:
        measure = get_measure_comprehensive(measure_id)
        if not measure:
            return jsonify({"status": "error", "error": "Measure not found"}), 404
        return jsonify(measure)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/next-id", methods=["GET"])
def get_next_member_id_route():
    """Return the next available member ID based on existing graph members."""
    try:
        from src.care_gap_neo4j import get_next_member_id
        return jsonify({"status": "success", "next_id": get_next_member_id()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/add", methods=["POST"])
def add_member():
    """Add new member with complete details to Neo4j."""
    try:
        from src.care_gap_neo4j import merge_member, merge_enrollment
        data = request.json
        
        # Validate required fields
        required = ["member_id", "name", "dob", "gender", "pcp_id", "plan_id"]
        for field in required:
            if not data.get(field):
                return jsonify({"status": "error", "error": f"Missing required field: {field}"}), 400
        
        # Create member node
        merge_member(
            member_id=data["member_id"],
            name=data["name"],
            dob=data["dob"],
            gender=data["gender"],
            pcp_id=data["pcp_id"],
            zip_code=data.get("zip_code", ""),
            enrollment_start=data.get("enrollment_start", data["dob"]),
            enrollment_end=data.get("enrollment_end", "2025-12-31"),
            age_str=data.get("age_str", ""),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            street_address=data.get("street_address", ""),
            city=data.get("city", ""),
            state=data.get("state", ""),
            race=data.get("race", ""),
            language=data.get("language", "English"),
            tobacco_use=data.get("tobacco_use", False),
            insurance_type=data.get("insurance_type", "Commercial"),
            chronic_conditions=data.get("chronic_conditions", []),
        )
        
        # Ensure BenefitPlan node exists before creating enrollment
        from src.care_gap_neo4j import merge_benefit_plan
        merge_benefit_plan(
            plan_id=data["plan_id"],
            preventive_covered="All preventive services",
            copay=0,
            deductible=500,
            eligibility_rules="Standard eligibility",
        )
        # Create enrollment relationships
        merge_enrollment(
            member_id=data["member_id"],
            plan_id=data["plan_id"],
            pcp_id=data["pcp_id"],
            effective_from=data.get("enrollment_start", data["dob"]),
            effective_to=data.get("enrollment_end", "2025-12-31")
        )
        
        # Persist extended patient record if the caller supplied any of it.
        lifestyle_payload = data.get("lifestyle") or {}
        if lifestyle_payload:
            merge_lifestyle(data["member_id"], lifestyle_payload)

        family_payload = data.get("family_history") or []
        if family_payload:
            replace_family_history(data["member_id"], family_payload)

        medical_payload = data.get("medical_history") or {}
        if medical_payload:
            replace_medical_history(data["member_id"], medical_payload)

        # Auto-detect care gaps immediately based on chronic conditions —
        # no LLM, pure Python. Ensures the member shows correct gap count
        # in the list without requiring a manual "AI Suggestions" click first.
        from src.care_gap_agents import detect_care_gaps
        gap_result = detect_care_gaps(data["member_id"])

        return jsonify({
            "status": "success",
            "message": f"Member {data['member_id']} added successfully",
            "member_id": data["member_id"],
            "gaps_detected": gap_result.get("gaps_created", []),
            "compliant_measures": gap_result.get("compliant", []),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>", methods=["DELETE"])
def delete_member(member_id):
    """Delete a member and all their relationships from Neo4j."""
    try:
        kg = get_knowledge_graph()
        # Check member exists
        exists = kg.run_query(
            "MATCH (m:Member {member_id: $mid}) RETURN m.name as name",
            {"mid": member_id},
        )
        if not exists:
            return jsonify({"status": "error", "error": f"Member {member_id} not found"}), 404

        member_name = exists[0]["name"]

        # Delete the member node and ALL relationships (DETACH DELETE)
        kg.run_query(
            "MATCH (m:Member {member_id: $mid}) DETACH DELETE m",
            {"mid": member_id},
        )

        return jsonify({
            "status": "success",
            "message": f"Member {member_name} ({member_id}) deleted successfully",
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/providers/list", methods=["GET"])
def get_providers():
    """Get all providers for dropdown selection."""
    try:
        kg = get_knowledge_graph()
        providers = kg.run_query("""
            MATCH (p:Provider)
            RETURN p.provider_id as provider_id,
                   p.name as name,
                   p.specialty as specialty,
                   p.network_status as network_status
            ORDER BY p.name
        """, {})
        return jsonify({"providers": providers})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/<member_id>/compare", methods=["GET"])
def compare_member(member_id):
    """
    Compare a member's open gaps against similar members who CLOSED those same
    gaps — showing exactly how they closed them (CPT code, ICD code, claim, date).
    """
    try:
        from src.hedis_golden_reference import HEDIS_MEASURES
        kg = get_knowledge_graph()

        # Current member summary
        current_member = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m,
                 count(CASE WHEN g.is_open = true  THEN 1 END) AS open_gaps,
                 count(CASE WHEN g.is_open = false THEN 1 END) AS closed_gaps
            RETURN m.member_id AS member_id, m.name AS name, m.age_str AS age,
                   m.gender AS gender, m.dob AS dob,
                   m.chronic_conditions AS chronic_conditions,
                   open_gaps, closed_gaps
        """, {"member_id": member_id})

        if not current_member:
            return jsonify({"status": "error", "error": "Member not found"}), 404

        current = current_member[0]
        try:
            age = int(current["age"].split()[0]) if current["age"] else 0
        except (ValueError, AttributeError, IndexError):
            age = 0

        # Current member's open gaps with golden reference codes
        current_open_gaps = kg.run_query("""
            MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)
                  -[:RELATES_TO]->(q:QualityMeasure)
            WHERE g.is_open = true
            RETURN g.care_gap_id AS care_gap_id, q.measure_id AS measure_id,
                   q.name AS measure_name, q.description AS description,
                   q.lookback_months AS lookback_months, g.created_on AS created_on,
                   g.primary_cpt_code AS primary_cpt_code, g.primary_icd10 AS primary_icd10
        """, {"member_id": member_id})

        current_open_measure_ids = [g["measure_id"] for g in current_open_gaps]

        for gap in current_open_gaps:
            m_data = HEDIS_MEASURES.get(gap["measure_id"], {})
            gap["cpt_codes"]          = m_data.get("primary_cpt", gap.get("primary_cpt_code") or "N/A")
            gap["icd_codes"]          = m_data.get("primary_icd10", gap.get("primary_icd10") or "N/A")
            gap["best_practices"]     = m_data.get("best_practices", [])
            gap["numerator_criteria"] = m_data.get("numerator_criteria", "")

        # Find members who CLOSED the same measure gaps — the key fix.
        # Show their name, how they closed it (CPT, ICD, date, claim).
        better_performers_raw = []
        gap_closure_examples  = []

        if current_open_measure_ids:
            closers = kg.run_query("""
                MATCH (m2:Member)-[:HAS_CARE_GAP]->(g2:CareGap)
                      -[:RELATES_TO]->(q:QualityMeasure)
                WHERE q.measure_id IN $measure_ids
                  AND g2.is_open = false
                  AND m2.member_id <> $member_id
                  AND m2.gender = $gender
                OPTIONAL MATCH (c:Claim {claim_id: g2.claim_id})
                OPTIONAL MATCH (m2)-[:HAS_CARE_GAP]->(all_g:CareGap)
                WITH m2, q, g2, c,
                     count(CASE WHEN all_g.is_open = true  THEN 1 END) AS open_gaps,
                     count(CASE WHEN all_g.is_open = false THEN 1 END) AS closed_gaps
                RETURN m2.member_id AS member_id, m2.name AS name,
                       m2.age_str AS age, m2.gender AS gender,
                       q.measure_id AS measure_id, q.name AS measure_name,
                       g2.care_gap_id AS care_gap_id, g2.closed_on AS closed_on,
                       g2.claim_id AS claim_id,
                       c.cpt_code AS cpt_code, c.icd_code AS icd_code,
                       c.service_date AS service_date,
                       open_gaps, closed_gaps
                ORDER BY g2.closed_on DESC
            """, {"measure_ids": current_open_measure_ids,
                  "member_id": member_id, "gender": current["gender"]})

            seen_members  = set()
            seen_measures = set()
            for row in closers:
                try:
                    m_age = int(row["age"].split()[0]) if row.get("age") else 0
                except (ValueError, AttributeError, IndexError):
                    m_age = 0
                if abs(m_age - age) > 10:
                    continue

                if row["member_id"] not in seen_members:
                    seen_members.add(row["member_id"])
                    better_performers_raw.append({
                        "member_id":   row["member_id"],
                        "name":        row["name"],
                        "age":         row["age"],
                        "gender":      row["gender"],
                        "open_gaps":   row["open_gaps"],
                        "closed_gaps": row["closed_gaps"],
                    })

                if row["measure_id"] not in seen_measures:
                    seen_measures.add(row["measure_id"])
                    m_data   = HEDIS_MEASURES.get(row["measure_id"], {})
                    cpt_used = row["cpt_code"]  or m_data.get("primary_cpt", "N/A")
                    icd_used = row["icd_code"]  or m_data.get("primary_icd10", "N/A")
                    gap_closure_examples.append({
                        "measure_id":   row["measure_id"],
                        "measure_name": row["measure_name"],
                        "closed_by":    row["name"],
                        "member_id":    row["member_id"],
                        "closed_on":    row["closed_on"],
                        "claim_id":     row["claim_id"],
                        "cpt_code":     cpt_used,
                        "icd_code":     icd_used,
                        "service_date": row["service_date"],
                    })

        # Age/gender cohort for metrics
        all_similar = kg.run_query("""
            MATCH (m2:Member)
            WHERE m2.member_id <> $member_id AND m2.gender = $gender
            OPTIONAL MATCH (m2)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m2,
                 count(CASE WHEN g.is_open = true  THEN 1 END) AS open_gaps,
                 count(CASE WHEN g.is_open = false THEN 1 END) AS closed_gaps
            RETURN m2.member_id AS member_id, m2.age_str AS age,
                   open_gaps, closed_gaps
        """, {"member_id": member_id, "gender": current["gender"]})

        filtered_similar = []
        for m in all_similar:
            try:
                m_age = int(m["age"].split()[0]) if m.get("age") else 0
                if abs(m_age - age) <= 5:
                    filtered_similar.append(m)
            except (ValueError, AttributeError, IndexError):
                continue

        # Improvement guidelines from golden reference
        improvement_guidelines = []
        for gp in current_open_gaps:
            m_data = HEDIS_MEASURES.get(gp["measure_id"], {})
            improvement_guidelines.append({
                "measure_id":               gp["measure_id"],
                "measure_name":             gp["measure_name"],
                "best_practices":           m_data.get("best_practices", []),
                "acceptable_documentation": m_data.get("clinical_guidelines", {}).get("acceptable", []),
                "numerator_criteria":       m_data.get("numerator_criteria", ""),
            })

        # Metrics
        avg_open   = (sum(m["open_gaps"]   for m in filtered_similar) / len(filtered_similar)
                      if filtered_similar else 0)
        avg_closed = (sum(m["closed_gaps"] for m in filtered_similar) / len(filtered_similar)
                      if filtered_similar else 0)
        percentile = calculate_percentile(
            current["open_gaps"],
            [m["open_gaps"] for m in filtered_similar],
        )

        # Peers who closed same measures (for summary)
        shared_measure_summary = []
        if current_open_measure_ids:
            shared_rows = kg.run_query("""
                MATCH (q:QualityMeasure)
                WHERE q.measure_id IN $measure_ids
                OPTIONAL MATCH (m2:Member)-[:HAS_CARE_GAP]->(g2:CareGap)
                              -[:RELATES_TO]->(q)
                WHERE g2.is_open = false AND m2.member_id <> $member_id
                RETURN q.measure_id AS measure_id, q.name AS measure_name,
                       count(DISTINCT m2) AS peers_who_closed
                ORDER BY peers_who_closed DESC
            """, {"measure_ids": current_open_measure_ids, "member_id": member_id})
            shared_measure_summary = shared_rows

        return jsonify({
            "current_member":         current,
            "similar_members":        filtered_similar,
            "better_performers":      better_performers_raw,
            "current_gaps":           current_open_gaps,
            "gap_closure_examples":   gap_closure_examples,
            "improvement_guidelines": improvement_guidelines,
            "shared_measure_summary": shared_measure_summary,
            "comparison_metrics": {
                "current_open_gaps":       current["open_gaps"],
                "current_closed_gaps":     current["closed_gaps"],
                "avg_open_gaps_similar":   round(avg_open,   1),
                "avg_closed_gaps_similar": round(avg_closed, 1),
                "percentile_rank":         percentile,
                "total_similar_members":   len(filtered_similar),
                "better_performers_count": len(better_performers_raw),
            },
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500
def calculate_percentile(value, values_list):
    """Calculate percentile rank based on open gaps (lower gaps = higher percentile = better)."""
    if not values_list:
        return 100 if value == 0 else 50
    
    # Special case: if member has 0 open gaps, they're always top performer
    if value == 0:
        return 100
    
    # Count members with MORE open gaps (worse performance)
    worse_count = sum(1 for v in values_list if v > value)
    
    # Count members with SAME number of gaps
    same_count = sum(1 for v in values_list if v == value)
    
    # Percentile = (worse + 0.5*same) / total * 100
    # This gives mid-point ranking for ties
    percentile = ((worse_count + 0.5 * same_count) / len(values_list)) * 100
    
    return round(percentile)


@app.route("/api/v1/plans/list", methods=["GET"])
def get_plans():
    """Get all benefit plans for dropdown selection."""
    try:
        kg = get_knowledge_graph()
        plans = kg.run_query("""
            MATCH (b:BenefitPlan)
            RETURN b.plan_id as plan_id,
                   b.copay as copay,
                   b.deductible as deductible,
                   b.preventive_covered as preventive_covered
            ORDER BY b.plan_id
        """, {})
        return jsonify({"plans": plans})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/care-gaps/validate/<member_id>/stream", methods=["GET"])
def validate_member_stream(member_id):
    """
    SSE endpoint — streams per-agent results as each of the 6 agents finishes.
    Frontend connects via EventSource; each event carries a JSON payload.

    Event types: metadata | agent_start | agent_done | complete | error
    """
    def generate():
        try:
            for event_type, data in get_agents().validate_and_suggest_stream(member_id):
                yield f"data: {json.dumps({'type': event_type, 'payload': data})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'payload': {'message': str(exc)}})}\n\n"

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.route("/api/v1/chat/member/<member_id>", methods=["POST"])
def chat_with_member(member_id):
    """
    Conversational AI assistant that knows the specific member's data.
    Care managers can ask questions; the assistant answers using member context
    fetched fresh from Neo4j on every request.

    Body: { "message": str, "history": [{"role": "user"|"assistant", "content": str}] }
    """
    try:
        import boto3
        from config.settings import settings as cfg

        data = request.json or {}
        message = str(data.get("message", "")).strip()
        history = data.get("history", [])

        if not message:
            return jsonify({"error": "message is required"}), 400

        profile = get_member_profile(member_id)
        if not profile:
            return jsonify({"error": f"Member {member_id} not found"}), 404

        gaps = get_member_open_gaps(member_id)
        claims = get_member_claims_cpt_codes(member_id)

        gaps_text = (
            ", ".join(f"{g['measure_id']} ({g['measure_name']})" for g in gaps)
            or "None"
        )
        claims_text = "\n".join(
            f"  - CPT {c.get('cpt_code','?')} | {c.get('service_date','?')} | ICD {c.get('icd_code','?')}"
            for c in claims[:12]
        ) or "  No claims on record"

        system_msg = f"""You are an AI care manager assistant helping care managers at a health plan.
You are currently helping with member {profile.get('name')} (ID: {member_id}).

Member profile:
  Name   : {profile.get('name')} | Age: {profile.get('age_str')} | Gender: {profile.get('gender')}
  DOB    : {profile.get('dob')} | Plan: {profile.get('plan_id')}
  PCP    : {profile.get('pcp_name')} ({profile.get('pcp_specialty')}) — {profile.get('pcp_network_status')}
  Copay  : ${profile.get('copay')} | Preventive: $0 | Deductible: ${profile.get('deductible', 500)}

Open care gaps ({len(gaps)}): {gaps_text}

Recent claims:
{claims_text}

Guidelines:
- Answer the care manager's questions about this specific member concisely and accurately.
- Be helpful and actionable. If asked about outreach, suggest best approach given the gaps.
- If asked for clinical guidance, provide evidence-based HEDIS-aligned information.
- Keep responses under 200 words unless the care manager asks for detail.
- Do not refuse clinical questions — you are assisting a licensed care manager."""

        bedrock = boto3.client(
            "bedrock-runtime",
            region_name=cfg.aws_region,
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
        )

        # Build Bedrock Converse messages (system separate, then user/assistant)
        converse_messages = []
        for h in history[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                converse_messages.append({
                    "role": h["role"],
                    "content": [{"text": h["content"]}],
                })
        converse_messages.append({"role": "user", "content": [{"text": message}]})

        # Merge consecutive same-role messages (Bedrock requires alternating)
        merged = []
        for m in converse_messages:
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["content"].extend(m["content"])
            else:
                merged.append(m)

        # Ensure first message is user role
        if merged and merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": [{"text": "Hello."}]})

        response = bedrock.converse(
            modelId=cfg.bedrock_model_id,
            system=[{"text": system_msg}],
            messages=merged,
            inferenceConfig={
                "maxTokens": 600,
                "temperature": 0.7,
            },
        )

        output = response.get("output", {})
        content_blocks = output.get("message", {}).get("content", [])
        reply = " ".join(b.get("text", "") for b in content_blocks if "text" in b)

        return jsonify({"reply": reply, "member_id": member_id})

    except Exception as exc:
        logger.exception("chat_with_member error")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/v1/email/<member_id>", methods=["GET"])
def get_member_emails_endpoint(member_id):
    """Return all emails (sent + received) for a specific member."""
    try:
        from src.care_gap_neo4j import get_member_emails
        emails = get_member_emails(member_id)
        return jsonify({"member_id": member_id, "emails": emails, "total": len(emails)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/email/<member_id>/send", methods=["POST"])
def send_member_email(member_id):
    """Send email via Azure Communication Services and persist in Neo4j."""
    try:
        import uuid
        from datetime import datetime
        from azure.communication.email import EmailClient
        from src.care_gap_neo4j import merge_email
        from config.settings import settings as cfg

        data = request.json or {}
        to_email = str(data.get("to", "")).strip()
        subject  = str(data.get("subject", "")).strip()
        body     = str(data.get("body", "")).strip()

        if not to_email or not subject or not body:
            return jsonify({"error": "to, subject, and body are required"}), 400

        sender   = cfg.azure_communication_sender
        conn_str = cfg.azure_communication_connection_string

        if not conn_str or not sender:
            return jsonify({"error": "Azure email not configured on the server"}), 500

        logger.info(f"[MANUAL-EMAIL] Sending to {to_email}, subject: {subject[:60]}")

        # Send via Azure Communication Services
        client  = EmailClient.from_connection_string(conn_str)
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to_email}]},
            "content": {
                "subject": subject,
                "plainText": body,
                "html": (
                    "<html><body>"
                    f"<div style='font-family:Calibri,sans-serif;font-size:14px;color:#333'>"
                    f"<pre style='white-space:pre-wrap;font-family:inherit'>{body}</pre>"
                    "</div></body></html>"
                ),
            },
        }
        result = _send_email_with_retry(client, message)

        # Check Azure result status
        send_status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
        logger.info(f"[MANUAL-EMAIL] Azure status: {send_status}")

        if send_status and str(send_status).lower() not in ("succeeded", "queued", "outfordelivery"):
            error_detail = ""
            if isinstance(result, dict) and result.get("error"):
                error_detail = f" - {result['error']}"
            return jsonify({"error": f"Email send failed with status: {send_status}{error_detail}"}), 500

        # Persist in Neo4j
        email_id  = f"EMAIL-{member_id}-{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().isoformat()
        merge_email(
            email_id=email_id, member_id=member_id,
            subject=subject, body=body,
            from_email=sender, to_email=to_email,
            timestamp=timestamp, direction="sent", is_read=True,
        )

        msg_id = result.get("id", "") if isinstance(result, dict) else str(result)
        logger.info(f"[MANUAL-EMAIL] Sent OK: email_id={email_id}, azure_id={msg_id}")

        return jsonify({
            "status": "sent",
            "email_id": email_id,
            "message_id": msg_id,
        })

    except Exception as e:
        logger.exception("send_member_email error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/email/test-send", methods=["GET"])
def test_email_send():
    """
    Quick diagnostic: send a tiny test email to verify Azure config.
    Usage: GET /api/v1/email/test-send?to=you@example.com
    """
    try:
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg

        to_addr = request.args.get("to", "").strip()
        if not to_addr:
            return jsonify({"error": "Pass ?to=email@example.com"}), 400

        conn_str = cfg.azure_communication_connection_string
        sender = cfg.azure_communication_sender

        if not conn_str or not sender:
            return jsonify({
                "error": "Azure email not configured",
                "connection_string_set": bool(conn_str),
                "sender_set": bool(sender),
            }), 500

        client = EmailClient.from_connection_string(conn_str)
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to_addr}]},
            "content": {
                "subject": "HEDIS Portal - Email Test",
                "plainText": "This is a test email from the HealthCare Management Portal. If you received this, email sending is working correctly.",
                "html": "<html><body><h2>Email Test Successful</h2><p>Azure Communication Services is configured correctly.</p></body></html>",
            },
        }
        result = _send_email_with_retry(client, message)

        send_status = result.get("status") if isinstance(result, dict) else getattr(result, "status", None)
        msg_id = result.get("id", "") if isinstance(result, dict) else str(result)

        return jsonify({
            "status": "ok",
            "azure_status": str(send_status),
            "message_id": msg_id,
            "sender": sender,
            "to": to_addr,
            "full_result": str(result),
        })
    except Exception as e:
        logger.exception("test_email_send error")
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


@app.route("/api/v1/email/mark-read/<email_id>", methods=["PATCH"])
def mark_email_read_endpoint(email_id):
    """Mark an email as read."""
    try:
        from src.care_gap_neo4j import mark_email_read
        mark_email_read(email_id)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/appointments/<appointment_id>/force-close", methods=["POST"])
def force_close_appointment(appointment_id):
    """
    Force-close a booked appointment for demo purposes.
    Immediately: creates claim, closes care gap, creates outreach, marks appointment completed.
    Same logic as complete_appointment but callable on any appointment regardless of date.
    """
    try:
        from src.care_gap_neo4j import get_appointment, close_care_gap_with_claim, merge_outreach
        import uuid as _uuid
        from datetime import date as _date

        data = request.json or {}
        care_gap_id = data.get("care_gap_id", "")

        appt = get_appointment(appointment_id)
        if not appt:
            return jsonify({"status": "error", "error": "Appointment not found"}), 404

        service_date = str(_date.today())
        claim_id = f"CLM-{appt['member_id']}-{appt['measure_id']}-{_uuid.uuid4().hex[:8].upper()}"

        cpt_code, icd_code = _get_hedis_codes(appt["measure_id"])
        # Use member's actual ICD from gap node if available
        if care_gap_id:
            kg = get_knowledge_graph()
            gap_rows = kg.run_query(
                "MATCH (g:CareGap {care_gap_id: $gid}) RETURN g.primary_icd10 AS icd",
                {"gid": care_gap_id},
            )
            if gap_rows and gap_rows[0].get("icd"):
                icd_code = gap_rows[0]["icd"]

        close_care_gap_with_claim(
            care_gap_id=care_gap_id,
            member_id=appt["member_id"],
            measure_id=appt["measure_id"],
            provider_id=appt.get("provider_id", ""),
            cpt_code=cpt_code,
            icd_code=icd_code,
            service_date=service_date,
            claim_id=claim_id,
            plan_id=appt.get("plan_id", ""),
        )

        # Mark appointment completed
        kg = get_knowledge_graph()
        kg.execute_write(
            "MATCH (a:Appointment {appointment_id: $appt_id}) SET a.status = 'Completed'",
            {"appt_id": appointment_id},
        )

        # Create outreach record
        outreach_id = f"OUT-{appt['member_id']}-{appt['measure_id']}-{_uuid.uuid4().hex[:6].upper()}"
        merge_outreach(
            outreach_id=outreach_id,
            care_gap_id=care_gap_id,
            member_id=appt["member_id"],
            care_manager_id="SYSTEM",
            channel="Force Close",
            date=service_date,
            status="Completed",
        )

        # Check compliance
        remaining = kg.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            RETURN count(g) AS cnt
        """, {"mid": appt["member_id"]})[0]["cnt"]
        is_now_compliant = (remaining == 0)

        # Sync: gap closed in persona DB
        if care_gap_id:
            try:
                from src.persona_sync import sync_gap_closed
                logger.info(f"[FORCE-CLOSE] Syncing gap closure to persona DB: member={appt['member_id']}, gap={care_gap_id}")
                sync_gap_closed(member_id=appt["member_id"],
                                care_gap_id=care_gap_id)
            except Exception as e:
                logger.error(f"[FORCE-CLOSE] Persona sync failed for gap {care_gap_id}: {e}")
        else:
            logger.warning(f"[FORCE-CLOSE] No care_gap_id — skipping persona sync for {appointment_id}")

        return jsonify({
            "status":           "success",
            "claim_id":         claim_id,
            "care_gap_id":      care_gap_id,
            "cpt_codes":        cpt_code,
            "icd_codes":        icd_code,
            "is_now_compliant": is_now_compliant,
            "message":          "Force closed — care gap closed and claim generated" + (
                " — Member is now fully compliant!" if is_now_compliant else ""
            ),
        })
    except Exception as e:
        logger.error(f"force_close_appointment error: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/members/set-default-email", methods=["POST"])
def set_default_email():
    """Add default email to all existing members that don't have one."""
    try:
        kg = get_knowledge_graph()
        default_email = "ajohnsm2020@gmail.com"
        # Count first, then update
        count_res = kg.run_query("""
            MATCH (m:Member)
            WHERE m.email IS NULL OR m.email = ''
            RETURN count(m) AS cnt
        """, {})
        count = count_res[0]["cnt"] if count_res else 0
        if count > 0:
            kg.execute_write("""
                MATCH (m:Member)
                WHERE m.email IS NULL OR m.email = ''
                SET m.email = $email
            """, {"email": default_email})
        return jsonify({
            "status": "success",
            "message": f"Updated {count} members with email {default_email}",
            "updated_count": count,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ── Bulk Upload endpoints ───────────────────────────���────────────────────────

@app.route("/api/v1/members/bulk-upload", methods=["POST"])
def bulk_upload_members():
    """
    Parse an uploaded Excel file, create Member nodes, detect care gaps for
    each member (pure Python — no LLM), and return a preview so the care
    manager can approve before triggering the full agent analysis + email.

    Expected Excel columns (REQUIRED in CAPS, OPTIONAL extended in italics):
      Name, DOB, Gender, Email, Phone, PCPID, PlanID, ZIP,
      ChronicConditions (comma-separated), InsuranceType,
      EnrollmentStart, EnrollmentEnd,
      PriorScreenings (optional, semicolon-separated measure:date pairs,
        e.g. "BCS:2025-06-15;COL:2024-03-20")

      --- Extended patient record (all optional) ---
      HeightCm, WeightKg, SmokingStatus, AlcoholUse, ExerciseFrequency,
      DietType, SleepHoursAvg, StressLevel, LifestyleNotes,
      FamilyHistory  -> "relation|alive|age|cond1,cond2;relation|alive|age|cond1"
      PastConditions -> "name|year|status;..."
      CurrentConditions -> "name|year;..."
      Surgeries -> "name|year;..."
      Allergies -> "substance|severity|reaction;..."
      Medications -> "name|dose|started|purpose;..."
      Immunizations -> "name|year;..."

    Returns JSON with a list of members and their detected gaps.
    """
    import pandas as pd
    from datetime import datetime as _dt
    from src.care_gap_neo4j import (
        merge_member, merge_enrollment, get_next_member_id,
        get_member_open_gaps, get_member_profile,
    )
    from src.care_gap_agents import detect_care_gaps

    def _cell(row, key, default=""):
        val = row.get(key, default)
        if val is None:
            return default
        s = str(val).strip()
        if s.lower() == "nan" or s == "":
            return default
        return s

    def _num(row, key):
        s = _cell(row, key, "")
        if not s:
            return None
        try:
            return float(s) if "." in s else int(s)
        except Exception:
            return None

    def _parse_family(raw: str):
        out = []
        for chunk in (raw or "").split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = [p.strip() for p in chunk.split("|")]
            relation = parts[0] if len(parts) > 0 else ""
            if not relation:
                continue
            alive = (parts[1].lower() in ("true", "yes", "1", "alive")) if len(parts) > 1 else True
            age = parts[2] if len(parts) > 2 else ""
            conditions = [c.strip() for c in (parts[3].split(",") if len(parts) > 3 else []) if c.strip()]
            out.append({
                "relation": relation, "name": "", "alive": alive,
                "age_or_age_at_death": age, "conditions": conditions,
                "cause_of_death": "", "notes": "",
            })
        return out

    def _parse_entries(raw: str, schema: list):
        """schema = list of field names in order. Empty strings skip the field."""
        out = []
        for chunk in (raw or "").split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            parts = [p.strip() for p in chunk.split("|")]
            item = {schema[i]: parts[i] for i in range(min(len(schema), len(parts))) if parts[i]}
            if item:
                out.append(item)
        return out

    if "file" not in request.files:
        return jsonify({"status": "error", "error": "No file uploaded. Use form field name 'file'."}), 400

    f = request.files["file"]
    if not f.filename.endswith((".xlsx", ".xls")):
        return jsonify({"status": "error", "error": "Only .xlsx or .xls files are accepted."}), 400

    try:
        df = pd.read_excel(f, sheet_name=0)
        df = df.dropna(how="all").dropna(axis=1, how="all")
    except Exception as exc:
        return jsonify({"status": "error", "error": f"Could not read Excel file: {exc}"}), 400

    required_cols = {"Name", "DOB", "Gender", "Email"}
    missing = required_cols - set(df.columns)
    if missing:
        return jsonify({"status": "error", "error": f"Missing required columns: {', '.join(sorted(missing))}"}), 400

    results = []
    for _, row in df.iterrows():
        try:
            # Auto-assign member ID
            member_id = get_next_member_id()
            name = str(row["Name"]).strip()
            dob = str(row["DOB"]).strip()[:10]
            gender = str(row["Gender"]).strip()[:1].upper()
            email = str(row.get("Email", "ajohnsm2020@gmail.com")).strip()
            phone = str(row.get("Phone", "")).strip()
            pcp_id = str(row.get("PCPID", "P1000")).strip()
            plan_id = str(row.get("PlanID", "PLAN-001")).strip()
            zip_code = str(row.get("ZIP", "")).strip()
            chronic_raw = str(row.get("ChronicConditions", "")).strip()
            chronic_conditions = [c.strip() for c in chronic_raw.split(",") if c.strip()] if chronic_raw and chronic_raw.lower() != "nan" else []
            insurance_type = str(row.get("InsuranceType", "Commercial")).strip()
            enrollment_start = str(row.get("EnrollmentStart", "2026-01-01")).strip()[:10]
            enrollment_end = str(row.get("EnrollmentEnd", "2026-12-31")).strip()[:10]

            # Calculate age string
            try:
                birth = _dt.strptime(dob, "%Y-%m-%d")
                today = _dt.now()
                years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
                months = (today.month - birth.month) % 12
                age_str = f"{years} Years, {months} Months"
            except Exception:
                age_str = ""

            # Create member in Neo4j
            merge_member(
                member_id=member_id, name=name, dob=dob, gender=gender,
                pcp_id=pcp_id, zip_code=zip_code,
                enrollment_start=enrollment_start, enrollment_end=enrollment_end,
                age_str=age_str, email=email, phone=phone,
                insurance_type=insurance_type, chronic_conditions=chronic_conditions,
            )
            # Ensure BenefitPlan node exists before creating enrollment
            from src.care_gap_neo4j import merge_benefit_plan
            merge_benefit_plan(
                plan_id=plan_id,
                preventive_covered="All preventive services",
                copay=0,
                deductible=500,
                eligibility_rules="Standard eligibility",
            )
            merge_enrollment(
                member_id=member_id, plan_id=plan_id,
                pcp_id=pcp_id, effective_from=enrollment_start, effective_to=enrollment_end,
            )

            # ── Extended patient record (optional columns) ──────────────────
            height_cm = _num(row, "HeightCm")
            weight_kg = _num(row, "WeightKg")
            bmi = None
            if height_cm and weight_kg:
                try:
                    bmi = round(float(weight_kg) / ((float(height_cm) / 100) ** 2), 1)
                except Exception:
                    bmi = None
            lifestyle = {
                "height_cm": height_cm, "weight_kg": weight_kg, "bmi": bmi,
                "smoking_status":     _cell(row, "SmokingStatus"),
                "alcohol_use":        _cell(row, "AlcoholUse"),
                "exercise_frequency": _cell(row, "ExerciseFrequency"),
                "diet_type":          _cell(row, "DietType"),
                "sleep_hours_avg":    _num(row, "SleepHoursAvg"),
                "stress_level":       _cell(row, "StressLevel"),
                "notes":              _cell(row, "LifestyleNotes"),
            }
            if any(v not in (None, "", 0) for v in lifestyle.values()):
                merge_lifestyle(member_id, lifestyle)

            fam = _parse_family(_cell(row, "FamilyHistory"))
            if fam:
                replace_family_history(member_id, fam)

            history = {
                "past_conditions":    _parse_entries(_cell(row, "PastConditions"),    ["name", "onset_year", "status", "notes"]),
                "current_conditions": _parse_entries(_cell(row, "CurrentConditions"), ["name", "onset_year", "notes"]),
                "surgeries":          _parse_entries(_cell(row, "Surgeries"),         ["name", "year", "notes"]),
                "allergies":          _parse_entries(_cell(row, "Allergies"),         ["substance", "severity", "reaction"]),
                "medications":        _parse_entries(_cell(row, "Medications"),       ["name", "dose", "started", "purpose"]),
                "immunizations":      _parse_entries(_cell(row, "Immunizations"),     ["name", "year"]),
            }
            if any(history.values()):
                replace_medical_history(member_id, history)

            # Load prior screenings as claims (e.g. "BCS:2025-06-15;COL:2024-03-20")
            prior_raw = str(row.get("PriorScreenings", "")).strip()
            if prior_raw and prior_raw.lower() != "nan":
                from src.hedis_golden_reference import HEDIS_MEASURES
                from src.care_gap_neo4j import merge_claim
                for entry in prior_raw.split(";"):
                    entry = entry.strip()
                    if ":" not in entry:
                        continue
                    mid_part, svc_date = entry.split(":", 1)
                    mid_part = mid_part.strip().upper()
                    svc_date = svc_date.strip()[:10]
                    measure_def = HEDIS_MEASURES.get(mid_part)
                    if not measure_def:
                        logger.warning(f"[BULK] Unknown measure '{mid_part}' in PriorScreenings for {member_id}")
                        continue
                    claim_id = f"PRIOR-{member_id}-{mid_part}"
                    merge_claim(
                        claim_id=claim_id,
                        member_id=member_id,
                        provider_id=pcp_id,
                        cpt_code=measure_def.get("primary_cpt", ""),
                        icd_code=measure_def.get("primary_icd10", ""),
                        service_date=svc_date,
                        status="Completed",
                    )
                    logger.info(f"[BULK] Prior screening claim created: {claim_id} ({mid_part} on {svc_date})")

            # Detect care gaps (pure Python — fast)
            gap_result = detect_care_gaps(member_id)
            open_gaps = get_member_open_gaps(member_id)
            profile = get_member_profile(member_id)

            # ── Sync persona to reference DB for visualization ──────
            try:
                from src.persona_sync import sync_member_persona, sync_care_gap
                sync_member_persona(
                    member_id=member_id, name=name, dob=dob,
                    gender=gender, age_str=age_str,
                    chronic_conditions=chronic_conditions,
                    insurance_type=insurance_type,
                    pcp_name=(profile or {}).get("pcp_name", pcp_id),
                    pcp_id=pcp_id,
                )
                for og in open_gaps:
                    sync_care_gap(
                        member_id=member_id,
                        care_gap_id=og["care_gap_id"],
                        measure_id=og["measure_id"],
                        measure_name=og.get("measure_name", og["measure_id"]),
                    )
            except Exception as ps_err:
                logger.warning(f"Persona sync failed for {member_id}: {ps_err}")

            results.append({
                "member_id": member_id,
                "name": name,
                "age_str": age_str,
                "gender": gender,
                "email": email,
                "chronic_conditions": chronic_conditions,
                "insurance_type": insurance_type,
                "plan_id": plan_id,
                "pcp_id": pcp_id,
                "pcp_name": (profile or {}).get("pcp_name", pcp_id),
                "gaps_created": gap_result.get("gaps_created", []),
                "compliant": gap_result.get("compliant", []),
                "excluded": gap_result.get("excluded", []),
                "open_gaps": open_gaps,
            })
        except Exception as exc:
            logger.error(f"Bulk upload error for row {row.get('Name', '?')}: {exc}", exc_info=True)
            results.append({
                "name": str(row.get("Name", "?")),
                "error": str(exc),
            })

    return jsonify({
        "status": "success",
        "total_uploaded": len(results),
        "members": results,
    })


@app.route("/api/v1/members/bulk-process", methods=["POST"])
def bulk_process_members():
    """
    After the care manager approves selected members from bulk-upload preview,
    run the 6-agent analysis AND send outreach emails for all selected
    members simultaneously using threads.

    Body: { "members": [ { "member_id": "M0031", "name": "...", ... }, ... ] }
    """
    import threading
    import uuid as _uuid
    from datetime import datetime as _dt
    from src.member_portal import get_portal_url

    data = request.json or {}
    member_list = data.get("members", [])
    if not member_list:
        return jsonify({"status": "error", "error": "No members provided"}), 400

    processing_results = {}
    lock = threading.Lock()

    def process_one(member_info):
        mid = member_info["member_id"]
        mname = member_info.get("name", mid)
        memail = member_info.get("email", "")
        try:
            # 1. Run 6-agent analysis
            # Sync: analysis started
            try:
                from src.persona_sync import sync_analysis_started
                sync_analysis_started(mid)
            except Exception:
                pass

            agents = get_agents()
            analysis = agents.validate_and_suggest(mid)

            # Sync: analysis complete
            try:
                from src.persona_sync import sync_analysis_complete
                summary = str(analysis.get("summary", ""))[:200] if isinstance(analysis, dict) else ""
                sync_analysis_complete(mid, summary=summary)
            except Exception:
                pass

            # 2. Send outreach email with portal link
            email_sent = False
            if memail:
                try:
                    from azure.communication.email import EmailClient
                    from config.settings import settings as cfg
                    from src.care_gap_neo4j import merge_email, merge_outreach, get_member_open_gaps as _get_gaps

                    open_gaps = _get_gaps(mid)
                    if open_gaps:
                        portal_url = get_portal_url(mid)

                        # Build human-readable treatment cards (NO codes)
                        from src.pdf_report import generate_member_report, _friendly
                        import base64 as _b64

                        gap_cards = ""
                        for g in open_gaps:
                            what, why, action = _friendly(
                                g.get("measure_id", ""),
                                g.get("resolution_guide") or g.get("description", ""),
                            )
                            gap_cards += (
                                f"<div style='background:#f8faff;border-left:4px solid #0033A1;"
                                f"padding:14px 18px;margin:10px 0;border-radius:0 8px 8px 0;'>"
                                f"<h3 style='color:#0033A1;margin:0 0 6px;font-size:15px;'>{what}</h3>"
                                f"<p style='color:#555;font-size:12px;margin:0 0 4px;'>"
                                f"<strong>Why:</strong> {why}</p>"
                                f"<p style='color:#333;font-size:12px;margin:0;'>"
                                f"<strong>What to do:</strong> {action}</p></div>"
                            )

                        subject = f"Your Preventive Care Report — {len(open_gaps)} Screening(s) Recommended - {mname}"
                        body_html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:680px;margin:auto;">
<div style="background:#0033A1;padding:20px 32px;border-radius:8px 8px 0 0;">
  <h1 style="color:white;margin:0;font-size:22px;">HealthCare Management Portal</h1>
  <p style="color:#b3c7f7;margin:4px 0 0;">Your Preventive Care Report</p>
</div>
<div style="border:1px solid #dce3f5;border-top:none;padding:32px;border-radius:0 0 8px 8px;">
  <p style="font-size:16px;">Dear <strong>{mname}</strong>,</p>
  <p>Our care management team has identified <strong>{len(open_gaps)} preventive screening(s)</strong> that are recommended for you. Completing these screenings is important for your long-term health and well-being.</p>

  <h2 style="color:#0033A1;margin:20px 0 8px;font-size:17px;">Your Recommended Screenings</h2>
  {gap_cards}

  <div style="background:#fff8e1;border-radius:8px;padding:14px;margin:20px 0;">
    <p style="margin:0;font-size:12px;color:#7a5900;"><strong>Attached:</strong> Your complete Care Management Report (PDF) with full details about your health profile and recommended treatments.</p>
  </div>

  <p>Please click the button below to review your screenings and schedule appointments at a convenient location near you:</p>
  <div style="text-align:center;margin:28px 0;">
    <a href="{portal_url}" style="background:#059669;color:white;padding:14px 36px;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">Review & Schedule Appointments</a>
  </div>
  <p style="color:#666;font-size:13px;">If you have already completed these screenings, please disregard this message or contact your care manager.</p>
  <hr style="border:none;border-top:1px solid #dce3f5;margin:24px 0;">
  <p style="color:#888;font-size:12px;">This is an automated message from the HealthCare Management Portal.</p>
</div>
</body></html>"""

                        # Generate PDF attachment
                        from src.care_gap_neo4j import get_member_profile as _get_profile
                        _prof = {}
                        try:
                            _prof = _get_profile(mid) or {}
                        except Exception:
                            pass

                        _pdf_bytes = generate_member_report(
                            member_id=mid,
                            name=mname,
                            dob=_prof.get("dob", ""),
                            gender=_prof.get("gender", ""),
                            pcp_name=_prof.get("pcp_name", ""),
                            plan_id=_prof.get("plan_id", ""),
                            insurance_type=_prof.get("insurance_type", ""),
                            chronic_conditions=_prof.get("chronic_conditions", ""),
                            open_gaps=open_gaps,
                        )
                        _pdf_b64 = _b64.b64encode(_pdf_bytes).decode("utf-8")

                        conn_str = cfg.azure_communication_connection_string
                        sender = cfg.azure_communication_sender
                        if conn_str and sender:
                            client = EmailClient.from_connection_string(conn_str)
                            message = {
                                "senderAddress": sender,
                                "recipients": {"to": [{"address": memail}]},
                                "content": {"subject": subject, "html": body_html},
                                "attachments": [
                                    {
                                        "name": f"Care_Report_{mid}.pdf",
                                        "contentType": "application/pdf",
                                        "contentInBase64": _pdf_b64,
                                    }
                                ],
                            }
                            _send_email_with_retry(client, message)
                            email_sent = True

                            # Persist email in Neo4j
                            email_id = f"BULK-EMAIL-{mid}-{_uuid.uuid4().hex[:8]}"
                            merge_email(
                                email_id=email_id, member_id=mid,
                                subject=subject,
                                body=f"Preventive care report: {len(open_gaps)} screening(s) recommended. PDF attached.",
                                from_email=sender, to_email=memail,
                                timestamp=_dt.now().isoformat(),
                                direction="sent", is_read=True,
                            )

                            # Create outreach record for each gap
                            for g in open_gaps:
                                out_id = f"BULK-OUT-{mid}-{g['measure_id']}-{_uuid.uuid4().hex[:6]}"
                                merge_outreach(
                                    outreach_id=out_id,
                                    care_gap_id=g["care_gap_id"],
                                    member_id=mid,
                                    care_manager_id="BULK-SYSTEM",
                                    channel="Email",
                                    date=_dt.now().strftime("%Y-%m-%d"),
                                    status="Sent",
                                )
                            # Sync: outreach sent
                            try:
                                from src.persona_sync import sync_outreach_sent
                                sync_outreach_sent(mid, channel="Email")
                            except Exception:
                                pass

                except Exception as email_err:
                    logger.warning(f"Bulk email failed for {mid}: {email_err}")

            # 3. Send WhatsApp notification
            whatsapp_sent = False
            try:
                from src.care_gap_neo4j import get_member_profile as _get_prof_wa
                from src.care_gap_neo4j import get_member_open_gaps as _get_gaps_wa
                _wa_prof = _get_prof_wa(mid) or {}
                mphone = _wa_prof.get("phone", "")
                logger.info(f"[BULK-WA] {mid} phone from profile: '{mphone}'")
                if mphone:
                    from src.whatsapp_service import send_care_gap_report
                    _wa_gaps = _get_gaps_wa(mid)
                    _wa_portal = get_portal_url(mid)
                    wa_result = send_care_gap_report(
                        to_phone=mphone,
                        member_name=mname,
                        gaps=_wa_gaps,
                        portal_url=_wa_portal,
                    )
                    whatsapp_sent = wa_result.get("success", False)
                    logger.info(f"[BULK-WA] {mid} result: {wa_result}")
                else:
                    logger.warning(f"[BULK-WA] {mid} — no phone on file, skipping WhatsApp")
            except Exception as wa_err:
                logger.warning(f"Bulk WhatsApp failed for {mid}: {wa_err}", exc_info=True)

            with lock:
                processing_results[mid] = {
                    "member_id": mid,
                    "name": mname,
                    "status": "completed",
                    "email_sent": email_sent,
                    "whatsapp_sent": whatsapp_sent,
                    "analysis_summary": str(analysis.get("summary", ""))[:500] if isinstance(analysis, dict) else str(analysis)[:500],
                }
        except Exception as exc:
            logger.error(f"Bulk process error for {mid}: {exc}", exc_info=True)
            with lock:
                processing_results[mid] = {
                    "member_id": mid,
                    "name": mname,
                    "status": "error",
                    "error": str(exc),
                }

    # Process members with limited concurrency (max 2 at a time)
    # to avoid Bedrock API throttling
    MAX_CONCURRENT = 2
    semaphore = threading.Semaphore(MAX_CONCURRENT)

    def process_one_with_limit(member_info):
        with semaphore:
            process_one(member_info)

    threads = []
    for m in member_list:
        t = threading.Thread(target=process_one_with_limit, args=(m,))
        t.start()
        threads.append(t)

    # Wait for all to finish (timeout 5 min per member)
    for t in threads:
        t.join(timeout=300)

    return jsonify({
        "status": "success",
        "total_processed": len(processing_results),
        "results": list(processing_results.values()),
    })


@app.route("/api/v1/members/bulk-upload-page")
def bulk_upload_page():
    """Serve the bulk upload HTML page."""
    return _bulk_upload_html()


@app.route("/api/v1/members/dashboard-page")
def members_dashboard_page():
    """Serve the all-members dashboard HTML page."""
    return _members_dashboard_html()


@app.route("/api/v1/login")
def login_page():
    """Common login page for the platform."""
    return _login_html()


@app.route("/api/v1/landing")
def landing_page():
    """Main landing page with buttons for Members Dashboard and Bulk Upload."""
    return _landing_html()


def _login_html():
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Login — HEDIS Care Gap Management</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,Roboto,'Helvetica Neue',sans-serif;background:#000048;min-height:100vh;display:flex;align-items:center;justify-content:center}
.login-wrapper{display:flex;flex-direction:column;align-items:center;width:100%;max-width:440px;padding:0 20px}
.login-logo{margin-bottom:32px;text-align:center}
.login-logo h1{color:#fff;font-size:22px;font-weight:700;margin-bottom:4px}
.login-logo p{color:#26EFE9;font-size:13px;font-weight:600;letter-spacing:0.5px}
.login-card{background:#fff;border-radius:0;width:100%;padding:40px 36px;box-shadow:0 8px 40px rgba(0,0,0,0.3)}
.login-card h2{color:#000048;font-size:24px;font-weight:700;margin-bottom:6px}
.login-card .subtitle{color:#53565A;font-size:14px;margin-bottom:28px}
.form-group{margin-bottom:20px}
.form-group label{display:block;font-size:13px;font-weight:600;color:#000048;margin-bottom:6px}
.form-group input{width:100%;padding:12px 14px;border:1px solid #D0D0CE;border-radius:0.5em;font-size:14px;background:#F7F7F5;outline:none;transition:border-color 0.2s,box-shadow 0.2s;color:#000048}
.form-group input:focus{border-color:#000048;box-shadow:0 0 0 3px rgba(0,0,72,0.1);background:#fff}
.form-group input::placeholder{color:#97999B}
.remember-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
.remember-row label{display:flex;align-items:center;gap:6px;font-size:13px;color:#53565A;cursor:pointer}
.remember-row input[type=checkbox]{width:16px;height:16px;accent-color:#2F78C4;cursor:pointer}
.remember-row a{font-size:13px;color:#2F78C4;text-decoration:none;font-weight:600}
.remember-row a:hover{text-decoration:underline}
.login-btn{width:100%;padding:14px;background:#26EFE9;color:#000048;border:none;border-radius:999px;font-size:15px;font-weight:700;cursor:pointer;transition:background 0.2s,transform 0.15s}
.login-btn:hover{background:#06C7CC;transform:translateY(-1px)}
.login-btn:active{transform:translateY(0)}
.login-error{display:none;background:rgba(184,31,45,0.08);color:#B81F2D;padding:10px 14px;border-radius:0.5em;font-size:13px;margin-bottom:16px;font-weight:500}
.login-error.show{display:block}
.login-footer{text-align:center;margin-top:24px;color:rgba(255,255,255,0.4);font-size:12px}
.divider{display:flex;align-items:center;gap:12px;margin:24px 0}
.divider hr{flex:1;border:none;border-top:1px solid #E8E8E6}
.divider span{color:#97999B;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
.dest-buttons{display:flex;gap:12px}
.dest-btn{flex:1;padding:12px;border:1px solid #E8E8E6;border-radius:0.5em;background:#F7F7F5;text-align:center;cursor:pointer;text-decoration:none;transition:all 0.2s;font-size:13px;font-weight:600;color:#000048}
.dest-btn:hover{background:#E8E8E6;border-color:#D0D0CE}
.dest-btn .icon{font-size:20px;display:block;margin-bottom:4px}
</style></head><body>
<div class="login-wrapper">
  <div class="login-logo">
    <h1>HEDIS Care Gap Management</h1>
    <p>AI-POWERED PLATFORM</p>
  </div>
  <div class="login-card">
    <h2>Sign In</h2>
    <p class="subtitle">Access the care management platform</p>
    <div class="login-error" id="loginError">Invalid username or password. Please try again.</div>
    <form id="loginForm" onsubmit="handleLogin(event)">
      <div class="form-group">
        <label for="username">Username</label>
        <input type="text" id="username" placeholder="Enter your username" autocomplete="username" required>
      </div>
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" id="password" placeholder="Enter your password" autocomplete="current-password" required>
      </div>
      <div class="remember-row">
        <label><input type="checkbox" id="remember"> Remember me</label>
        <a href="#">Forgot password?</a>
      </div>
      <button type="submit" class="login-btn">Sign In</button>
    </form>
    <div class="divider"><hr><span>Go to</span><hr></div>
    <div class="dest-buttons">
      <a class="dest-btn" href="http://localhost:5173" target="_blank">
        <span class="icon">&#9881;</span>
        Main Dashboard
      </a>
      <a class="dest-btn" href="/api/v1/landing">
        <span class="icon">&#128202;</span>
        Admin Portal
      </a>
    </div>
  </div>
  <div class="login-footer">HEDIS Care Gap Management &mdash; Powered by AI Agents & Knowledge Graph</div>
</div>

<script>
function handleLogin(e){
  e.preventDefault();
  const user=document.getElementById('username').value.trim();
  const pass=document.getElementById('password').value;
  const errorEl=document.getElementById('loginError');

  // Simple auth check — accepts admin/admin or any non-empty credentials
  if(!user||!pass){
    errorEl.classList.add('show');
    return;
  }

  // Store login state
  const remember=document.getElementById('remember').checked;
  const storage=remember?localStorage:sessionStorage;
  storage.setItem('hedis_logged_in','true');
  storage.setItem('hedis_user',user);

  // Redirect to landing page
  window.location.href='/api/v1/landing';
}

// Auto-fill if remembered
window.addEventListener('DOMContentLoaded',()=>{
  if(localStorage.getItem('hedis_logged_in')==='true'){
    document.getElementById('username').value=localStorage.getItem('hedis_user')||'';
  }
});
</script>
</body></html>"""


def _landing_html():
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>HEDIS Care Gap Management — Cognizant</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,Roboto,'Helvetica Neue',sans-serif;background:#F7F7F5;min-height:100vh}
.top-bar{background:#000048;padding:16px 40px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 12px rgba(0,0,72,0.18)}
.top-bar h1{color:#fff;font-size:20px;font-weight:700;letter-spacing:0.3px}
.top-bar .badge{background:rgba(38,239,233,0.15);color:#26EFE9;padding:5px 14px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:0.5px}
.hero{text-align:center;padding:48px 20px 24px}
.hero h2{font-size:30px;color:#000048;margin-bottom:8px;font-weight:700}
.hero p{color:#53565A;font-size:15px;max-width:600px;margin:0 auto 12px}
.stats-bar{display:flex;justify-content:center;gap:32px;margin:20px auto 36px;flex-wrap:wrap}
.stat-pill{background:#fff;border-radius:0;padding:12px 24px;display:flex;align-items:center;gap:10px;box-shadow:0 2px 10px rgba(0,0,0,0.06)}
.stat-pill .num{font-size:24px;font-weight:700}
.stat-pill .lbl{font-size:12px;color:#97999B;text-transform:uppercase;letter-spacing:0.5px}
.stat-pill.blue .num{color:#000048}
.stat-pill.red .num{color:#B81F2D}
.stat-pill.amber .num{color:#E9C71D}
.stat-pill.green .num{color:#2DB81F}
.cards{display:flex;gap:28px;justify-content:center;flex-wrap:wrap;max-width:1100px;margin:0 auto;padding:0 20px 48px}
.card{background:#fff;border-radius:0;padding:0;width:330px;box-shadow:0 4px 24px rgba(0,0,72,0.08);transition:transform 0.25s,box-shadow 0.25s;cursor:pointer;text-decoration:none;color:inherit;overflow:hidden;border:1px solid #E8E8E6}
.card:hover{transform:translateY(-8px);box-shadow:0 12px 40px rgba(0,0,72,0.16)}
.card-top{padding:28px 24px 20px;text-align:center}
.card-icon{width:64px;height:64px;border-radius:0.5em;display:flex;align-items:center;justify-content:center;font-size:30px;margin:0 auto 16px}
.card-icon.blue{background:rgba(47,120,196,0.12);color:#000048}
.card-icon.purple{background:rgba(115,115,216,0.12);color:#2E308E}
.card-icon.teal{background:rgba(6,199,204,0.12);color:#05819B}
.card h2{font-size:18px;color:#000048;margin-bottom:8px;font-weight:700}
.card p{color:#53565A;font-size:13px;line-height:1.55;padding:0 4px}
.card-features{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin-top:14px}
.tag{background:rgba(47,120,196,0.08);color:#000048;font-size:10px;padding:4px 10px;border-radius:999px;font-weight:600}
.tag.green{background:rgba(45,184,31,0.1);color:#2DB81F}
.tag.purple{background:rgba(115,115,216,0.1);color:#2E308E}
.card-bottom{background:#F7F7F5;padding:16px 24px;border-top:1px solid #E8E8E6;text-align:center}
.card-btn{display:inline-block;background:#26EFE9;color:#000048;padding:10px 32px;border-radius:999px;font-size:13px;font-weight:700;text-decoration:none;transition:background 0.2s,transform 0.15s}
.card-btn:hover{background:#06C7CC;transform:scale(1.03)}
.card-btn.green-btn{background:#26EFE9;color:#000048}
.card-btn.green-btn:hover{background:#06C7CC}
.card-btn.purple-btn{background:#26EFE9;color:#000048}
.card-btn.purple-btn:hover{background:#06C7CC}
.footer{text-align:center;padding:20px;color:#97999B;font-size:12px}
</style></head><body>
<div class="top-bar">
  <h1>HEDIS Care Gap Management</h1>
  <span class="badge">AI-POWERED PLATFORM</span>
</div>

<div class="hero">
  <h2>Care Management Dashboard</h2>
  <p>Unified platform for preventive care compliance — manage members, track care gaps, and drive outreach from one place.</p>
</div>

<div class="stats-bar" id="statsBar">
  <div class="stat-pill blue"><div><div class="num" id="statTotal">-</div><div class="lbl">Total Members</div></div></div>
  <div class="stat-pill red"><div><div class="num" id="statCritical">-</div><div class="lbl">Critical</div></div></div>
  <div class="stat-pill amber"><div><div class="num" id="statAttention">-</div><div class="lbl">Needs Attention</div></div></div>
  <div class="stat-pill green"><div><div class="num" id="statCompliant">-</div><div class="lbl">Compliant</div></div></div>
</div>

<div class="cards">
  <a class="card" href="http://localhost:5173" target="_blank">
    <div class="card-top">
      <div class="card-icon blue">&#9881;</div>
      <h2>Overall Dashboard</h2>
      <p>Full interactive dashboard with individual member panels, real-time AI analysis, and complete care gap lifecycle management.</p>
      <div class="card-features">
        <span class="tag">6-Agent AI Analysis</span>
        <span class="tag">Force Close</span>
        <span class="tag">Claims</span>
        <span class="tag">Email & Chat</span>
        <span class="tag">Appointments</span>
        <span class="tag">Outreach</span>
      </div>
    </div>
    <div class="card-bottom">
      <span class="card-btn">Open Dashboard &rarr;</span>
    </div>
  </a>

  <a class="card" href="/api/v1/members/dashboard-page">
    <div class="card-top">
      <div class="card-icon purple">&#128100;</div>
      <h2>Members Overview</h2>
      <p>Quick population-level view of all members — search, filter, and see care gap statuses at a glance.</p>
      <div class="card-features">
        <span class="tag purple">Search Members</span>
        <span class="tag purple">Status Filters</span>
        <span class="tag purple">Gap Counts</span>
        <span class="tag purple">PCP Info</span>
      </div>
    </div>
    <div class="card-bottom">
      <span class="card-btn purple-btn">View Members &rarr;</span>
    </div>
  </a>

  <a class="card" href="/api/v1/members/bulk-upload-page">
    <div class="card-top">
      <div class="card-icon teal">&#128196;</div>
      <h2>Excel Upload & Outreach</h2>
      <p>Upload a member spreadsheet — AI detects care gaps, previews results, then sends personalized email outreach with PDF reports.</p>
      <div class="card-features">
        <span class="tag green">Drag & Drop</span>
        <span class="tag green">Auto-Detect Gaps</span>
        <span class="tag green">Bulk Email</span>
        <span class="tag green">PDF Reports</span>
      </div>
    </div>
    <div class="card-bottom">
      <span class="card-btn green-btn">Upload Excel &rarr;</span>
    </div>
  </a>
</div>

<div class="footer">HEDIS Care Gap Management System &mdash; Powered by AI Agents &amp; Knowledge Graph</div>

<script>
(async()=>{
  try{
    const [mRes,sRes]=await Promise.all([fetch('/api/v1/members'),fetch('/api/v1/dashboard/stats')]);
    const mData=await mRes.json();const sData=await sRes.json();
    const members=mData.members||[];
    document.getElementById('statTotal').textContent=sData.total_members||members.length||0;
    document.getElementById('statCritical').textContent=members.filter(m=>m.open_gaps>=3).length;
    document.getElementById('statAttention').textContent=members.filter(m=>m.open_gaps>0&&m.open_gaps<3).length;
    document.getElementById('statCompliant').textContent=sData.compliant_members||0;
  }catch(e){console.warn('Stats load failed:',e)}
})();
</script>
</body></html>"""


def _members_dashboard_html():
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Members Dashboard - HEDIS Care Gap</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,Roboto,'Helvetica Neue',sans-serif;background:#F7F7F5;padding:24px}
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
.header h1{color:#000048;font-size:24px}
.header a{color:#000048;text-decoration:none;font-weight:600;font-size:14px}
.stats{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.stat-card{background:#fff;border-radius:0;padding:20px 24px;flex:1;min-width:180px;box-shadow:0 2px 12px rgba(0,0,0,0.06)}
.stat-card .label{color:#97999B;font-size:12px;text-transform:uppercase;letter-spacing:0.5px}
.stat-card .value{font-size:28px;font-weight:700;margin-top:4px}
.stat-card.critical .value{color:#B81F2D}
.stat-card.attention .value{color:#E9C71D}
.stat-card.compliant .value{color:#2DB81F}
.stat-card.total .value{color:#000048}
.search-bar{margin-bottom:16px}
.search-bar input{width:100%;padding:12px 16px;border:1px solid #D0D0CE;border-radius:0.5em;font-size:14px;outline:none;background:#F7F7F5}
.search-bar input:focus{border-color:#000048;box-shadow:0 0 0 3px rgba(0,0,72,0.1)}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:0;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.06)}
th{background:#000048;color:#fff;padding:12px 16px;text-align:left;font-size:13px;text-transform:uppercase;letter-spacing:0.5px}
td{padding:12px 16px;border-bottom:1px solid #E8E8E6;font-size:14px;color:#000048}
tr:hover td{background:#F7F7F5}
.badge{display:inline-block;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:600}
.badge.critical{background:rgba(184,31,45,0.08);color:#B81F2D}
.badge.attention{background:rgba(233,199,29,0.12);color:#92400e}
.badge.compliant{background:rgba(45,184,31,0.1);color:#2DB81F}
.member-link{color:#2F78C4;text-decoration:none;font-weight:600}
.member-link:hover{text-decoration:underline}
.loading{text-align:center;padding:60px;color:#97999B}
</style></head><body>
<div class="header">
  <h1>&#128202; Members Dashboard</h1>
  <a href="/api/v1/landing">&larr; Back to Home</a>
  <a href="http://localhost:5173" target="_blank" style="margin-left:16px;background:#26EFE9;color:#000048;padding:8px 20px;border-radius:999px;font-size:13px;font-weight:700;text-decoration:none">Open Overall Dashboard &rarr;</a>
</div>
<div class="stats" id="stats"><div class="loading">Loading stats...</div></div>
<div class="search-bar"><input type="text" id="searchInput" placeholder="Search members by name, ID, or status..." oninput="filterMembers()"></div>
<table><thead><tr>
  <th>Member ID</th><th>Name</th><th>Age</th><th>Gender</th><th>PCP</th><th>Open Gaps</th><th>Closed Gaps</th><th>Status</th>
</tr></thead><tbody id="memberTable"><tr><td colspan="8" class="loading">Loading members...</td></tr></tbody></table>
<script>
let allMembers=[];
async function load(){
  try{
    const [membersRes,statsRes]=await Promise.all([fetch('/api/v1/members'),fetch('/api/v1/dashboard/stats')]);
    const membersData=await membersRes.json();
    const statsData=await statsRes.json();
    allMembers=membersData.members||[];
    document.getElementById('stats').innerHTML=`
      <div class="stat-card total"><div class="label">Total Members</div><div class="value">${statsData.total_members||0}</div></div>
      <div class="stat-card critical"><div class="label">Critical (3+ gaps)</div><div class="value">${allMembers.filter(m=>m.open_gaps>=3).length}</div></div>
      <div class="stat-card attention"><div class="label">Needs Attention (1-2)</div><div class="value">${allMembers.filter(m=>m.open_gaps>0&&m.open_gaps<3).length}</div></div>
      <div class="stat-card compliant"><div class="label">Compliant (0)</div><div class="value">${statsData.compliant_members||0}</div></div>
    `;
    renderMembers(allMembers);
  }catch(e){document.getElementById('memberTable').innerHTML='<tr><td colspan=\"8\">Error loading data: '+e.message+'</td></tr>';}
}
function renderMembers(members){
  const tb=document.getElementById('memberTable');
  if(!members.length){tb.innerHTML='<tr><td colspan=\"8\" style=\"text-align:center;padding:40px;color:#888\">No members found</td></tr>';return;}
  tb.innerHTML=members.map(m=>{
    let status,cls;
    if(m.open_gaps>=3){status='Critical';cls='critical';}
    else if(m.open_gaps>0){status='Needs Attention';cls='attention';}
    else{status='Compliant';cls='compliant';}
    return `<tr>
      <td><a class="member-link" href="http://localhost:5173" target="_blank">${m.member_id}</a></td>
      <td><strong>${m.name||'N/A'}</strong></td>
      <td>${m.age||'N/A'}</td>
      <td>${m.gender||'N/A'}</td>
      <td>${m.pcp_name||'N/A'}</td>
      <td style="font-weight:700;color:${m.open_gaps>0?'#B81F2D':'#2DB81F'}">${m.open_gaps}</td>
      <td style="color:#2DB81F;font-weight:600">${m.closed_gaps}</td>
      <td><span class="badge ${cls}">${status}</span></td>
    </tr>`;
  }).join('');
}
function filterMembers(){
  const q=document.getElementById('searchInput').value.toLowerCase();
  if(!q){renderMembers(allMembers);return;}
  renderMembers(allMembers.filter(m=>
    (m.member_id||'').toLowerCase().includes(q)||
    (m.name||'').toLowerCase().includes(q)||
    (m.open_gaps>=3?'critical':m.open_gaps>0?'needs attention':'compliant').includes(q)
  ));
}
load();
</script></body></html>"""


def _bulk_upload_html():
    return """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Bulk Upload Members - HEDIS Care Gap</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,Roboto,'Helvetica Neue',sans-serif;background:#F7F7F5;padding:24px}
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
.header h1{color:#000048;font-size:24px}
.header a{color:#000048;text-decoration:none;font-weight:600;font-size:14px}
.upload-area{background:#fff;border:2px dashed #000048;border-radius:0;padding:60px 40px;text-align:center;margin-bottom:24px;transition:background 0.2s}
.upload-area.dragover{background:rgba(47,120,196,0.06)}
.upload-area h2{color:#000048;margin-bottom:8px}
.upload-area p{color:#53565A;margin-bottom:20px;font-size:14px}
.upload-area input[type=file]{display:none}
.upload-btn{display:inline-block;background:#26EFE9;color:#000048;padding:14px 36px;border-radius:999px;font-size:15px;font-weight:700;cursor:pointer;border:none;transition:background 0.2s}
.upload-btn:hover{background:#06C7CC}
.upload-btn:disabled{background:#97999B;color:#fff;cursor:not-allowed}
.template-link{display:inline-block;margin-top:16px;color:#2F78C4;font-size:13px;text-decoration:underline;cursor:pointer}
.progress-bar{display:none;margin:20px auto;width:80%;height:6px;background:#E8E8E6;border-radius:3px;overflow:hidden}
.progress-bar .fill{height:100%;background:#000048;border-radius:3px;transition:width 0.5s}
.status-msg{text-align:center;margin:12px 0;font-size:14px;color:#53565A}

/* Preview popup (modal) */
.modal-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,72,0.5);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.show{display:flex}
.modal{background:#fff;border-radius:0;width:95%;max-width:1200px;max-height:90vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 8px 48px rgba(0,0,72,0.2)}
.modal-header{background:#000048;color:#fff;padding:20px 28px;display:flex;justify-content:space-between;align-items:center}
.modal-header h2{font-size:20px}
.modal-close{background:none;border:none;color:#fff;font-size:28px;cursor:pointer}
.modal-body{overflow-y:auto;padding:24px 28px;flex:1}
.modal-footer{padding:16px 28px;border-top:1px solid #E8E8E6;display:flex;justify-content:space-between;align-items:center;background:#F7F7F5}

.summary-bar{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.summary-item{background:rgba(47,120,196,0.06);padding:12px 20px;border-radius:0;text-align:center;min-width:140px}
.summary-item .num{font-size:24px;font-weight:700;color:#000048}
.summary-item .lbl{font-size:11px;color:#53565A;text-transform:uppercase;letter-spacing:0.5px;margin-top:2px}

.select-all-row{margin-bottom:12px;display:flex;align-items:center;gap:8px}
.select-all-row input{width:18px;height:18px;cursor:pointer;accent-color:#2F78C4}
.select-all-row label{font-size:14px;font-weight:600;color:#000048;cursor:pointer}

.member-card{background:#fff;border:1px solid #E8E8E6;border-radius:0;margin-bottom:16px;overflow:hidden;transition:box-shadow 0.2s}
.member-card:hover{box-shadow:0 2px 12px rgba(0,0,72,0.08)}
.member-card-header{display:flex;align-items:center;padding:14px 20px;gap:12px;cursor:pointer}
.member-card-header input[type=checkbox]{width:18px;height:18px;cursor:pointer;flex-shrink:0;accent-color:#2F78C4}
.member-card-header .info{flex:1}
.member-card-header .info .name{font-weight:700;color:#000048;font-size:15px}
.member-card-header .info .meta{color:#53565A;font-size:12px;margin-top:2px}
.member-card-header .gap-count{font-weight:700;font-size:18px;padding:6px 14px;border-radius:0}
.member-card-header .gap-count.has-gaps{background:rgba(184,31,45,0.08);color:#B81F2D}
.member-card-header .gap-count.no-gaps{background:rgba(45,184,31,0.1);color:#2DB81F}
.member-card-body{padding:0 20px 14px 50px;display:none}
.member-card-body.show{display:block}
.gap-table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
.gap-table th{background:rgba(47,120,196,0.08);color:#000048;padding:8px 10px;text-align:left;font-size:11px;text-transform:uppercase}
.gap-table td{padding:8px 10px;border-bottom:1px solid #E8E8E6;color:#000048}

.approve-btn{background:#26EFE9;color:#000048;padding:12px 36px;border-radius:999px;font-size:15px;font-weight:700;cursor:pointer;border:none;transition:background 0.2s}
.approve-btn:hover{background:#06C7CC}
.approve-btn:disabled{background:#97999B;color:#fff;cursor:not-allowed}
.cancel-btn{background:#E8E8E6;color:#000048;padding:12px 28px;border-radius:999px;font-size:14px;font-weight:600;cursor:pointer;border:none}
.cancel-btn:hover{background:#D0D0CE}
.selected-count{font-size:14px;color:#53565A}

/* Processing overlay */
.processing-overlay{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,72,0.6);z-index:2000;align-items:center;justify-content:center}
.processing-overlay.show{display:flex}
.processing-box{background:#fff;border-radius:0;padding:48px;text-align:center;max-width:500px}
.processing-box h2{color:#000048;margin-bottom:12px}
.processing-box p{color:#53565A;font-size:14px;margin-bottom:24px}
.spinner{width:48px;height:48px;border:4px solid #E8E8E6;border-top:4px solid #000048;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}
@keyframes spin{to{transform:rotate(360deg)}}

/* Results */
.results-area{display:none;margin-top:24px}
.results-area.show{display:block}
.result-card{background:#fff;border-radius:0;padding:16px 20px;margin-bottom:12px;display:flex;align-items:center;gap:16px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}
.result-card .icon{font-size:28px}
.result-card .info{flex:1}
.result-card .info .name{font-weight:700;font-size:15px;color:#000048}
.result-card .info .detail{color:#53565A;font-size:12px;margin-top:2px}
.result-card .status-badge{padding:6px 14px;border-radius:999px;font-size:12px;font-weight:600}
.result-card .status-badge.success{background:rgba(45,184,31,0.1);color:#2DB81F}
.result-card .status-badge.error{background:rgba(184,31,45,0.08);color:#B81F2D}
</style></head><body>
<div class="header">
  <h1>&#128228; Bulk Upload Members</h1>
  <a href="/api/v1/landing">&larr; Back to Home</a>
</div>

<div class="upload-area" id="uploadArea">
  <h2>Upload Patient Excel File</h2>
  <p>Drag & drop your Excel file here, or click to browse.<br>
     Required columns: <strong>Name, DOB, Gender, Email</strong><br>
     Optional: Phone, PCPID, PlanID, ZIP, ChronicConditions, InsuranceType, EnrollmentStart, EnrollmentEnd, PriorScreenings (e.g. BCS:2025-06-15;COL:2024-03-20)</p>
  <input type="file" id="fileInput" accept=".xlsx,.xls">
  <button class="upload-btn" id="uploadBtn" onclick="document.getElementById('fileInput').click()">Choose Excel File</button>
  <br><span class="template-link" onclick="downloadTemplate()">Download sample template</span>
  <div class="progress-bar" id="progressBar"><div class="fill" id="progressFill"></div></div>
  <div class="status-msg" id="statusMsg"></div>
</div>

<!-- Preview Modal -->
<div class="modal-overlay" id="previewModal">
  <div class="modal">
    <div class="modal-header">
      <h2>&#128269; Care Gap Analysis Preview</h2>
      <button class="modal-close" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-body" id="previewBody"></div>
    <div class="modal-footer">
      <div>
        <button class="cancel-btn" onclick="closeModal()">Cancel</button>
        <span class="selected-count" id="selectedCount" style="margin-left:16px"></span>
      </div>
      <button class="approve-btn" id="approveBtn" onclick="approveAndProcess()">Approve & Start Analysis</button>
    </div>
  </div>
</div>

<!-- Processing Overlay -->
<div class="processing-overlay" id="processingOverlay">
  <div class="processing-box">
    <div class="spinner"></div>
    <h2>Processing Members...</h2>
    <p id="processingMsg">Running 6-agent AI analysis and sending outreach emails simultaneously for all selected members. This may take a few minutes.</p>
  </div>
</div>

<!-- Results Area -->
<div class="results-area" id="resultsArea">
  <h2 style="color:#000048;margin-bottom:16px">&#9989; Processing Complete</h2>
  <div id="resultsContainer"></div>
  <div style="text-align:center;margin-top:24px">
    <button class="upload-btn" onclick="location.reload()">Upload Another File</button>
    <a href="/api/v1/members/dashboard-page" style="margin-left:16px;color:#000048;font-weight:600;text-decoration:none">View Members Dashboard &rarr;</a>
  </div>
</div>

<script>
let uploadedMembers=[];

// Drag and drop
const area=document.getElementById('uploadArea');
area.addEventListener('dragover',e=>{e.preventDefault();area.classList.add('dragover');});
area.addEventListener('dragleave',()=>area.classList.remove('dragover'));
area.addEventListener('drop',e=>{
  e.preventDefault();area.classList.remove('dragover');
  if(e.dataTransfer.files.length){document.getElementById('fileInput').files=e.dataTransfer.files;handleFile();}
});
document.getElementById('fileInput').addEventListener('change',handleFile);

async function handleFile(){
  const file=document.getElementById('fileInput').files[0];
  if(!file)return;
  const btn=document.getElementById('uploadBtn');
  const bar=document.getElementById('progressBar');
  const fill=document.getElementById('progressFill');
  const msg=document.getElementById('statusMsg');

  btn.disabled=true;btn.textContent='Uploading...';
  bar.style.display='block';fill.style.width='30%';
  msg.textContent='Uploading and analyzing patient data...';

  const formData=new FormData();
  formData.append('file',file);

  try{
    fill.style.width='60%';
    const res=await fetch('/api/v1/members/bulk-upload',{method:'POST',body:formData});
    fill.style.width='90%';
    const data=await res.json();
    fill.style.width='100%';

    if(data.status==='error'){
      msg.textContent='Error: '+data.error;
      msg.style.color='#dc3545';
      btn.disabled=false;btn.textContent='Choose Excel File';
      return;
    }

    uploadedMembers=data.members||[];
    msg.textContent=`Successfully processed ${data.total_uploaded} members. Opening preview...`;
    msg.style.color='#10b981';

    setTimeout(()=>showPreview(uploadedMembers),500);
  }catch(e){
    msg.textContent='Upload failed: '+e.message;msg.style.color='#dc3545';
  }
  btn.disabled=false;btn.textContent='Choose Excel File';
}

function showPreview(members){
  const body=document.getElementById('previewBody');
  const totalMembers=members.length;
  const totalGaps=members.reduce((sum,m)=>(m.open_gaps||[]).length+sum,0);
  const withGaps=members.filter(m=>(m.open_gaps||[]).length>0).length;
  const compliant=totalMembers-withGaps;

  let html=`
    <div class="summary-bar">
      <div class="summary-item"><div class="num">${totalMembers}</div><div class="lbl">Total Members</div></div>
      <div class="summary-item"><div class="num">${totalGaps}</div><div class="lbl">Care Gaps Found</div></div>
      <div class="summary-item"><div class="num">${withGaps}</div><div class="lbl">Members with Gaps</div></div>
      <div class="summary-item"><div class="num">${compliant}</div><div class="lbl">Compliant</div></div>
    </div>
    <div class="select-all-row">
      <input type="checkbox" id="selectAll" checked onchange="toggleSelectAll()">
      <label for="selectAll">Select / Deselect All Members</label>
    </div>
  `;

  members.forEach((m,i)=>{
    if(m.error){
      html+=`<div class="member-card" style="border-color:#dc3545"><div class="member-card-header">
        <div class="info"><div class="name">${m.name||'Unknown'}</div><div class="meta" style="color:#dc3545">Error: ${m.error}</div></div>
      </div></div>`;
      return;
    }
    const gaps=m.open_gaps||[];
    const hasGaps=gaps.length>0;
    html+=`
    <div class="member-card">
      <div class="member-card-header" onclick="toggleCard(${i})">
        <input type="checkbox" class="member-check" data-idx="${i}" ${hasGaps?'checked':''} onclick="event.stopPropagation();updateCount()">
        <div class="info">
          <div class="name">${m.name} <span style="color:#888;font-weight:400;font-size:12px">(${m.member_id})</span></div>
          <div class="meta">${m.age_str||''} | ${m.gender==='F'?'Female':'Male'} | ${m.email||'N/A'} | ${(m.chronic_conditions||[]).join(', ')||'No chronic conditions'}</div>
        </div>
        <div class="gap-count ${hasGaps?'has-gaps':'no-gaps'}">${gaps.length} gap${gaps.length!==1?'s':''}</div>
      </div>
      <div class="member-card-body" id="card_${i}">
        ${hasGaps?`<table class="gap-table"><thead><tr><th>Measure</th><th>Code</th><th>CPT</th><th>ICD-10</th><th>Description</th></tr></thead><tbody>
          ${gaps.map(g=>`<tr>
            <td><strong>${g.measure_name||g.measure_id}</strong></td>
            <td>${g.measure_id}</td>
            <td><code>${g.primary_cpt_code||'N/A'}</code></td>
            <td><code>${g.primary_icd10||'N/A'}</code></td>
            <td style="max-width:300px;font-size:12px;color:#555">${(g.resolution_guide||'').substring(0,120)}${(g.resolution_guide||'').length>120?'...':''}</td>
          </tr>`).join('')}
        </tbody></table>`
        :`<p style="color:#10b981;font-weight:600;padding:8px 0">&#9989; Member is compliant — no care gaps detected.</p>`}
        <div style="margin-top:8px;font-size:12px;color:#888">
          Compliant: ${(m.compliant||[]).join(', ')||'None'} &nbsp;|&nbsp; Excluded: ${(m.excluded||[]).join(', ')||'None'}
        </div>
      </div>
    </div>`;
  });

  body.innerHTML=html;
  document.getElementById('previewModal').classList.add('show');
  updateCount();
}

function toggleCard(i){
  document.getElementById('card_'+i).classList.toggle('show');
}

function toggleSelectAll(){
  const checked=document.getElementById('selectAll').checked;
  document.querySelectorAll('.member-check').forEach(cb=>cb.checked=checked);
  updateCount();
}

function updateCount(){
  const checked=document.querySelectorAll('.member-check:checked').length;
  const total=document.querySelectorAll('.member-check').length;
  document.getElementById('selectedCount').textContent=`${checked} of ${total} members selected`;
  document.getElementById('approveBtn').disabled=checked===0;
}

function closeModal(){
  document.getElementById('previewModal').classList.remove('show');
}

async function approveAndProcess(){
  const selected=[];
  document.querySelectorAll('.member-check:checked').forEach(cb=>{
    const idx=parseInt(cb.dataset.idx);
    const m=uploadedMembers[idx];
    if(m&&!m.error)selected.push({member_id:m.member_id,name:m.name,email:m.email});
  });
  if(!selected.length){alert('Please select at least one member.');return;}

  closeModal();
  document.getElementById('uploadArea').style.display='none';
  const overlay=document.getElementById('processingOverlay');
  overlay.classList.add('show');
  document.getElementById('processingMsg').textContent=
    `Running 6-agent AI analysis and sending outreach emails simultaneously for ${selected.length} member(s). This may take a few minutes.`;

  try{
    const res=await fetch('/api/v1/members/bulk-process',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({members:selected})
    });
    const data=await res.json();
    overlay.classList.remove('show');

    // Show results
    const container=document.getElementById('resultsContainer');
    const results=data.results||[];
    container.innerHTML=results.map(r=>`
      <div class="result-card">
        <div class="icon">${r.status==='completed'?'&#9989;':'&#10060;'}</div>
        <div class="info">
          <div class="name">${r.name} (${r.member_id})</div>
          <div class="detail">${r.status==='completed'?
            (r.email_sent?'Analysis complete &bull; Outreach email sent':'Analysis complete &bull; No email sent'):
            'Error: '+(r.error||'Unknown error')}</div>
        </div>
        <span class="status-badge ${r.status==='completed'?'success':'error'}">${r.status==='completed'?'Completed':'Failed'}</span>
      </div>
    `).join('');

    document.getElementById('resultsArea').classList.add('show');
  }catch(e){
    overlay.classList.remove('show');
    alert('Processing failed: '+e.message);
  }
}

function downloadTemplate(){
  window.open('/api/v1/members/bulk-upload-template','_blank');
}
</script></body></html>"""


@app.route("/api/v1/members/bulk-upload-template")
def download_bulk_template():
    """Serve the sample Excel template for bulk upload."""
    import os
    template_path = os.path.join(os.path.dirname(__file__), "bulk_upload_template.xlsx")
    if os.path.exists(template_path):
        from flask import send_file
        return send_file(template_path, as_attachment=True,
                         download_name="bulk_upload_template.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return jsonify({"error": "Template file not found"}), 404


# ── Reference DB — Persona Graph Endpoints ───────────────────────────────────

@app.route("/api/v1/reference/graph", methods=["GET"])
def reference_graph():
    """Return persona-based nodes + edges from the reference DB for dashboard visualization."""
    try:
        from src.persona_sync import get_dashboard_graph
        result = get_dashboard_graph()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Reference graph error: {e}", exc_info=True)
        return jsonify({"nodes": [], "edges": []})


@app.route("/api/v1/reference/member/<member_id>/personas", methods=["GET"])
def reference_member_personas(member_id):
    """Return the persona + care-gap lifecycle sub-graph for a specific member."""
    try:
        from src.persona_sync import get_member_lifecycle_graph, sync_appointment_booked, sync_gap_closed

        # ── Reconcile: check original DB for appointments not yet synced ──
        try:
            kg = get_knowledge_graph()
            appointments = kg.run_query("""
                MATCH (m:Member {member_id: $mid})-[:HAS_APPOINTMENT]->(a:Appointment)
                RETURN a.appointment_id AS appointment_id,
                       a.care_gap_id    AS care_gap_id,
                       a.appointment_date AS appointment_date,
                       a.lab_location   AS lab_location,
                       a.status         AS status
            """, {"mid": member_id})
            for appt in appointments:
                cgid = appt.get("care_gap_id")
                if not cgid:
                    continue
                # Check if this gap already has appointment_booked stage in ref DB
                from src.persona_sync import _ref
                ref = _ref()
                check = ref.run_query(
                    "MATCH (g:CareGap {gap_id: $gid}) RETURN g.stage AS stage",
                    {"gid": cgid}
                )
                current_stage = (check[0]["stage"] if check else None)
                is_completed = appt.get("status") == "Completed"

                # Already fully synced
                if current_stage == "gap_closed":
                    continue

                # Sync appointment booking if not yet at that stage
                if current_stage not in ("appointment_booked", "gap_closed"):
                    logger.info(f"[RECONCILE] Syncing appointment for gap {cgid} (current stage: {current_stage})")
                    sync_appointment_booked(
                        member_id=member_id, care_gap_id=cgid,
                        appointment_id=appt.get("appointment_id", ""),
                        appointment_date=appt.get("appointment_date", ""),
                        lab_location=appt.get("lab_location", ""),
                    )

                # If appointment completed in original DB, close gap in ref DB
                if is_completed and current_stage != "gap_closed":
                    logger.info(f"[RECONCILE] Syncing gap closure for {cgid} (appointment completed)")
                    sync_gap_closed(member_id=member_id, care_gap_id=cgid)

            # Also check for gaps closed directly (without appointment) in original DB
            closed_gaps = kg.run_query("""
                MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
                WHERE g.is_open = false
                RETURN g.care_gap_id AS care_gap_id
            """, {"mid": member_id})
            for cg in closed_gaps:
                cgid = cg.get("care_gap_id")
                if not cgid:
                    continue
                from src.persona_sync import _ref
                ref = _ref()
                check = ref.run_query(
                    "MATCH (g:CareGap {gap_id: $gid}) RETURN g.stage AS stage",
                    {"gid": cgid}
                )
                current_stage = (check[0]["stage"] if check else None)
                if current_stage != "gap_closed":
                    logger.info(f"[RECONCILE] Syncing closed gap {cgid} (current stage: {current_stage})")
                    sync_gap_closed(member_id=member_id, care_gap_id=cgid)

        except Exception as rec_err:
            logger.warning(f"[RECONCILE] Reconciliation failed: {rec_err}")

        result = get_member_lifecycle_graph(member_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Reference member personas error: {e}", exc_info=True)
        return jsonify({"nodes": [], "edges": [], "member": None, "lifecycle": []})


@app.route("/api/v1/reference/sync-all", methods=["POST"])
def sync_all_to_reference():
    """Bulk sync all existing members from original DB into the persona reference DB."""
    try:
        from src.persona_sync import bootstrap_persona_schema, sync_all_existing_members
        bootstrap_persona_schema()
        count = sync_all_existing_members()
        return jsonify({"status": "success", "synced": count})
    except Exception as e:
        logger.error(f"Sync-all error: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


# Register member portal Blueprint
from src.member_portal import portal_bp
app.register_blueprint(portal_bp)


if __name__ == "__main__":
    # Bootstrap persona reference DB schema on startup
    try:
        from src.persona_sync import bootstrap_persona_schema
        bootstrap_persona_schema()
        logger.info("Persona reference DB schema ready")
    except Exception as e:
        logger.warning(f"Persona schema bootstrap skipped: {e}")

    app.run(debug=True, port=5001, use_reloader=False)
