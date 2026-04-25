"""
Mobile APK backend — Flask Blueprint.

Surface for a per-member mobile app (React Native / Expo). Every route is
scoped to a single member_id derived from a JWT, never from the request
body, so a member can only ever read/write their own record.

Routes:
  POST /api/v1/mobile/activate             member_id + OTP -> JWT
  GET  /api/v1/mobile/member/me            current member payload
  POST /api/v1/mobile/chat                  conversational agent (member-scoped)
  POST /api/v1/mobile/appointments          book/cancel
  POST /api/v1/mobile/push/register         FCM device token
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_member_profile,
    get_member_extended_profile,
    merge_appointment,
    get_appointment,
    merge_outreach,
)
from src.neo4j_connection import get_knowledge_graph


mobile_bp = Blueprint("mobile_api", __name__)
_logger = logging.getLogger(__name__)

_MOBILE_SECRET = "hedis-mobile-apk-2026"  # demo secret; move to env in prod
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30    # 30 days

# In-memory OTP + push-token stores (replace with Neo4j / Redis in prod)
_otp_store: dict[str, tuple[str, float]] = {}  # member_id -> (otp, expires_ts)
_push_tokens: dict[str, str] = {}              # member_id -> fcm_token
_chat_history: dict[str, list] = {}            # member_id -> Bedrock Converse messages (last ~20 turns)
_CHAT_HISTORY_CAP = 40                         # keep last 40 messages (≈ 20 turns)


# ── JWT-ish signed token (HS256-style HMAC, no external dep) ────────────────

def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    import base64
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(member_id: str, exp_ts: int) -> str:
    payload = json.dumps({"sub": member_id, "exp": exp_ts}, separators=(",", ":"))
    body = _b64url(payload.encode())
    sig = hmac.new(_MOBILE_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}"


def _verify(token: str) -> str | None:
    """Return member_id if token valid, else None."""
    try:
        body_b64, sig_b64 = token.split(".", 1)
        expected = hmac.new(_MOBILE_SECRET.encode(), body_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), sig_b64):
            return None
        payload = json.loads(_b64url_decode(body_b64))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload.get("sub")
    except Exception:
        return None


def _current_member_id() -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return _verify(auth[7:])


def _require_auth():
    """Return (member_id, None) on success, or (None, error_response)."""
    mid = _current_member_id()
    if not mid:
        return None, (jsonify({"error": "unauthorized"}), 401)
    return mid, None


# ── Activation (OTP flow) ────────────────────────────────────────────────────

@mobile_bp.route("/api/v1/mobile/activate/request", methods=["POST"])
def activate_request():
    """Member enters member_id -> backend generates OTP, sends via email.

    Body: { "member_id": "M0001" }
    """
    data = request.json or {}
    member_id = (data.get("member_id") or "").strip().upper()
    if not member_id:
        return jsonify({"error": "member_id required"}), 400

    profile = get_member_profile(member_id)
    if not profile:
        return jsonify({"error": "member not found"}), 404

    # 6-digit OTP, 10-minute expiry
    otp = f"{uuid.uuid4().int % 1_000_000:06d}"
    _otp_store[member_id] = (otp, time.time() + 600)

    # Email the OTP (reuse Azure Communication Services — same channel as outreach)
    try:
        _send_otp_email(profile, otp)
    except Exception as exc:
        _logger.warning(f"[MOBILE] OTP email failed for {member_id}: {exc}")
        # Still return success so the member can retry; surface OTP in logs for dev
        _logger.info(f"[MOBILE] OTP for {member_id} (dev fallback): {otp}")

    return jsonify({"status": "otp_sent", "email_hint": _mask_email(profile.get("email", ""))})


@mobile_bp.route("/api/v1/mobile/activate/verify", methods=["POST"])
def activate_verify():
    """Verify OTP and issue a long-lived JWT.

    Body: { "member_id": "M0001", "otp": "123456" }
    """
    data = request.json or {}
    member_id = (data.get("member_id") or "").strip().upper()
    otp = (data.get("otp") or "").strip()

    stored = _otp_store.get(member_id)
    if not stored:
        return jsonify({"error": "no otp requested"}), 400
    expected_otp, exp_ts = stored
    if time.time() > exp_ts:
        _otp_store.pop(member_id, None)
        return jsonify({"error": "otp expired"}), 400
    if not hmac.compare_digest(expected_otp, otp):
        return jsonify({"error": "otp mismatch"}), 401

    _otp_store.pop(member_id, None)
    token = _sign(member_id, int(time.time()) + _TOKEN_TTL_SECONDS)
    return jsonify({"token": token, "member_id": member_id, "expires_in": _TOKEN_TTL_SECONDS})


def _mask_email(email: str) -> str:
    if "@" not in email:
        return ""
    local, dom = email.split("@", 1)
    return f"{local[:2]}***@{dom}"


def _send_otp_email(profile: dict, otp: str):
    """Send OTP via Azure Communication Services."""
    from azure.communication.email import EmailClient
    from config.settings import settings

    if not settings.azure_communication_connection_string:
        raise RuntimeError("Azure email not configured")

    client = EmailClient.from_connection_string(settings.azure_communication_connection_string)
    message = {
        "senderAddress": settings.azure_communication_sender,
        "recipients": {"to": [{"address": profile["email"], "displayName": profile.get("name", "")}]},
        "content": {
            "subject": "Your Cognizant Care mobile activation code",
            "plainText": f"Your one-time activation code is: {otp}\n\nThis code expires in 10 minutes.",
            "html": f"""
                <p>Hi {profile.get('name', '')},</p>
                <p>Your one-time activation code for the Cognizant Care mobile app is:</p>
                <h2 style="letter-spacing:4px;">{otp}</h2>
                <p>This code expires in 10 minutes.</p>
            """,
        },
    }
    poller = client.begin_send(message)
    poller.result()


# ── Member-scoped data ───────────────────────────────────────────────────────

def _reconcile_completed_gaps(member_id: str) -> int:
    """Close any open CareGap that already has a 'Completed' Appointment for the same measure.

    Returns the number of gaps reconciled. Idempotent — safe to call on every read.
    """
    kg = get_knowledge_graph()
    rows = kg.run_query(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        WHERE coalesce(g.is_open, true) = true
        WITH g, q, m
        MATCH (a:Appointment {member_id: $mid, status: 'Completed'})
        WHERE a.measure_id = q.measure_id
        WITH g, q, a ORDER BY a.appointment_date DESC LIMIT 1
        SET g.is_open = false,
            g.closed_on = a.appointment_date,
            g.gap_status = 'Closed'
        RETURN g.care_gap_id AS gap_id, q.measure_id AS measure_id, a.appointment_id AS appointment_id
        """,
        {"mid": member_id},
    ) or []
    if rows:
        _logger.info(f"[MOBILE/reconcile] {member_id}: closed {len(rows)} gap(s) due to completed appts: {rows}")
        # Also push the closure to the reference DB so portal timeline reflects it
        try:
            from src.persona_sync import sync_gap_closed
            for r in rows:
                if r.get("gap_id"):
                    sync_gap_closed(member_id=member_id, care_gap_id=r["gap_id"])
        except Exception as exc:
            _logger.warning(f"[MOBILE/reconcile] persona sync failed: {exc}")
        # Emit a socket event so portal refreshes live
        try:
            from src.care_gap_api import emit_portal_event
            emit_portal_event("care_gap_updated", {
                "member_id": member_id,
                "closed": [r.get("gap_id") for r in rows if r.get("gap_id")],
                "source": "auto_reconcile",
            })
        except Exception:
            pass
    return len(rows)


@mobile_bp.route("/api/v1/mobile/member/me", methods=["GET"])
def mobile_member_me():
    member_id, err = _require_auth()
    if err:
        return err

    # Auto-close any gap whose corresponding screening was already completed.
    _reconcile_completed_gaps(member_id)

    profile = get_member_profile(member_id) or {}
    ext = get_member_extended_profile(member_id) or {}
    gaps = get_member_open_gaps(member_id) or []
    return jsonify({
        "member_id": member_id,
        "profile": profile,
        "extended": ext,
        "open_gaps": gaps,
    })


@mobile_bp.route("/api/v1/mobile/appointments", methods=["GET"])
def mobile_list_appointments():
    member_id, err = _require_auth()
    if err:
        return err
    kg = get_knowledge_graph()
    rows = kg.run_query(
        """
        MATCH (a:Appointment {member_id: $mid})
        RETURN a.appointment_id    AS appointment_id,
               a.member_id         AS member_id,
               a.measure_id        AS measure_id,
               a.screening_name    AS screening_name,
               a.appointment_date  AS appointment_date,
               a.appointment_time  AS appointment_time,
               a.lab_number        AS lab_number,
               a.lab_specialist    AS lab_specialist,
               a.lab_location      AS lab_location,
               a.status            AS status,
               a.care_gap_id       AS care_gap_id,
               a.cpt_codes         AS cpt_codes,
               a.icd_codes         AS icd_codes
        ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """,
        {"mid": member_id},
    )
    return jsonify({"appointments": rows or []})


@mobile_bp.route("/api/v1/mobile/appointments/<appointment_id>/cancel", methods=["POST"])
def mobile_cancel_appointment(appointment_id):
    """Member-initiated cancel. Flips status, syncs reference DB timeline, emits socket event."""
    member_id, err = _require_auth()
    if err:
        return err
    kg = get_knowledge_graph()
    rows = kg.run_query(
        """
        MATCH (a:Appointment {appointment_id: $aid, member_id: $mid})
        SET a.status = 'Cancelled', a.cancelled_at = $now, a.cancelled_by = 'member'
        RETURN a.appointment_id AS appointment_id, a.measure_id AS measure_id,
               a.appointment_date AS appointment_date, a.appointment_time AS appointment_time,
               a.care_gap_id AS care_gap_id
        """,
        {"aid": appointment_id, "mid": member_id, "now": datetime.now().isoformat()},
    )
    if not rows:
        return jsonify({"error": "appointment not found"}), 404
    appt = rows[0]

    # Sync the cancellation to the reference DB so the portal timeline shows it
    if appt.get("care_gap_id"):
        try:
            from src.persona_sync import sync_appointment_cancelled
            sync_appointment_cancelled(
                member_id=member_id,
                care_gap_id=appt["care_gap_id"],
                appointment_id=appointment_id,
                appointment_date=appt.get("appointment_date", ""),
                cancelled_by="member",
            )
        except Exception as exc:
            _logger.warning(f"[MOBILE] cancel sync failed: {exc}")

    try:
        from src.care_gap_api import emit_portal_event
        emit_portal_event("appointment_booked", {
            "member_id": member_id,
            "appointment_id": appointment_id,
            "measure_id": appt.get("measure_id"),
            "status": "Cancelled",
            "source": "mobile_cancel",
        })
    except Exception:
        pass
    return jsonify({"status": "cancelled", "appointment_id": appointment_id})


@mobile_bp.route("/api/v1/mobile/appointments", methods=["POST"])
def mobile_book_appointment():
    """Book an appointment from the mobile app.

    Body: {
      "measure_id": "BCS",
      "appointment_date": "2026-05-12",
      "appointment_time": "10:00",
      "care_gap_id": "GAP-...",      # optional
      "lab_name": "Apollo Radiology", # optional (from Google Places)
      "lab_address": "...",           # optional
      "lab_place_id": "ChIJ..."       # optional
    }
    """
    member_id, err = _require_auth()
    if err:
        return err
    data = request.json or {}
    result = _perform_booking(member_id, data, source="manual")
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


def _send_mobile_booking_email(member_id: str, name: str, email: str, appt: dict) -> bool:
    """Send the booking confirmation email directly via Azure Communication Services.

    Returns True on success, False on failure (logs the reason). No silent swallows.
    """
    try:
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg
    except Exception as exc:
        _logger.error(f"[MOBILE/email] ACS SDK import failed: {exc}")
        return False

    if not getattr(cfg, "azure_communication_connection_string", ""):
        _logger.error("[MOBILE/email] AZURE_COMMUNICATION_CONNECTION_STRING is not configured")
        return False
    sender = getattr(cfg, "azure_communication_sender", "")
    if not sender:
        _logger.error("[MOBILE/email] AZURE_COMMUNICATION_SENDER is not configured")
        return False
    if not email or "@" not in email:
        _logger.warning(f"[MOBILE/email] invalid recipient '{email}'")
        return False

    measure_name = appt.get("measure_name") or appt.get("measure_id") or "screening"
    date_str = appt.get("date") or ""
    time_str = appt.get("time") or ""
    location = appt.get("lab_location") or ""
    specialist = appt.get("lab_specialist") or ""
    appt_id = appt.get("appointment_id") or ""

    html = f"""
<html><body style="font-family:Arial,sans-serif;color:#000048;max-width:640px;margin:auto;">
<div style="background:#000048;padding:20px 28px;">
  <h1 style="color:#FFFFFF;margin:0;font-size:20px;">Cognizant Care</h1>
  <p style="color:#92BBE6;margin:4px 0 0;font-size:12px;">Appointment confirmation</p>
</div>
<div style="border:1px solid #E8E8E6;border-top:none;padding:28px;">
  <p style="font-size:15px;">Dear <strong>{name}</strong>,</p>
  <p style="font-size:15px;">Your <strong>{measure_name}</strong> appointment is confirmed.</p>
  <table style="width:100%;border-collapse:collapse;margin:18px 0;">
    <tr><td style="padding:8px 12px;background:#F7F7F5;width:35%;"><strong>Date</strong></td><td style="padding:8px 12px;">{date_str}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Time</strong></td><td style="padding:8px 12px;">{time_str}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Location</strong></td><td style="padding:8px 12px;">{location}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Specialist</strong></td><td style="padding:8px 12px;">{specialist}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Reference</strong></td><td style="padding:8px 12px;font-family:monospace;">{appt_id}</td></tr>
  </table>
  <div style="background:#FFF8E1;border-left:4px solid #E9C71D;padding:14px;margin-top:18px;">
    <strong>Before you arrive:</strong>
    <ul style="margin:6px 0;padding-left:18px;">
      <li>Arrive 15 minutes early.</li>
      <li>Bring photo ID and insurance card.</li>
      <li>Wear comfortable clothing.</li>
    </ul>
  </div>
  <p style="color:#53565A;font-size:11px;margin-top:18px;">
    To reschedule or cancel, open the Cognizant Care mobile app or contact your care manager.
  </p>
</div></body></html>"""

    try:
        client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": email, "displayName": name}]},
            "content": {
                "subject": f"Cognizant Care — {measure_name} appointment confirmed",
                "plainText": (
                    f"Dear {name},\n\nYour {measure_name} appointment is confirmed.\n"
                    f"Date: {date_str}\nTime: {time_str}\nLocation: {location}\n"
                    f"Specialist: {specialist}\nReference: {appt_id}\n"
                ),
                "html": html,
            },
        }
        poller = client.begin_send(message)
        poller.result()
        return True
    except Exception as exc:
        _logger.error(f"[MOBILE/email] send failed for {email}: {exc}", exc_info=True)
        return False


def _perform_booking(member_id: str, data: dict, source: str = "manual") -> dict:
    """Shared booking path used by manual POST and agent chat tool."""
    measure_id = data.get("measure_id")
    appt_date = data.get("appointment_date") or data.get("date")
    appt_time = data.get("appointment_time") or data.get("time")
    if not (measure_id and appt_date and appt_time):
        return {"error": "measure_id, appointment_date, appointment_time required"}

    profile = get_member_profile(member_id) or {}

    # Lab details — either member-selected via Google Places or fallback per measure
    lab_name = (data.get("lab_name") or "").strip()
    lab_addr = (data.get("lab_address") or "").strip()
    lab_place_id = (data.get("lab_place_id") or "").strip()
    if lab_name:
        lab_number = lab_place_id or "GPLACE"
        lab_specialist = lab_name
        lab_location = lab_addr or lab_name
    else:
        fallback = _FALLBACK_LAB.get(measure_id, _DEFAULT_LAB)
        lab_number = fallback["lab_number"]
        lab_specialist = fallback["lab_specialist"]
        lab_location = fallback["lab_location"]

    try:
        from src.care_gap_api import _get_hedis_codes
        cpt_codes, icd_codes = _get_hedis_codes(measure_id)
    except Exception:
        cpt_codes, icd_codes = "", ""

    measure_name = data.get("measure_name") or measure_id
    appointment_id = f"APT-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
    care_gap_id = data.get("care_gap_id", "")

    merge_appointment(
        appointment_id=appointment_id,
        member_id=member_id,
        measure_id=measure_id,
        appointment_date=appt_date,
        appointment_time=appt_time,
        lab_number=lab_number,
        lab_specialist=lab_specialist,
        lab_location=lab_location,
        screening_name=measure_name,
        cpt_codes=cpt_codes,
        icd_codes=icd_codes,
        provider_id=profile.get("pcp_id", ""),
        status="Scheduled",
        care_gap_id=care_gap_id,
    )

    # Outreach record so portal shows the booking originated from mobile
    outreach_id = f"OUT-MOBILE-{member_id}-{measure_id}-{uuid.uuid4().hex[:6].upper()}"
    try:
        merge_outreach(
            outreach_id=outreach_id,
            care_gap_id=care_gap_id,
            member_id=member_id,
            care_manager_id=f"MOBILE-{source.upper()}",
            channel="Mobile App (Agent)" if source == "agent" else "Mobile App",
            date=datetime.now().strftime("%Y-%m-%d"),
            status="Scheduled",
        )
    except Exception as exc:
        _logger.warning(f"[MOBILE] outreach record failed: {exc}")

    # Sync the booking to the reference DB so the portal graph visualization picks it up
    if care_gap_id:
        try:
            from src.persona_sync import sync_appointment_booked
            sync_appointment_booked(
                member_id=member_id,
                care_gap_id=care_gap_id,
                appointment_id=appointment_id,
                appointment_date=appt_date,
                lab_location=lab_location,
            )
        except Exception as exc:
            _logger.warning(f"[MOBILE] persona sync failed: {exc}")

    # Friendly display strings for email + response
    try:
        friendly_date = datetime.strptime(appt_date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    except Exception:
        friendly_date = appt_date
    try:
        hh, mm = appt_time.split(":")
        h = int(hh)
        friendly_time = f"{h % 12 or 12}:{mm} {'AM' if h < 12 else 'PM'}"
    except Exception:
        friendly_time = appt_time

    # Confirmation email — fetch the LATEST email from the DB after recent updates
    fresh_profile = get_member_profile(member_id) or {}
    member_email = fresh_profile.get("email") or profile.get("email") or ""
    member_name  = fresh_profile.get("name") or profile.get("name") or member_id
    email_status = "skipped:no_email"
    if member_email:
        appt_summary = {
            "appointment_id": appointment_id,
            "measure_name": measure_name,
            "date": friendly_date,
            "time": friendly_time,
            "lab_location": lab_location,
            "lab_specialist": lab_specialist,
        }
        if _send_mobile_booking_email(member_id, member_name, member_email, appt_summary):
            email_status = f"sent:{member_email}"
            _logger.info(f"[MOBILE/booking] confirmation email sent to {member_email} for {appointment_id}")
        else:
            email_status = "failed"
    else:
        _logger.warning(f"[MOBILE/booking] no email on profile for {member_id}; skipping confirmation")

    payload = {
        "appointment_id": appointment_id,
        "member_id": member_id,
        "measure_id": measure_id,
        "measure_name": measure_name,
        "appointment_date": appt_date,
        "appointment_time": appt_time,
        "friendly_date": friendly_date,
        "friendly_time": friendly_time,
        "lab_location": lab_location,
        "lab_specialist": lab_specialist,
        "status": "Scheduled",
        "source": source,
        "email_status": email_status,
        "email_sent_to": member_email if email_status.startswith("sent") else "",
    }

    # Real-time push to portal
    try:
        from src.care_gap_api import emit_portal_event
        emit_portal_event("appointment_booked", payload)
    except Exception as exc:
        _logger.warning(f"[MOBILE] socket emit failed: {exc}")

    return {"status": "booked", "appointment": payload}


# ── Lab/slot/geocode helpers for the agent-driven booking flow ──────────────

_FALLBACK_LAB = {
    "BCS": {"lab_number": "LAB-02", "lab_specialist": "Dr. Sarah Mitchell",
            "lab_location": "Radiology & Mammography Unit, 2nd Floor"},
    "CCS": {"lab_number": "LAB-01", "lab_specialist": "Dr. James Rodriguez",
            "lab_location": "Cytology & Gynecology Lab, 1st Floor"},
    "COL": {"lab_number": "LAB-03", "lab_specialist": "Dr. Emily Chen",
            "lab_location": "Gastroenterology & Endoscopy Suite, 3rd Floor"},
    "CBP": {"lab_number": "LAB-04", "lab_specialist": "Dr. Michael Thompson",
            "lab_location": "Cardiology Clinic, 4th Floor"},
    "CDC": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
            "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
    "GSD": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
            "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
    "KED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
            "lab_location": "Renal & Nephrology Lab, 2nd Floor"},
    "BPD": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
            "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
    "EED": {"lab_number": "LAB-05", "lab_specialist": "Dr. Lisa Patel",
            "lab_location": "Diabetes & Endocrinology Center, 2nd Floor"},
}
_DEFAULT_LAB = {"lab_number": "LAB-01", "lab_specialist": "On-Call Specialist",
                "lab_location": "General Screening Lab, 1st Floor"}


@mobile_bp.route("/api/v1/mobile/slots", methods=["GET"])
def mobile_slots():
    """Return upcoming available time slots (next 7 business days, 30-min intervals)."""
    _, err = _require_auth()
    if err:
        return err
    from src.member_portal import _generate_slots, _get_booked_slots
    all_slots = _generate_slots(7)
    booked = _get_booked_slots()
    available = [s for s in all_slots if (s["date"], s["time"]) not in booked]
    return jsonify({"slots": available})


@mobile_bp.route("/api/v1/mobile/labs/nearby", methods=["GET"])
def mobile_nearby_labs():
    """Google Places proxy scoped to this member. Query: lat, lng, measure_id."""
    _, err = _require_auth()
    if err:
        return err
    import requests as http_requests
    from config.settings import settings as cfg

    if not cfg.google_maps_api_key:
        return jsonify({"error": "Google Maps not configured"}), 500
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    measure_id = request.args.get("measure_id", "")
    if not (lat and lng):
        return jsonify({"error": "lat and lng required"}), 400

    keywords = {
        "BCS": "mammography radiology breast screening",
        "CCS": "gynecology cervical screening pap smear",
        "COL": "gastroenterology colonoscopy endoscopy",
        "CBP": "cardiology blood pressure clinic",
        "CDC": "diabetes endocrinology HbA1c lab",
        "GSD": "diabetes endocrinology HbA1c lab",
        "EED": "ophthalmology diabetic eye exam retinal screening",
        "KED": "nephrology kidney screening renal lab",
        "BPD": "diabetes endocrinology blood glucose lab",
    }
    keyword = keywords.get(measure_id, "medical lab diagnostic center")
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": request.args.get("radius", "5000"),
        "keyword": keyword,
        "type": "health",
        "key": cfg.google_maps_api_key,
    }
    try:
        resp = http_requests.get(url, params=params, timeout=10).json()
    except Exception as exc:
        return jsonify({"error": f"Places API error: {exc}"}), 502

    results = []
    for p in resp.get("results", [])[:10]:
        loc = p.get("geometry", {}).get("location", {})
        results.append({
            "place_id": p.get("place_id", ""),
            "name": p.get("name", ""),
            "address": p.get("vicinity", ""),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "rating": p.get("rating"),
            "open_now": p.get("opening_hours", {}).get("open_now"),
        })
    return jsonify({"results": results})


@mobile_bp.route("/api/v1/mobile/member/me", methods=["PATCH"])
def mobile_update_profile():
    """Member-initiated profile update. Limited to safe fields only."""
    member_id, err = _require_auth()
    if err:
        return err
    data = request.json or {}
    allowed = {"phone", "email", "address", "notification_pref"}
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({"error": "no editable fields provided"}), 400

    kg = get_knowledge_graph()
    sets = ", ".join(f"m.{k} = ${k}" for k in updates)
    params = {**updates, "mid": member_id}
    ok = kg.execute_write(f"MATCH (m:Member {{member_id: $mid}}) SET {sets}", params)
    if not ok:
        _logger.error(f"[MOBILE/profile] write failed for {member_id} with fields {list(updates)}")
        return jsonify({"error": "write failed"}), 500
    _logger.info(f"[MOBILE/profile] {member_id} updated fields: {list(updates)}")

    profile = get_member_profile(member_id) or {}
    try:
        from src.care_gap_api import emit_portal_event
        emit_portal_event("profile_updated", {"member_id": member_id, "changes": list(updates.keys()), "profile": profile})
    except Exception as exc:
        _logger.warning(f"[MOBILE] profile emit failed: {exc}")
    return jsonify({"status": "updated", "profile": profile})


# ── Conversational agent ─────────────────────────────────────────────────────

@mobile_bp.route("/api/v1/mobile/chat/reset", methods=["POST"])
def mobile_chat_reset():
    """Clear chat memory for this member (sign-out, 'new topic' button, etc.)."""
    member_id, err = _require_auth()
    if err:
        return err
    _chat_history.pop(member_id, None)
    return jsonify({"status": "reset"})


@mobile_bp.route("/api/v1/mobile/chat/proactive", methods=["GET"])
def mobile_chat_proactive():
    """Return pending proactive bot messages (reminders) for this member."""
    member_id, err = _require_auth()
    if err:
        return err
    try:
        from src.mobile_reminders import drain_proactive_messages
        msgs = drain_proactive_messages(member_id)
    except Exception:
        msgs = []
    return jsonify({"messages": msgs})


@mobile_bp.route("/api/v1/mobile/chat", methods=["POST"])
def mobile_chat():
    """Ask the member-scoped care agent a question.

    Body: { "message": "What is my blood pressure screening status?" }
    Returns: { "reply": "..." }
    """
    member_id, err = _require_auth()
    if err:
        return err

    data = request.json or {}
    user_msg = (data.get("message") or "").strip()
    user_location = data.get("user_location") or None  # optional: {"lat": ..., "lng": ...}
    if not user_msg:
        return jsonify({"error": "message required"}), 400

    try:
        result = _run_member_chat(member_id, user_msg, user_location=user_location)
        return jsonify(result)
    except Exception as exc:
        _logger.error(f"[MOBILE] chat error for {member_id}: {exc}", exc_info=True)
        return jsonify({"reply": "Sorry, I couldn't process that right now. Please try again.", "attachment": None})


_TOOL_SPEC = [
    {
        "toolSpec": {
            "name": "show_my_profile",
            "description": "Display the patient's profile summary (name, age, plan, doctor, contact info) as a structured card grid in the app. Call this when the user wants to see or verify profile details.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "show_my_appointments",
            "description": "Display the patient's upcoming and recent appointments as a structured list card in the app.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "list_my_open_care_gaps",
            "description": "List this member's open (non-compliant) care gaps with measure_id and friendly name. The app will render them as tappable cards.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "find_nearby_labs",
            "description": "Find nearby diagnostic labs/clinics for a specific screening using the member's current GPS location.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "measure_id": {"type": "string", "description": "HEDIS measure ID (e.g. BCS, CCS, COL, CBP, CDC)."},
                },
                "required": ["measure_id"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "list_available_slots",
            "description": "Return available 30-minute appointment slots for the next 7 business days.",
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    },
    {
        "toolSpec": {
            "name": "book_appointment",
            "description": "Book an appointment for the member. Only call after the member has explicitly confirmed the measure, date, time, and lab.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "measure_id": {"type": "string"},
                    "measure_name": {"type": "string"},
                    "care_gap_id": {"type": "string"},
                    "appointment_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "appointment_time": {"type": "string", "description": "HH:MM in 24-hour"},
                    "lab_name": {"type": "string"},
                    "lab_address": {"type": "string"},
                    "lab_place_id": {"type": "string"},
                },
                "required": ["measure_id", "appointment_date", "appointment_time"],
            }},
        }
    },
    {
        "toolSpec": {
            "name": "update_my_profile",
            "description": "Update member's editable profile fields (phone, email, address). Confirm with member before calling.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "address": {"type": "string"},
                },
            }},
        }
    },
]


def _dispatch_tool(member_id: str, tool_name: str, tool_input: dict, user_location: dict | None) -> dict:
    """Execute a single agent tool call and return a JSON-serialisable result."""
    if tool_name == "show_my_profile":
        p = get_member_profile(member_id) or {}
        ext = get_member_extended_profile(member_id) or {}
        return {
            "profile": {
                "member_id": member_id,
                "name": p.get("name"),
                "age": p.get("age"),
                "gender": p.get("gender"),
                "dob": p.get("dob"),
                "phone": p.get("phone"),
                "email": p.get("email"),
                "address": p.get("address"),
                "plan": p.get("plan_name") or p.get("plan"),
                "primary_care_physician": p.get("pcp_name") or p.get("pcp_id"),
            },
            "lifestyle": ext.get("lifestyle", {}),
        }

    if tool_name == "show_my_appointments":
        kg = get_knowledge_graph()
        rows = kg.run_query(
            """
            MATCH (a:Appointment {member_id: $mid})
            RETURN a.appointment_id AS appointment_id, a.measure_id AS measure_id,
                   a.screening_name AS screening_name,
                   a.appointment_date AS appointment_date, a.appointment_time AS appointment_time,
                   a.lab_location AS lab_location, a.lab_specialist AS lab_specialist,
                   a.status AS status
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
            LIMIT 15
            """,
            {"mid": member_id},
        ) or []
        return {"appointments": rows}

    if tool_name == "list_my_open_care_gaps":
        try:
            _reconcile_completed_gaps(member_id)
        except Exception:
            pass
        return {"open_gaps": get_member_open_gaps(member_id) or []}

    if tool_name == "find_nearby_labs":
        if not user_location or not user_location.get("lat"):
            return {"error": "location_unavailable",
                    "message": "I need your current location to find nearby labs. Please enable location in the app."}
        import requests as http_requests
        from config.settings import settings as cfg
        measure_id = tool_input.get("measure_id", "")
        keywords = {
            "BCS": "mammography radiology breast screening",
            "CCS": "gynecology cervical screening pap smear",
            "COL": "gastroenterology colonoscopy endoscopy",
            "CBP": "cardiology blood pressure clinic",
            "CDC": "diabetes endocrinology HbA1c lab",
            "GSD": "diabetes endocrinology HbA1c lab",
            "EED": "ophthalmology diabetic eye exam retinal screening",
            "KED": "nephrology kidney screening renal lab",
        }
        try:
            resp = http_requests.get(
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                params={
                    "location": f"{user_location['lat']},{user_location['lng']}",
                    "radius": 5000,
                    "keyword": keywords.get(measure_id, "medical lab diagnostic center"),
                    "type": "health",
                    "key": cfg.google_maps_api_key,
                },
                timeout=10,
            ).json()
        except Exception as exc:
            return {"error": str(exc)}
        labs = []
        for p in resp.get("results", [])[:6]:
            loc = p.get("geometry", {}).get("location", {})
            labs.append({
                "place_id": p.get("place_id", ""),
                "name": p.get("name", ""),
                "address": p.get("vicinity", ""),
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "rating": p.get("rating"),
            })
        return {"labs": labs}

    if tool_name == "list_available_slots":
        from src.member_portal import _generate_slots, _get_booked_slots
        booked = _get_booked_slots()
        slots = [s for s in _generate_slots(7) if (s["date"], s["time"]) not in booked]
        return {"slots": slots[:40]}

    if tool_name == "book_appointment":
        return _perform_booking(member_id, tool_input, source="agent")

    if tool_name == "update_my_profile":
        allowed = {"phone", "email", "address"}
        updates = {k: v for k, v in tool_input.items() if k in allowed and v}
        if not updates:
            return {"error": "no fields provided"}
        kg = get_knowledge_graph()
        sets = ", ".join(f"m.{k} = ${k}" for k in updates)
        params = {**updates, "mid": member_id}
        kg.run_query(f"MATCH (m:Member {{member_id: $mid}}) SET {sets}", params)
        try:
            from src.care_gap_api import emit_portal_event
            emit_portal_event("profile_updated", {"member_id": member_id, "changes": list(updates.keys())})
        except Exception:
            pass
        return {"status": "updated", "updated_fields": list(updates.keys())}

    return {"error": f"unknown tool {tool_name}"}


def _run_member_chat(member_id: str, user_msg: str, user_location: dict | None = None) -> dict:
    """Tool-using member-scoped agent. Returns {reply, attachment} so the mobile UI can render interactive cards."""
    import boto3
    from config.settings import settings

    # Reconcile before reading so the agent never sees a stale "open" gap whose
    # appointment was already completed.
    try:
        _reconcile_completed_gaps(member_id)
    except Exception as exc:
        _logger.warning(f"[MOBILE/chat] reconcile failed: {exc}")

    profile = get_member_profile(member_id) or {}
    ext = get_member_extended_profile(member_id) or {}
    gaps = get_member_open_gaps(member_id) or []

    # Recent appointments
    kg = get_knowledge_graph()
    appts = kg.run_query(
        """
        MATCH (a:Appointment {member_id: $mid})
        RETURN a.appointment_id AS id, a.measure_id AS measure, a.screening_name AS name,
               a.appointment_date AS date, a.appointment_time AS time,
               a.lab_location AS location, a.lab_specialist AS specialist, a.status AS status
        ORDER BY a.appointment_date DESC LIMIT 10
        """,
        {"mid": member_id},
    ) or []

    context = {
        "member_id": member_id,
        "profile": {
            "name": profile.get("name"),
            "age": profile.get("age"),
            "gender": profile.get("gender"),
            "dob": profile.get("dob"),
            "phone": profile.get("phone"),
            "email": profile.get("email"),
            "address": profile.get("address"),
            "plan": profile.get("plan_name") or profile.get("plan"),
            "primary_care_physician": profile.get("pcp_name") or profile.get("pcp_id"),
        },
        "health_summary": {
            "lifestyle": ext.get("lifestyle", {}),
            "medical_history": ext.get("medical_history", []),
            "family_history": ext.get("family_history", []),
            "risk_factors": ext.get("risk_factors", []),
        },
        "open_care_gaps": [
            {
                "care_gap_id": g.get("care_gap_id"),
                "measure_id": g.get("measure_id"),
                "measure_name": g.get("measure_name"),
                "description": g.get("measure_description") or g.get("description"),
                "priority": g.get("priority"),
                "due": g.get("due_date"),
            }
            for g in gaps
        ],
        "appointments": appts,
    }

    system_prompt = (
        "You are the Cognizant Care mobile health assistant for ONE specific patient. "
        "CRITICAL: Never output XML-style tags like <thinking>, <reasoning>, <scratchpad>, <plan>, or any "
        "internal chain-of-thought. Respond with ONLY the final answer as plain text or bullets.\n\n"
        f"PATIENT CONTEXT (authoritative):\n{json.dumps(context, default=str)[:7000]}\n\n"
        "WHEN TO CALL WHICH TOOL:\n"
        "- User asks about THEIR profile / name / age / plan / doctor / phone / email / address → call show_my_profile (renders card grid).\n"
        "- User asks about THEIR care gaps / screenings they need / what's overdue → call list_my_open_care_gaps (renders gap cards).\n"
        "- User asks about THEIR upcoming or past appointments → call show_my_appointments (renders list).\n"
        "- User wants to BOOK a screening → use the booking flow below.\n"
        "- User wants to UPDATE contact info → confirm new value, then call update_my_profile.\n"
        "Never reveal data from other patients. Always call these tools when relevant so the app renders rich cards instead of plain text.\n\n"
        "BOOKING FLOW (strict):\n"
        "(1) Ask which care gap they want (or call list_my_open_care_gaps first).\n"
        "(2) Call find_nearby_labs to show nearby options. If it returns 'location_unavailable', ask them to enable "
        "location (the app renders an Enable-location button).\n"
        "(3) Ask which lab they prefer from the on-screen map/list.\n"
        "(4) Call list_available_slots and let them pick from the on-screen picker.\n"
        "(5) Recap: measure + date + time + lab; ask 'Shall I confirm this booking? (yes/no)'.\n"
        "(6) Only call book_appointment after explicit 'yes'.\n"
        "After booking succeeds, tell them a confirmation email was sent and the care team has been notified.\n\n"
        "CRITICAL BOOKING RULES:\n"
        "- ALL labs returned by find_nearby_labs are VALID, approved providers. NEVER refuse to book at a lab "
        "the user selected from the find_nearby_labs results — those are pre-vetted nearby options from our system. "
        "- NEVER say 'I can't book outside our system' or 'contact the clinic directly' — our system supports booking "
        "at any lab the user selected. Call book_appointment with the selected lab's details.\n"
        "- If the user refers to a previous message (e.g. 'the first one', 'that lab', 'the 9 AM slot'), use the "
        "most recent lab or slot you presented, not a generic fallback.\n"
        "- DO NOT list available time slots in your text reply after calling list_available_slots. The mobile app "
        "renders an interactive on-screen picker. Just say a brief one-liner like 'Pick a date and time below.' \n"
        "- DO NOT list lab options in your text reply after calling find_nearby_labs. The mobile app renders an "
        "interactive map + lab cards. Just say a brief one-liner like 'I found nearby labs — tap one to select.'\n\n"
        "Keep replies concise, warm, mobile-friendly (<150 words). Use bullet points for lists. "
        "Always pair a tool call with a short natural-language sentence — never leave the response empty."
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    # Load this member's prior conversation and append the new user turn.
    history = _chat_history.setdefault(member_id, [])
    history.append({"role": "user", "content": [{"text": user_msg}]})
    # Trim: Bedrock requires messages to start with 'user'; drop oldest pairs when over cap
    while len(history) > _CHAT_HISTORY_CAP:
        history.pop(0)
        # If the oldest is now not a user turn, drop it too so the sequence stays valid
        while history and history[0].get("role") != "user":
            history.pop(0)
    messages = history
    attachment: dict | None = None  # last structured UI payload (labs, slots, booking_confirmed)
    for _ in range(6):  # up to 6 tool-use iterations
        resp = client.converse(
            modelId=settings.bedrock_model_id,
            system=[{"text": system_prompt}],
            messages=messages,
            toolConfig={"tools": _TOOL_SPEC},
            inferenceConfig={"maxTokens": 800, "temperature": 0.3},
        )
        out = resp.get("output", {}).get("message", {})
        stop = resp.get("stopReason")
        messages.append(out)

        if stop != "tool_use":
            texts = [b.get("text", "") for b in out.get("content", []) if "text" in b]
            joined = " ".join(texts).strip()
            cleaned = _clean_agent_reply(joined)
            # If we're surfacing an interactive picker, strip any duplicate text dumps from the reply
            if attachment and attachment.get("type") in ("slots", "labs"):
                cleaned = _strip_picker_text_dump(cleaned, attachment["type"])
            return {
                "reply": cleaned or "I didn't catch that — could you rephrase?",
                "attachment": attachment,
            }

        tool_results = []
        for block in out.get("content", []):
            if "toolUse" in block:
                tu = block["toolUse"]
                name = tu["name"]
                input_ = tu.get("input", {}) or {}
                result = _dispatch_tool(member_id, name, input_, user_location)

                # Capture structured UI attachments per tool
                if name == "show_my_profile" and "profile" in result:
                    attachment = {"type": "profile_summary", "profile": result["profile"], "lifestyle": result.get("lifestyle", {})}
                elif name == "show_my_appointments" and "appointments" in result:
                    attachment = {"type": "appointments_list", "items": result["appointments"]}
                elif name == "list_my_open_care_gaps" and "open_gaps" in result:
                    attachment = {"type": "gap_list", "items": result["open_gaps"]}
                elif name == "find_nearby_labs":
                    if "labs" in result:
                        attachment = {
                            "type": "labs",
                            "measure_id": input_.get("measure_id"),
                            "user_location": user_location,
                            "items": result["labs"],
                        }
                    elif result.get("error") == "location_unavailable":
                        attachment = {
                            "type": "location_prompt",
                            "measure_id": input_.get("measure_id"),
                            "message": "Please enable location access to find nearby screening labs.",
                        }
                elif name == "list_available_slots" and "slots" in result:
                    attachment = {
                        "type": "slots",
                        "items": result["slots"][:24],  # first 24 slots for the picker
                    }
                elif name == "book_appointment" and result.get("status") == "booked":
                    attachment = {
                        "type": "booking_confirmed",
                        "appointment": result.get("appointment", {}),
                    }

                tool_results.append({
                    "toolResult": {
                        "toolUseId": tu["toolUseId"],
                        "content": [{"json": result}],
                    }
                })
        messages.append({"role": "user", "content": tool_results})

    return {
        "reply": "I'm having trouble completing that right now. Please try again or use the Appointments tab to book directly.",
        "attachment": attachment,
    }


def _strip_picker_text_dump(text: str, kind: str) -> str:
    """When an interactive picker (slots/labs) is rendered, remove any text-list duplicates
    so the chat doesn't show a redundant bulleted dump of times/labs above the picker UI."""
    import re
    if not text:
        return text
    lines = text.split("\n")
    kept = []
    for ln in lines:
        s = ln.strip()
        if kind == "slots":
            # Drop lines that look like a time-list bullet:  "- 8:00 AM", "* 09:30", "8:00 AM", "Monday April 27"
            if re.match(r"^[-*•]?\s*\d{1,2}[:.]?\d{0,2}\s*(am|pm)?\s*$", s, re.IGNORECASE):
                continue
            if re.match(r"^[-*•]\s*\d{1,2}:\d{2}\s*(am|pm)?\s*$", s, re.IGNORECASE):
                continue
            # Header lines like "Monday, April 27, 2026" or "Available Slots:"
            if re.match(r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday),", s, re.IGNORECASE):
                continue
            if re.match(r"^(available|here are|the following)\s+(slots|times)", s, re.IGNORECASE):
                continue
        if kind == "labs":
            if re.match(r"^[-*•\d.]+\s+(LAB|Lab|Dr\.|Hospital|Clinic|Diagnostic)", s):
                continue
        kept.append(ln)
    out = "\n".join(kept).strip()
    # Collapse 3+ blank lines
    out = re.sub(r"\n{3,}", "\n\n", out)
    # If we stripped everything, fall back to a short prompt
    if not out:
        out = "Pick a slot below to continue." if kind == "slots" else "Pick a lab below to continue."
    return out


def _clean_agent_reply(text: str) -> str:
    """Strip reasoning leaks (Nova Pro sometimes emits <thinking> blocks, XML tags, or
    planning preambles in its final text output). Keeps the user-facing answer only."""
    import re
    if not text:
        return ""
    # Remove <thinking>...</thinking>, <reasoning>...</reasoning>, <scratchpad>...</scratchpad>
    text = re.sub(r"<\s*(thinking|reasoning|scratchpad|reflection|plan)\s*>.*?<\s*/\s*\1\s*>",
                  "", text, flags=re.IGNORECASE | re.DOTALL)
    # Strip any stray opening/closing reasoning tags (mismatched or truncated)
    text = re.sub(r"<\s*/?\s*(thinking|reasoning|scratchpad|reflection|plan)\s*>",
                  "", text, flags=re.IGNORECASE)
    # Collapse 3+ newlines and trim
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ── Push notifications (FCM token registration) ─────────────────────────────

@mobile_bp.route("/api/v1/mobile/push/register", methods=["POST"])
def push_register():
    member_id, err = _require_auth()
    if err:
        return err
    data = request.json or {}
    token = (data.get("fcm_token") or "").strip()
    if not token:
        return jsonify({"error": "fcm_token required"}), 400
    _push_tokens[member_id] = token
    return jsonify({"status": "registered"})


def get_push_token(member_id: str) -> str | None:
    """Used by the re-outreach scheduler to push a reminder to a specific member."""
    return _push_tokens.get(member_id)
