"""
WhatsApp messaging service via Twilio.
Sends notifications through WhatsApp for:
  - Appointment booking confirmations (uses content template)
  - Care gap analysis reports (freeform body)
"""
import json
import logging
from config.settings import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    """Lazy-init Twilio client."""
    global _client
    if _client is None:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise RuntimeError("Twilio not configured (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)")
        from twilio.rest import Client
        _client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _client


def _format_phone(phone: str) -> str:
    """Ensure phone is in whatsapp:+... format."""
    phone = phone.strip()
    if phone.startswith("whatsapp:"):
        return phone
    if not phone.startswith("+"):
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            # Assume Indian number for 10-digit
            phone = f"+91{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            phone = f"+{digits}"
        else:
            phone = f"+{digits}"
    return f"whatsapp:{phone}"


def send_whatsapp(to_phone: str, body: str) -> dict:
    """
    Send a freeform WhatsApp message via Twilio.
    Works within the 24-hour conversation window after user opts in.
    """
    try:
        client = _get_client()
        to_wa = _format_phone(to_phone)
        from_wa = settings.twilio_whatsapp_from
        logger.info(f"[WHATSAPP] Sending freeform to {to_wa} from {from_wa}")

        message = client.messages.create(
            body=body,
            from_=from_wa,
            to=to_wa,
        )
        logger.info(f"[WHATSAPP] Sent to {to_wa} — SID: {message.sid}, status: {message.status}")
        return {"success": True, "sid": message.sid, "status": message.status}
    except Exception as e:
        logger.error(f"[WHATSAPP] Freeform failed to {to_phone}: {e}")
        return {"success": False, "error": str(e)}


def send_whatsapp_template(to_phone: str, content_sid: str, variables: dict) -> dict:
    """
    Send a WhatsApp message using a Twilio Content Template.
    Works outside the 24-hour window — more reliable for proactive notifications.
    """
    try:
        client = _get_client()
        to_wa = _format_phone(to_phone)
        from_wa = settings.twilio_whatsapp_from
        logger.info(f"[WHATSAPP] Sending template {content_sid} to {to_wa}")

        message = client.messages.create(
            from_=from_wa,
            to=to_wa,
            content_sid=content_sid,
            content_variables=json.dumps(variables),
        )
        logger.info(f"[WHATSAPP] Template sent to {to_wa} — SID: {message.sid}, status: {message.status}")
        return {"success": True, "sid": message.sid, "status": message.status}
    except Exception as e:
        logger.error(f"[WHATSAPP] Template failed to {to_phone}: {e}")
        return {"success": False, "error": str(e)}


# ── Pre-built message senders ──────────────────────────────────────────────

# Twilio sandbox default appointment template
APPOINTMENT_TEMPLATE_SID = "HXb5b62575e6e4ff6129ad7c8efe1f983e"


def send_appointment_confirmation(to_phone, member_name, measure_name,
                                   appointment_date, appointment_time,
                                   appointment_id, lab_location, lab_specialist):
    """
    Send appointment booking confirmation via WhatsApp.
    Uses content template first (works outside 24h window),
    falls back to freeform if template fails.
    """
    # Try template first: "Your appointment is coming up on {1} at {2}"
    template_result = send_whatsapp_template(
        to_phone=to_phone,
        content_sid=APPOINTMENT_TEMPLATE_SID,
        variables={"1": appointment_date, "2": appointment_time},
    )
    if template_result.get("success"):
        return template_result

    # Fallback: freeform message with full details
    logger.info(f"[WHATSAPP] Template failed, trying freeform for {member_name}")
    body = (
        f"Hi {member_name},\n\n"
        f"Your appointment has been confirmed:\n\n"
        f"*{measure_name}*\n"
        f"Date: {appointment_date}\n"
        f"Time: {appointment_time}\n"
        f"Location: {lab_location}\n"
        f"Doctor: {lab_specialist}\n"
        f"Ref: {appointment_id}\n\n"
        f"Please arrive 15 min early with your ID and insurance card.\n\n"
        f"HealthCare Management Portal"
    )
    return send_whatsapp(to_phone, body)


def send_care_gap_report(to_phone, member_name, gaps, portal_url=""):
    """
    Send care gap analysis summary via WhatsApp.
    Uses freeform message (requires 24h opt-in window for sandbox).
    """
    from src.pdf_report import _friendly

    gap_lines = []
    for i, g in enumerate(gaps, 1):
        mid = g.get("measure_id", "")
        friendly_name, _, _ = _friendly(mid, g.get("resolution_guide") or g.get("description", ""))
        gap_lines.append(f"{i}. {friendly_name}")

    gap_list = "\n".join(gap_lines)
    portal_line = f"\nBook appointments: {portal_url}" if portal_url else ""

    body = (
        f"Hi {member_name},\n\n"
        f"Your preventive care report is ready.\n\n"
        f"*Recommended Screenings ({len(gaps)}):*\n"
        f"{gap_list}\n\n"
        f"A detailed report has been sent to your email."
        f"{portal_line}\n\n"
        f"HealthCare Management Portal"
    )
    return send_whatsapp(to_phone, body)
