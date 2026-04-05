"""
REST API endpoints for Care Gap workflows.
Run: python -m src.care_gap_api
"""
import json
import logging
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from src.care_gap_data_loader import load_all
from src.care_gap_agents import CareGapAgentSystem
from src.care_gap_neo4j import (
    get_member_open_gaps, get_member_profile, get_measure_comprehensive,
    get_member_claims_cpt_codes, check_member_exclusions
)
from src.neo4j_connection import get_knowledge_graph

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend
agent_system = None
logger = logging.getLogger(__name__)


def get_agents():
    global agent_system
    if agent_system is None:
        agent_system = CareGapAgentSystem()
    return agent_system


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
    """Get all members with their care gap status."""
    try:
        kg = get_knowledge_graph()
        members = kg.run_query("""
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WITH m,
                 count(DISTINCT CASE WHEN g.is_open = true  THEN g.care_gap_id ELSE null END) AS open_gaps,
                 count(DISTINCT CASE WHEN g.is_open = false THEN g.care_gap_id ELSE null END) AS closed_gaps
            OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
            RETURN m.member_id as member_id,
                   m.name as name,
                   m.age_str as age,
                   m.gender as gender,
                   m.dob as dob,
                   open_gaps,
                   closed_gaps,
                   p.name as pcp_name,
                   p.provider_id as pcp_id
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

        return jsonify({
            "member_id": member_id,
            "profile": profile,
            "open_gaps": gaps,
            "closed_gaps": closed_gaps,
            "claims": claims,
            "outreach_history": outreach,
            "appointments": appointments
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

        # ── Send professional email ───────────────────────────────────────
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
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">📅 Appointment Details</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">Screening Type</td><td style="padding:10px 16px;">{measure_name}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Date</td><td style="padding:10px 16px;">{friendly_date}</td></tr>
    <tr><td style="padding:10px 16px; font-weight:600;">Time</td><td style="padding:10px 16px;">{friendly_time}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Appointment ID</td><td style="padding:10px 16px; font-family:monospace;">{appointment_id}</td></tr>
  </table>

  <table style="width:100%; border-collapse:collapse; margin:24px 0; background:#f0f4ff; border-radius:6px; overflow:hidden;">
    <tr style="background:#005EB8; color:white;">
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">🏥 Lab &amp; Specialist Information</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">Lab Number</td><td style="padding:10px 16px;">{lab_info['lab_number']}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Lab Location</td><td style="padding:10px 16px;">{lab_info['lab_location']}</td></tr>
    <tr><td style="padding:10px 16px; font-weight:600;">Assigned Specialist</td><td style="padding:10px 16px;">{lab_info['lab_specialist']}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Specialty</td><td style="padding:10px 16px;">{lab_info['specialty']}</td></tr>
  </table>

  <table style="width:100%; border-collapse:collapse; margin:24px 0; background:#f0f4ff; border-radius:6px; overflow:hidden;">
    <tr style="background:#004494; color:white;">
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">🩺 Clinical Codes</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">CPT Code(s)</td><td style="padding:10px 16px; font-family:monospace;">{cpt_codes or "Per provider order"}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">ICD-10 Code(s)</td><td style="padding:10px 16px; font-family:monospace;">{icd_codes or "Per diagnosis"}</td></tr>
    <tr><td style="padding:10px 16px; font-weight:600;">Referring Provider</td><td style="padding:10px 16px;">{pcp_name}</td></tr>
  </table>

  <table style="width:100%; border-collapse:collapse; margin:24px 0; background:#f0f4ff; border-radius:6px; overflow:hidden;">
    <tr style="background:#1a6b3c; color:white;">
      <th colspan="2" style="padding:12px 16px; text-align:left; font-size:15px;">💳 Insurance Information</th>
    </tr>
    <tr><td style="padding:10px 16px; font-weight:600; width:40%;">Plan ID</td><td style="padding:10px 16px; font-family:monospace;">{plan_id}</td></tr>
    <tr style="background:#e8eeff;"><td style="padding:10px 16px; font-weight:600;">Insurance Type</td><td style="padding:10px 16px;">{insurance}</td></tr>
    <tr><td style="padding:10px 16px; font-weight:600;">Member ID</td><td style="padding:10px 16px; font-family:monospace;">{member_id}</td></tr>
  </table>

  <div style="background:#fff8e1; border-left:4px solid #f59e0b; padding:16px; border-radius:4px; margin:24px 0;">
    <strong>📋 Pre-Appointment Instructions:</strong>
    <ul style="margin:8px 0; padding-left:20px;">
      <li>Please arrive 15 minutes before your scheduled time.</li>
      <li>Bring a valid government-issued photo ID and your insurance card.</li>
      <li>Wear comfortable, loose-fitting clothing appropriate for the screening.</li>
      <li>If you need to reschedule, please contact us at least 24 hours in advance.</li>
    </ul>
  </div>

  <p>If you have any questions, please contact your care management team. Do not reply to this email.</p>
  <hr style="border:none; border-top:1px solid #dce3f5; margin:24px 0;">
  <p style="color:#888; font-size:12px;">This is an automated message from the HealthCare Management Portal. Appointment ID: {appointment_id}</p>
</div>
</body></html>"""

            try:
                client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
                message = {
                    "senderAddress": sender,
                    "recipients": {"to": [{"address": member_email}]},
                    "content": {"subject": subject, "html": body_html},
                }
                poller = client.begin_send(message)
                poller.result()
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
                f"Lab: {lab_info['lab_number']} - {lab_info['lab_location']}\n"
                f"Specialist: {lab_info['lab_specialist']}\n"
                f"CPT Code: {cpt_codes or 'Per provider order'}\n"
                f"ICD-10 Code: {icd_codes or 'Per diagnosis'}\n"
                f"Appointment ID: {appointment_id}"
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
        
        # Create enrollment relationships
        merge_enrollment(
            member_id=data["member_id"],
            plan_id=data["plan_id"],
            pcp_id=data["pcp_id"],
            effective_from=data.get("enrollment_start", data["dob"]),
            effective_to=data.get("enrollment_end", "2025-12-31")
        )
        
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
        from openai import AzureOpenAI
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

        client = AzureOpenAI(
            azure_endpoint=cfg.endpoint,
            api_key=cfg.openai_api_key,
            api_version=cfg.azure_openai_api_version,
        )

        messages = [{"role": "system", "content": system_msg}]
        # Include up to last 10 turns of conversation history
        for h in history[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": message})

        completion = client.chat.completions.create(
            model=cfg.openai_model,
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )

        reply = completion.choices[0].message.content
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

        sender     = cfg.azure_communication_sender
        conn_str   = cfg.azure_communication_connection_string

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
        poller = client.begin_send(message)
        result = poller.result()

        # Persist in Neo4j
        email_id  = f"EMAIL-{member_id}-{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().isoformat()
        merge_email(
            email_id=email_id, member_id=member_id,
            subject=subject, body=body,
            from_email=sender, to_email=to_email,
            timestamp=timestamp, direction="sent", is_read=True,
        )

        return jsonify({
            "status": "sent",
            "email_id": email_id,
            "message_id": result.get("id", "") if isinstance(result, dict) else str(result),
        })

    except Exception as e:
        logger.exception("send_member_email error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/email/mark-read/<email_id>", methods=["PATCH"])
def mark_email_read_endpoint(email_id):
    """Mark an email as read."""
    try:
        from src.care_gap_neo4j import mark_email_read
        mark_email_read(email_id)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001, use_reloader=False)
