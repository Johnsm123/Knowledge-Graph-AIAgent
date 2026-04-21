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
)
from src.neo4j_connection import get_knowledge_graph


mobile_bp = Blueprint("mobile_api", __name__)
_logger = logging.getLogger(__name__)

_MOBILE_SECRET = "hedis-mobile-apk-2026"  # demo secret; move to env in prod
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30    # 30 days

# In-memory OTP + push-token stores (replace with Neo4j / Redis in prod)
_otp_store: dict[str, tuple[str, float]] = {}  # member_id -> (otp, expires_ts)
_push_tokens: dict[str, str] = {}              # member_id -> fcm_token


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
    member_id = (data.get("member_id") or "").strip()
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
    member_id = (data.get("member_id") or "").strip()
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

@mobile_bp.route("/api/v1/mobile/member/me", methods=["GET"])
def mobile_member_me():
    member_id, err = _require_auth()
    if err:
        return err

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
        RETURN a ORDER BY a.appointment_date DESC
        """,
        {"mid": member_id},
    )
    return jsonify({"appointments": [r.get("a", {}) for r in rows]})


@mobile_bp.route("/api/v1/mobile/appointments", methods=["POST"])
def mobile_book_appointment():
    """Book an appointment from the mobile app.

    Body: { "measure_id": "BCS", "appointment_date": "2026-05-12", "appointment_time": "10:00" }
    """
    member_id, err = _require_auth()
    if err:
        return err
    data = request.json or {}
    measure_id = data.get("measure_id")
    appt_date = data.get("appointment_date")
    appt_time = data.get("appointment_time")
    if not (measure_id and appt_date and appt_time):
        return jsonify({"error": "measure_id, appointment_date, appointment_time required"}), 400

    appointment_id = f"APT-{uuid.uuid4().hex[:8].upper()}"
    merge_appointment(
        appointment_id=appointment_id,
        member_id=member_id,
        measure_id=measure_id,
        appointment_date=appt_date,
        appointment_time=appt_time,
        lab_number="",
        lab_specialist="",
        lab_location="",
        screening_name="",
        cpt_codes="",
        icd_codes="",
        provider_id="",
        status="Scheduled",
        care_gap_id=data.get("care_gap_id", ""),
    )
    return jsonify({
        "status": "booked",
        "appointment": {
            "appointment_id": appointment_id,
            "member_id": member_id,
            "measure_id": measure_id,
            "appointment_date": appt_date,
            "appointment_time": appt_time,
            "status": "Scheduled",
        },
    })


# ── Conversational agent ─────────────────────────────────────────────────────

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
    if not user_msg:
        return jsonify({"error": "message required"}), 400

    try:
        reply = _run_member_chat(member_id, user_msg)
        return jsonify({"reply": reply})
    except Exception as exc:
        _logger.error(f"[MOBILE] chat error for {member_id}: {exc}", exc_info=True)
        return jsonify({"reply": "Sorry, I couldn't process that right now. Please try again."})


def _run_member_chat(member_id: str, user_msg: str) -> str:
    """Run Bedrock Converse against this member's context only."""
    import boto3
    from config.settings import settings

    profile = get_member_profile(member_id) or {}
    ext = get_member_extended_profile(member_id) or {}
    gaps = get_member_open_gaps(member_id) or []

    context = {"profile": profile, "extended": ext, "open_gaps": gaps}
    system_prompt = (
        "You are a friendly personal health assistant for a single patient. "
        "You have access to that patient's profile, care gaps, and appointments below. "
        "Answer only questions relevant to this patient. Never disclose data about other patients. "
        "If the patient wants to book an appointment, tell them which care gap you'd book for "
        "and ask them to tap the 'Book' button in the app.\n\n"
        f"PATIENT CONTEXT:\n{json.dumps(context, default=str)[:4000]}"
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    response = client.converse(
        modelId=settings.bedrock_model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_msg}]}],
        inferenceConfig={"maxTokens": 500, "temperature": 0.4},
    )
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    return " ".join(b.get("text", "") for b in blocks if "text" in b).strip()


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
