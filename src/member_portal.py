"""
Member-facing Portal — Flask Blueprint.

Serves HTML pages linked from automated outreach emails so members can:
  1. Review their care gap analysis and respond Yes / No per gap
  2. Pick available appointment time slots for accepted gaps
  3. Receive a booking confirmation (also sent via email)

Security: every portal URL contains an HMAC token derived from the member_id
and a server-side secret.  No login required — the link *is* the credential.
"""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from src.neo4j_connection import get_knowledge_graph
from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_member_profile,
    merge_appointment,
    get_appointment,
    merge_outreach,
)

portal_bp = Blueprint("member_portal", __name__)

_PORTAL_SECRET = "hedis-care-gap-portal-2025"  # demo secret


# ── Token helpers ────────────────────────────────────────────────────────────

def _make_token(member_id: str) -> str:
    return hmac.new(
        _PORTAL_SECRET.encode(), member_id.encode(), hashlib.sha256
    ).hexdigest()[:24]


def _verify_token(member_id: str, token: str) -> bool:
    return hmac.compare_digest(_make_token(member_id), token)


def get_portal_url(member_id: str) -> str:
    """Return the base portal URL for a member (used when composing emails)."""
    token = _make_token(member_id)
    return f"http://localhost:5001/portal/{member_id}/{token}"


# ── Available time-slot generator ────────────────────────────────────────────

def _generate_slots(days_ahead: int = 7):
    """Generate 30-min appointment slots for the next *days_ahead* business days."""
    slots = []
    day = datetime.now() + timedelta(days=1)
    biz_days = 0
    while biz_days < days_ahead:
        if day.weekday() < 5:  # Mon-Fri
            for hour in range(8, 17):
                for minute in (0, 30):
                    if hour == 16 and minute == 30:
                        continue
                    slots.append({
                        "date": day.strftime("%Y-%m-%d"),
                        "time": f"{hour:02d}:{minute:02d}",
                        "display_date": day.strftime("%A, %B %d, %Y"),
                        "display_time": f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}",
                    })
            biz_days += 1
        day += timedelta(days=1)
    return slots


def _get_booked_slots():
    """Return set of (date, time) tuples already booked across all members."""
    kg = get_knowledge_graph()
    rows = kg.run_query("""
        MATCH (a:Appointment)
        WHERE a.status <> 'Completed'
        RETURN a.appointment_date AS d, a.appointment_time AS t
    """, {})
    return {(r["d"], r["t"]) for r in rows if r["d"] and r["t"]}


# ── 1. Gap response page — member reviews gaps and clicks Yes / No ───────────

@portal_bp.route("/portal/<member_id>/<token>", methods=["GET"])
def portal_gap_review(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    profile = get_member_profile(member_id)
    if not profile:
        return "<h2>Member not found.</h2>", 404

    gaps = get_member_open_gaps(member_id)
    name = profile.get("name", member_id)

    if not gaps:
        return _html_page("No Open Care Gaps", f"""
            <div class="card">
              <h2>Hi {name},</h2>
              <p>Great news — you currently have <strong>no open care gaps</strong>.
              You are compliant with all quality measures. Keep up the great work!</p>
            </div>
        """)

    gap_cards = ""
    for g in gaps:
        gap_cards += f"""
        <div class="gap-card">
          <div class="gap-title">{g['measure_name']} <span class="badge">{g['measure_id']}</span></div>
          <p class="gap-desc">{g.get('resolution_guide') or ''}</p>
          <table class="gap-codes">
            <tr><td><strong>CPT Code</strong></td><td><code>{g.get('primary_cpt_code') or 'N/A'}</code></td></tr>
            <tr><td><strong>ICD-10</strong></td><td><code>{g.get('primary_icd10') or 'N/A'}</code></td></tr>
            <tr><td><strong>Lookback</strong></td><td>{g.get('lookback_months') or '12'} months</td></tr>
          </table>
          <div class="btn-row">
            <label class="radio-btn yes-btn">
              <input type="checkbox" name="accepted" value="{g['care_gap_id']}" checked />
              <span>Yes, I want this screening</span>
            </label>
          </div>
        </div>
        """

    return _html_page(f"Care Gap Analysis — {name}", f"""
        <div class="header-banner">
          <h1>HealthCare Management Portal</h1>
          <p>Preventive Care Analysis for <strong>{name}</strong></p>
        </div>
        <div class="card">
          <h2>Your Recommended Screenings</h2>
          <p>Our care team has identified the following preventive screenings for you.
             Please review each one and uncheck any you do <em>not</em> wish to schedule.</p>
          <form method="POST" action="/portal/{member_id}/{token}/respond">
            {gap_cards}
            <button type="submit" class="primary-btn">Continue to Scheduling &rarr;</button>
          </form>
        </div>
    """)


# ── 2. Process Yes/No responses and redirect to scheduling ──────────────────

@portal_bp.route("/portal/<member_id>/<token>/respond", methods=["POST"])
def portal_gap_respond(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    accepted_ids = request.form.getlist("accepted")  # list of care_gap_ids

    if not accepted_ids:
        return _html_page("No Screenings Selected", f"""
            <div class="card">
              <h2>No screenings selected</h2>
              <p>You did not select any screenings. If this was a mistake,
              <a href="/portal/{member_id}/{token}">go back</a> and try again.</p>
              <p>Thank you for reviewing your care gap analysis.</p>
            </div>
        """)

    # Store accepted gap IDs in query string for the scheduling page
    gap_params = "&".join(f"gap={gid}" for gid in accepted_ids)
    return f"""<html><head><meta http-equiv="refresh" content="0;url=/portal/{member_id}/{token}/schedule?{gap_params}" /></head></html>"""


# ── 3. Scheduling page — pick time slots ─────────────────────────────────────

@portal_bp.route("/portal/<member_id>/<token>/schedule", methods=["GET"])
def portal_schedule(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    profile = get_member_profile(member_id)
    name = profile.get("name", member_id) if profile else member_id
    accepted_gap_ids = request.args.getlist("gap")

    if not accepted_gap_ids:
        return _html_page("Error", "<div class='card'><p>No gaps specified.</p></div>")

    # Fetch gap details
    gaps = get_member_open_gaps(member_id)
    selected_gaps = [g for g in gaps if g["care_gap_id"] in accepted_gap_ids]

    if not selected_gaps:
        return _html_page("Error", "<div class='card'><p>No matching open gaps found.</p></div>")

    # Generate available slots and mark booked ones
    all_slots = _generate_slots(7)
    booked = _get_booked_slots()

    # Lab assignment map (same as care_gap_api.py)
    LAB_MAP = {
        "BCS": "Radiology & Mammography Unit, 2nd Floor",
        "CCS": "Cytology & Gynecology Lab, 1st Floor",
        "COL": "Gastroenterology & Endoscopy Suite, 3rd Floor",
        "CBP": "Cardiology Clinic, 4th Floor",
        "GSD": "Diabetes & Endocrinology Center, 2nd Floor",
        "EED": "Diabetes & Endocrinology Center, 2nd Floor",
        "KED": "Renal & Nephrology Lab, 2nd Floor",
        "BPD": "Diabetes & Endocrinology Center, 2nd Floor",
        "AAP": "General Screening Lab, 1st Floor",
        "CHL": "General Screening Lab, 1st Floor",
    }

    # Group slots by date for display
    from collections import OrderedDict
    slots_by_date = OrderedDict()
    for s in all_slots:
        slots_by_date.setdefault(s["date"], []).append(s)

    gap_sections = ""
    for g in selected_gaps:
        location = LAB_MAP.get(g["measure_id"], "General Screening Lab, 1st Floor")

        slot_html = ""
        for date_key, day_slots in slots_by_date.items():
            display_date = day_slots[0]["display_date"]
            slot_html += f'<div class="date-header">{display_date}</div><div class="slot-grid">'
            for s in day_slots:
                is_booked = (s["date"], s["time"]) in booked
                disabled = "disabled" if is_booked else ""
                booked_label = ' (Booked)' if is_booked else ""
                slot_html += f"""
                <label class="slot-label {'slot-disabled' if is_booked else ''}">
                  <input type="radio" name="slot_{g['care_gap_id']}" value="{s['date']}|{s['time']}" {disabled} />
                  <span>{s['display_time']}{booked_label}</span>
                </label>"""
            slot_html += "</div>"

        gap_sections += f"""
        <div class="schedule-gap">
          <div class="gap-title">{g['measure_name']} <span class="badge">{g['measure_id']}</span></div>
          <p class="gap-location">Location: {location}</p>
          <p>Select a date and time for your appointment:</p>
          <input type="hidden" name="gap_ids" value="{g['care_gap_id']}" />
          <input type="hidden" name="measure_{g['care_gap_id']}" value="{g['measure_id']}" />
          <input type="hidden" name="measure_name_{g['care_gap_id']}" value="{g['measure_name']}" />
          <div class="slots-container">{slot_html}</div>
        </div>
        """

    return _html_page(f"Schedule Appointments — {name}", f"""
        <div class="header-banner">
          <h1>HealthCare Management Portal</h1>
          <p>Schedule Your Appointments — <strong>{name}</strong></p>
        </div>
        <div class="card">
          <h2>Choose Your Preferred Time Slots</h2>
          <p>Select one time slot per screening. Greyed-out slots are already booked.</p>
          <form method="POST" action="/portal/{member_id}/{token}/book">
            {gap_sections}
            <button type="submit" class="primary-btn">Confirm &amp; Book Appointments</button>
          </form>
        </div>
    """)


# ── 4. Book appointments and show confirmation ──────────────────────────────

@portal_bp.route("/portal/<member_id>/<token>/book", methods=["POST"])
def portal_book(member_id, token):
    if not _verify_token(member_id, token):
        return "<h2>Invalid or expired link.</h2>", 403

    profile = get_member_profile(member_id)
    name = profile.get("name", member_id) if profile else member_id
    gap_ids = request.form.getlist("gap_ids")

    if not gap_ids:
        return _html_page("Error", "<div class='card'><p>No gaps to book.</p></div>")

    from src.care_gap_api import _get_hedis_codes

    LAB_MAP = {
        "BCS": {"lab_number": "LAB-02", "lab_specialist": "Dr. Sarah Mitchell",
                "lab_location": "Radiology & Mammography Unit, 2nd Floor"},
        "CCS": {"lab_number": "LAB-01", "lab_specialist": "Dr. James Rodriguez",
                "lab_location": "Cytology & Gynecology Lab, 1st Floor"},
        "COL": {"lab_number": "LAB-03", "lab_specialist": "Dr. Emily Chen",
                "lab_location": "Gastroenterology & Endoscopy Suite, 3rd Floor"},
        "CBP": {"lab_number": "LAB-04", "lab_specialist": "Dr. Michael Thompson",
                "lab_location": "Cardiology Clinic, 4th Floor"},
        "GSD": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
        "EED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
        "KED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Renal & Nephrology Lab, 2nd Floor"},
        "BPD": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
                "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
    }
    DEFAULT_LAB = {"lab_number": "LAB-01", "lab_specialist": "On-Call Specialist",
                   "lab_location": "General Screening Lab, 1st Floor"}

    bookings_html = ""
    booked_appointments = []

    for gid in gap_ids:
        slot_val = request.form.get(f"slot_{gid}", "")
        if not slot_val or "|" not in slot_val:
            continue

        appt_date, appt_time = slot_val.split("|", 1)
        measure_id = request.form.get(f"measure_{gid}", "")
        measure_name = request.form.get(f"measure_name_{gid}", measure_id)
        lab = LAB_MAP.get(measure_id, DEFAULT_LAB)
        cpt_codes, icd_codes = _get_hedis_codes(measure_id)

        appointment_id = f"APT-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
        merge_appointment(
            appointment_id=appointment_id,
            member_id=member_id,
            measure_id=measure_id,
            appointment_date=appt_date,
            appointment_time=appt_time,
            lab_number=lab["lab_number"],
            lab_specialist=lab["lab_specialist"],
            lab_location=lab["lab_location"],
            screening_name=measure_name,
            cpt_codes=cpt_codes,
            icd_codes=icd_codes,
            provider_id=profile.get("pcp_id", ""),
            care_gap_id=gid,
        )

        # Create outreach record for the scheduling
        outreach_id = f"OUT-SCHED-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
        merge_outreach(
            outreach_id=outreach_id,
            care_gap_id=gid,
            member_id=member_id,
            care_manager_id="AUTO-AGENT",
            channel="Member Portal",
            date=datetime.now().strftime("%Y-%m-%d"),
            status="Scheduled",
        )

        # Format display
        try:
            dt = datetime.strptime(appt_date, "%Y-%m-%d")
            friendly_date = dt.strftime("%A, %B %d, %Y")
        except Exception:
            friendly_date = appt_date
        try:
            hh, mm = appt_time.split(":")
            h = int(hh)
            friendly_time = f"{h % 12 or 12}:{mm} {'AM' if h < 12 else 'PM'}"
        except Exception:
            friendly_time = appt_time

        bookings_html += f"""
        <div class="booking-card">
          <div class="gap-title">{measure_name} <span class="badge">{measure_id}</span></div>
          <table class="gap-codes">
            <tr><td><strong>Date</strong></td><td>{friendly_date}</td></tr>
            <tr><td><strong>Time</strong></td><td>{friendly_time}</td></tr>
            <tr><td><strong>Location</strong></td><td>{lab['lab_location']}</td></tr>
            <tr><td><strong>Specialist</strong></td><td>{lab['lab_specialist']}</td></tr>
            <tr><td><strong>CPT Code</strong></td><td><code>{cpt_codes}</code></td></tr>
            <tr><td><strong>ICD-10</strong></td><td><code>{icd_codes}</code></td></tr>
            <tr><td><strong>Appointment ID</strong></td><td><code>{appointment_id}</code></td></tr>
          </table>
        </div>
        """
        booked_appointments.append({
            "appointment_id": appointment_id,
            "measure_name": measure_name,
            "date": friendly_date,
            "time": friendly_time,
        })

    # Send confirmation email
    member_email = profile.get("email", "")
    if member_email and booked_appointments:
        _send_booking_confirmation_email(member_id, name, member_email, booked_appointments)

    if not bookings_html:
        return _html_page("No Slots Selected", f"""
            <div class="card">
              <h2>No time slots were selected</h2>
              <p>Please go back and select a time slot for each screening.</p>
              <a href="/portal/{member_id}/{token}" class="primary-btn">Go Back</a>
            </div>
        """)

    return _html_page(f"Appointments Confirmed — {name}", f"""
        <div class="header-banner success">
          <h1>HealthCare Management Portal</h1>
          <p>Appointments Confirmed!</p>
        </div>
        <div class="card">
          <div class="success-icon">&#10004;</div>
          <h2>Your appointments have been booked!</h2>
          <p>A confirmation email has been sent to <strong>{member_email or 'your registered email'}</strong>.</p>
          {bookings_html}
          <div class="info-box">
            <strong>Pre-Appointment Instructions:</strong>
            <ul>
              <li>Please arrive 15 minutes before your scheduled time.</li>
              <li>Bring a valid government-issued photo ID and your insurance card.</li>
              <li>Wear comfortable, loose-fitting clothing appropriate for the screening.</li>
              <li>If you need to reschedule, please contact your care manager.</li>
            </ul>
          </div>
        </div>
    """)


# ── Confirmation email sender ────────────────────────────────────────────────

def _send_booking_confirmation_email(member_id, name, email, appointments):
    """Send booking confirmation email via Azure Communication Services."""
    try:
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg
        from src.care_gap_neo4j import merge_email

        if not cfg.azure_communication_connection_string:
            return

        rows = ""
        for a in appointments:
            rows += f"""
            <tr>
              <td style="padding:10px 16px;">{a['measure_name']}</td>
              <td style="padding:10px 16px;">{a['date']}</td>
              <td style="padding:10px 16px;">{a['time']}</td>
              <td style="padding:10px 16px;font-family:monospace;">{a['appointment_id']}</td>
            </tr>"""

        html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:680px;margin:auto;">
<div style="background:#059669;padding:20px 32px;border-radius:8px 8px 0 0;">
  <h1 style="color:white;margin:0;font-size:22px;">HealthCare Management Portal</h1>
  <p style="color:#b3f5d9;margin:4px 0 0;">Appointment Booking Confirmation</p>
</div>
<div style="border:1px solid #dce3f5;border-top:none;padding:32px;border-radius:0 0 8px 8px;">
  <p style="font-size:16px;">Dear <strong>{name}</strong>,</p>
  <p>Your screening appointments have been successfully booked. Please review the details below.</p>
  <table style="width:100%;border-collapse:collapse;margin:24px 0;">
    <tr style="background:#059669;color:white;">
      <th style="padding:12px 16px;text-align:left;">Screening</th>
      <th style="padding:12px 16px;text-align:left;">Date</th>
      <th style="padding:12px 16px;text-align:left;">Time</th>
      <th style="padding:12px 16px;text-align:left;">Appointment ID</th>
    </tr>
    {rows}
  </table>
  <div style="background:#fff8e1;border-left:4px solid #f59e0b;padding:16px;border-radius:4px;margin:24px 0;">
    <strong>Pre-Appointment Instructions:</strong>
    <ul style="margin:8px 0;padding-left:20px;">
      <li>Arrive 15 minutes before your scheduled time.</li>
      <li>Bring a valid photo ID and insurance card.</li>
      <li>Wear comfortable clothing.</li>
    </ul>
  </div>
  <p style="color:#888;font-size:12px;">This is an automated message from the HealthCare Management Portal.</p>
</div>
</body></html>"""

        client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
        message = {
            "senderAddress": cfg.azure_communication_sender,
            "recipients": {"to": [{"address": email}]},
            "content": {
                "subject": f"Appointment Confirmation — {len(appointments)} Screening(s) Booked",
                "html": html,
            },
        }
        poller = client.begin_send(message)
        poller.result()

        # Persist email in Neo4j
        email_id = f"PORTAL-CONFIRM-{member_id}-{uuid.uuid4().hex[:8]}"
        merge_email(
            email_id=email_id,
            member_id=member_id,
            subject=f"Appointment Confirmation — {len(appointments)} Screening(s) Booked",
            body=f"Booking confirmation for {len(appointments)} appointment(s)",
            from_email=cfg.azure_communication_sender,
            to_email=email,
            timestamp=datetime.now().isoformat(),
            direction="sent",
            is_read=True,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Confirmation email failed: {e}")


# ── HTML template helper ─────────────────────────────────────────────────────

def _html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',Arial,sans-serif; background:#f0f4f8; color:#1a1a2e; line-height:1.6; }}
  .header-banner {{ background:#0033A1; color:white; padding:32px; text-align:center; }}
  .header-banner.success {{ background:#059669; }}
  .header-banner h1 {{ font-size:24px; margin-bottom:4px; }}
  .header-banner p {{ color:#b3c7f7; font-size:15px; }}
  .header-banner.success p {{ color:#b3f5d9; }}
  .card {{ max-width:780px; margin:32px auto; background:white; border-radius:12px; padding:32px; box-shadow:0 2px 12px rgba(0,0,0,0.08); }}
  h2 {{ font-size:20px; margin-bottom:16px; color:#0033A1; }}
  .gap-card, .schedule-gap, .booking-card {{ border:1px solid #e2e8f0; border-radius:10px; padding:20px; margin:16px 0; }}
  .gap-title {{ font-size:17px; font-weight:600; color:#1a1a2e; display:flex; align-items:center; gap:10px; }}
  .badge {{ background:#0033A1; color:white; font-size:11px; padding:3px 10px; border-radius:20px; font-weight:600; }}
  .gap-desc {{ color:#64748b; font-size:14px; margin:8px 0; }}
  .gap-location {{ color:#64748b; font-size:13px; margin:4px 0 12px; }}
  .gap-codes {{ margin:12px 0; font-size:14px; border-collapse:collapse; }}
  .gap-codes td {{ padding:4px 16px 4px 0; }}
  code {{ background:#f1f5f9; padding:2px 8px; border-radius:4px; font-size:13px; }}
  .btn-row {{ margin-top:12px; }}
  .radio-btn {{ display:inline-flex; align-items:center; gap:8px; cursor:pointer; padding:8px 16px; border:2px solid #059669; border-radius:8px; color:#059669; font-weight:600; font-size:14px; }}
  .radio-btn input {{ accent-color:#059669; width:18px; height:18px; }}
  .primary-btn {{ display:inline-block; background:#0033A1; color:white; border:none; padding:14px 32px; border-radius:8px; font-size:16px; font-weight:600; cursor:pointer; margin-top:20px; text-decoration:none; }}
  .primary-btn:hover {{ background:#002880; }}
  .success-icon {{ font-size:48px; color:#059669; text-align:center; margin:16px 0; }}
  .info-box {{ background:#f0f4ff; border-left:4px solid #0033A1; padding:16px; border-radius:4px; margin:20px 0; }}
  .info-box ul {{ padding-left:20px; margin-top:8px; }}
  .info-box li {{ margin:4px 0; font-size:14px; }}
  .date-header {{ font-weight:600; color:#0033A1; margin:16px 0 8px; font-size:15px; border-bottom:1px solid #e2e8f0; padding-bottom:6px; }}
  .slot-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:8px; margin-bottom:12px; }}
  .slot-label {{ display:flex; align-items:center; gap:6px; padding:8px 12px; border:1px solid #e2e8f0; border-radius:6px; cursor:pointer; font-size:13px; transition:all .15s; }}
  .slot-label:hover {{ border-color:#0033A1; background:#f0f4ff; }}
  .slot-label input:checked + span {{ color:#0033A1; font-weight:600; }}
  .slot-disabled {{ opacity:0.4; cursor:not-allowed; background:#f8f8f8; text-decoration:line-through; }}
  .slot-disabled input {{ pointer-events:none; }}
  .slots-container {{ max-height:400px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin:12px 0; }}
  .booking-card {{ background:#f0fdf4; border-color:#059669; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ── JSON API endpoint for auto-process (called from dashboard) ───────────────

@portal_bp.route("/api/v1/members/<member_id>/auto-process", methods=["GET"])
def auto_process_member(member_id):
    """
    Automated agent pipeline:
    1. detect_care_gaps (pure Python)
    2. Run 6-agent analysis (LLM)
    3. Send professional care gap analysis email with portal link
    Returns SSE-style JSON events for frontend progress tracking.
    """
    import json
    import logging
    from flask import Response, stream_with_context

    logger = logging.getLogger(__name__)

    def generate():
        try:
            # Step 1: Detect care gaps
            yield _sse({"step": "detect_gaps", "status": "running", "message": "Detecting care gaps..."})
            from src.care_gap_agents import detect_care_gaps
            gap_result = detect_care_gaps(member_id)
            yield _sse({"step": "detect_gaps", "status": "done",
                        "gaps_created": gap_result.get("gaps_created", []),
                        "compliant": gap_result.get("compliant", [])})

            profile = get_member_profile(member_id)
            if not profile:
                yield _sse({"step": "error", "message": "Member not found"})
                return

            gaps = get_member_open_gaps(member_id)
            name = profile.get("name", member_id)
            email = profile.get("email", "")

            if not gaps:
                yield _sse({"step": "complete", "status": "compliant",
                            "message": f"{name} is fully compliant. No email needed."})
                return

            # Step 2: Run 6-agent analysis
            yield _sse({"step": "agent_analysis", "status": "running",
                        "message": "Running AI agent analysis..."})

            from src.care_gap_agents import CareGapAgentSystem
            agent_system = CareGapAgentSystem()
            agent_responses = {}
            for event_type, data in agent_system.validate_and_suggest_stream(member_id):
                if event_type == "agent_done":
                    agent_responses[data["agent"]] = data["content"]
                    yield _sse({"step": "agent_analysis", "agent": data["agent"],
                                "status": "done"})
                elif event_type == "agent_start":
                    yield _sse({"step": "agent_analysis", "agent": data["agent"],
                                "status": "running"})

            yield _sse({"step": "agent_analysis", "status": "done",
                        "message": "All agents completed."})

            # Step 3: Compose and send email
            if not email:
                yield _sse({"step": "email", "status": "skipped",
                            "message": "No email on file — skipping email."})
            else:
                yield _sse({"step": "email", "status": "running",
                            "message": f"Sending analysis email to {email}..."})

                portal_url = get_portal_url(member_id)

                # Build the recommendation summary from agent output
                rec_text = agent_responses.get("recommendation_agent", "")
                care_gap_text = agent_responses.get("care_gap_agent", "")

                _send_analysis_email(member_id, name, email, gaps, portal_url,
                                     rec_text, care_gap_text)

                yield _sse({"step": "email", "status": "done",
                            "message": f"Email sent to {email}"})

            yield _sse({"step": "complete", "status": "success",
                        "message": f"Auto-process complete for {name}",
                        "gaps_count": len(gaps),
                        "email_sent": bool(email)})

        except Exception as exc:
            logger.exception("auto_process_member error")
            yield _sse({"step": "error", "message": str(exc)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


def _sse(data: dict) -> str:
    import json
    return f"data: {json.dumps(data)}\n\n"


def _send_analysis_email(member_id, name, email, gaps, portal_url,
                         recommendation_text, care_gap_text):
    """Send the care gap analysis email with interactive portal link."""
    try:
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg
        from src.care_gap_neo4j import merge_email

        if not cfg.azure_communication_connection_string:
            return

        gap_rows = ""
        for g in gaps:
            gap_rows += f"""
            <tr>
              <td style="padding:12px 16px;font-weight:600;">{g['measure_name']}</td>
              <td style="padding:12px 16px;"><code>{g['measure_id']}</code></td>
              <td style="padding:12px 16px;"><code>{g.get('primary_cpt_code','N/A')}</code></td>
              <td style="padding:12px 16px;"><code>{g.get('primary_icd10','N/A')}</code></td>
              <td style="padding:12px 16px;">{g.get('lookback_months','12')} mo</td>
            </tr>"""

        # Clean up agent text for email display (strip markdown formatting)
        import re
        clean_rec = re.sub(r'[*#`]', '', recommendation_text[:1500]) if recommendation_text else ""
        clean_gap = re.sub(r'[*#`]', '', care_gap_text[:1000]) if care_gap_text else ""

        html = f"""
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:700px;margin:auto;">
<div style="background:#0033A1;padding:24px 32px;border-radius:8px 8px 0 0;">
  <h1 style="color:white;margin:0;font-size:22px;">HealthCare Management Portal</h1>
  <p style="color:#b3c7f7;margin:4px 0 0;">Preventive Care Gap Analysis Report</p>
</div>
<div style="border:1px solid #dce3f5;border-top:none;padding:32px;border-radius:0 0 8px 8px;">
  <p style="font-size:16px;">Dear <strong>{name}</strong>,</p>
  <p>Our AI-powered care management system has completed a comprehensive analysis of your
  preventive care status based on HEDIS quality measures. Below is a summary of recommended
  screenings and actions.</p>

  <h2 style="color:#0033A1;margin:24px 0 12px;font-size:18px;">Open Care Gaps</h2>
  <table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:14px;">
    <tr style="background:#0033A1;color:white;">
      <th style="padding:10px 16px;text-align:left;">Screening</th>
      <th style="padding:10px 16px;text-align:left;">Measure</th>
      <th style="padding:10px 16px;text-align:left;">CPT</th>
      <th style="padding:10px 16px;text-align:left;">ICD-10</th>
      <th style="padding:10px 16px;text-align:left;">Lookback</th>
    </tr>
    {gap_rows}
  </table>

  {"<h2 style='color:#0033A1;margin:24px 0 12px;font-size:18px;'>AI Analysis Summary</h2><div style='background:#f0f4ff;padding:16px;border-radius:8px;font-size:14px;white-space:pre-wrap;'>" + clean_gap + "</div>" if clean_gap else ""}

  {"<h2 style='color:#0033A1;margin:24px 0 12px;font-size:18px;'>Recommendations</h2><div style='background:#f0fdf4;padding:16px;border-radius:8px;font-size:14px;white-space:pre-wrap;'>" + clean_rec + "</div>" if clean_rec else ""}

  <div style="text-align:center;margin:32px 0;">
    <p style="font-size:16px;margin-bottom:16px;"><strong>Would you like to schedule these screenings?</strong></p>
    <a href="{portal_url}" style="display:inline-block;background:#059669;color:white;padding:16px 40px;border-radius:8px;font-size:16px;font-weight:600;text-decoration:none;">
      Yes — Review &amp; Schedule Appointments
    </a>
    <p style="margin-top:12px;font-size:13px;color:#888;">
      Click the button above to review each screening and choose your preferred appointment times.
    </p>
  </div>

  <hr style="border:none;border-top:1px solid #dce3f5;margin:24px 0;">
  <p style="color:#888;font-size:12px;">
    This is an automated analysis from the HealthCare Management Portal AI Care Gap System.
    If you have questions, please contact your care management team.
  </p>
</div>
</body></html>"""

        client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
        message = {
            "senderAddress": cfg.azure_communication_sender,
            "recipients": {"to": [{"address": email}]},
            "content": {
                "subject": f"Care Gap Analysis Report — {len(gaps)} Recommended Screening(s)",
                "html": html,
            },
        }
        poller = client.begin_send(message)
        poller.result()

        # Persist email in Neo4j
        email_id = f"AUTO-ANALYSIS-{member_id}-{uuid.uuid4().hex[:8]}"
        merge_email(
            email_id=email_id,
            member_id=member_id,
            subject=f"Care Gap Analysis Report — {len(gaps)} Recommended Screening(s)",
            body=f"AI analysis report with {len(gaps)} open gaps. Portal link included.",
            from_email=cfg.azure_communication_sender,
            to_email=email,
            timestamp=datetime.now().isoformat(),
            direction="sent",
            is_read=True,
        )

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Analysis email failed: {e}")
