"""Mobile reminder scheduler + Firebase Cloud Messaging push sender.

Three reminder jobs (APScheduler):
  1. Day-before 18:00 local — "You have BCS screening tomorrow at 10 AM"
  2. Morning-of   08:00 local — "Your screening is today at 10 AM"
  3. Post-appointment +2h    — "We noticed you missed your BCS — want to reschedule?"

Every reminder:
  - Writes a proactive chat message into a per-member queue (surfaced when member opens Chat)
  - Sends FCM push (if Firebase Admin configured)
  - Sends email reminder via Azure Communication Services
  - For missed appointments: also flips status to "No Show" and emits socket event
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

_logger = logging.getLogger(__name__)

# In-memory proactive message queue: member_id -> list of messages
# (Persist to Neo4j in future iteration; in-memory is fine for single-worker deployment.)
_proactive_queue: dict[str, list[dict[str, Any]]] = {}


# ── Firebase Admin bootstrap (idempotent, lazy) ─────────────────────────────

_fb_initialized = False


def _init_firebase() -> bool:
    """Initialize firebase-admin once. Returns True if ready to send pushes."""
    global _fb_initialized
    if _fb_initialized:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        _logger.warning("[REMINDER] firebase-admin not installed; push disabled")
        return False

    # Try env var first (Azure), then local JSON file (dev)
    raw = os.environ.get("FIREBASE_ADMIN_CREDENTIALS")
    if raw:
        try:
            cred_dict = json.loads(raw)
            cred = credentials.Certificate(cred_dict)
        except Exception as exc:
            _logger.warning(f"[REMINDER] FIREBASE_ADMIN_CREDENTIALS env var invalid: {exc}")
            return False
    else:
        # dev fallback — file at project root
        key_path = os.path.join(os.getcwd(), "firebase-admin.json")
        if not os.path.exists(key_path):
            _logger.info("[REMINDER] No Firebase credentials found; push notifications disabled (email still works)")
            return False
        cred = credentials.Certificate(key_path)

    try:
        firebase_admin.initialize_app(cred)
        _fb_initialized = True
        _logger.info("[REMINDER] Firebase Admin initialized")
        return True
    except ValueError:
        # already initialized in another worker
        _fb_initialized = True
        return True
    except Exception as exc:
        _logger.warning(f"[REMINDER] Firebase init failed: {exc}")
        return False


def send_push(token: str, title: str, body: str, data: dict | None = None,
              channel_id: str = "appointments") -> bool:
    """Send a push notification to a single device. Returns True on success.

    On Android we explicitly target a HIGH/MAX-importance channel so the
    notification appears in the system drawer (drop-down) and as a heads-up
    banner — even if the app is closed or the device is locked.
    """
    if not token or not _init_firebase():
        return False
    try:
        from firebase_admin import messaging
        msg = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    title=title,
                    body=body,
                    channel_id=channel_id,
                    default_sound=True,
                    default_vibrate_timings=True,
                    visibility="public",
                    notification_count=1,
                ),
            ),
        )
        messaging.send(msg)
        return True
    except Exception as exc:
        _logger.warning(f"[REMINDER] FCM send failed: {exc}")
        return False


# ── Proactive chat queue ────────────────────────────────────────────────────

def enqueue_proactive_message(member_id: str, text: str, kind: str = "reminder") -> None:
    """Queue a bot message that will appear at top of chat when member opens Assistant."""
    _proactive_queue.setdefault(member_id, []).append({
        "id": f"PROACTIVE-{uuid.uuid4().hex[:8]}",
        "text": text,
        "kind": kind,
        "timestamp": datetime.now().isoformat(),
    })


def drain_proactive_messages(member_id: str) -> list[dict[str, Any]]:
    """Return and clear queued proactive messages for this member."""
    msgs = _proactive_queue.pop(member_id, [])
    return msgs


# ── Email reminder ──────────────────────────────────────────────────────────

def _send_reminder_email(member_profile: dict, appt: dict, kind: str) -> None:
    """Send reminder email via Azure Communication Services."""
    try:
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg

        if not cfg.azure_communication_connection_string:
            return
        email = member_profile.get("email") or ""
        if not email:
            return

        name = member_profile.get("name", "Member")
        measure_name = appt.get("screening_name") or appt.get("measure_id")
        date_str = appt.get("appointment_date")
        time_str = appt.get("appointment_time")
        location = appt.get("lab_location", "")

        subjects = {
            "day_before": f"Reminder: {measure_name} screening tomorrow",
            "morning_of": f"Today: {measure_name} screening",
            "missed":     f"Missed appointment — {measure_name}",
        }
        subject = subjects.get(kind, "Appointment reminder")

        headline = {
            "day_before": f"Your {measure_name} screening is tomorrow.",
            "morning_of": f"Your {measure_name} screening is today.",
            "missed":     f"We noticed you missed your {measure_name} appointment.",
        }[kind]

        cta = {
            "day_before": "Please arrive 15 minutes early. Bring your ID and insurance card.",
            "morning_of": "Please leave early if traveling. Arrive 15 minutes before your slot.",
            "missed":     "Open the Cognizant Care app to reschedule when you're ready.",
        }[kind]

        html = f"""
<html><body style="font-family:Arial,sans-serif;color:#000048;max-width:620px;margin:auto;">
<div style="background:#000048;padding:20px 28px;">
  <h1 style="color:#FFFFFF;margin:0;font-size:20px;">Cognizant Care</h1>
  <p style="color:#92BBE6;margin:4px 0 0;font-size:12px;">Appointment reminder</p>
</div>
<div style="border:1px solid #E8E8E6;border-top:none;padding:28px;">
  <p style="font-size:15px;">Dear <strong>{name}</strong>,</p>
  <p style="font-size:15px;">{headline}</p>
  <table style="width:100%;border-collapse:collapse;margin:18px 0;">
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Screening</strong></td><td style="padding:8px 12px;">{measure_name}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Date</strong></td><td style="padding:8px 12px;">{date_str}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Time</strong></td><td style="padding:8px 12px;">{time_str}</td></tr>
    <tr><td style="padding:8px 12px;background:#F7F7F5;"><strong>Location</strong></td><td style="padding:8px 12px;">{location}</td></tr>
  </table>
  <p style="font-size:14px;color:#53565A;">{cta}</p>
</div>
</body></html>"""

        client = EmailClient.from_connection_string(cfg.azure_communication_connection_string)
        client.begin_send({
            "senderAddress": cfg.azure_communication_sender,
            "recipients": {"to": [{"address": email, "displayName": name}]},
            "content": {"subject": subject, "plainText": headline + "\n\n" + cta, "html": html},
        })
    except Exception as exc:
        _logger.warning(f"[REMINDER] email failed: {exc}")


# ── Core reminder logic ─────────────────────────────────────────────────────

def _fire_reminders(kind: str, appointments: list[dict]) -> None:
    """Send all three reminder channels for a batch of appointments."""
    from src.care_gap_neo4j import get_member_profile

    try:
        from src.mobile_api import get_push_token
    except Exception:
        get_push_token = lambda _mid: None  # noqa: E731

    # Proactive bot message text per kind
    bot_text = {
        "day_before": lambda a: (
            f"Reminder: you have a **{a.get('screening_name') or a.get('measure_id')}** "
            f"screening tomorrow at {a.get('appointment_time')}. "
            f"Location: {a.get('lab_location', 'TBA')}. "
            f"Please arrive 15 minutes early with your ID. Want to reschedule?"
        ),
        "morning_of": lambda a: (
            f"Your **{a.get('screening_name') or a.get('measure_id')}** screening is today at "
            f"{a.get('appointment_time')} — {a.get('lab_location', '')}. "
            f"Need directions or a reschedule?"
        ),
        "missed": lambda a: (
            f"I noticed you missed your **{a.get('screening_name') or a.get('measure_id')}** "
            f"screening on {a.get('appointment_date')} at {a.get('appointment_time')}. "
            f"Would you like to reschedule it? I can find another slot at a nearby lab."
        ),
    }[kind]

    for a in appointments:
        member_id = a.get("member_id")
        if not member_id:
            continue
        profile = get_member_profile(member_id) or {}

        text = bot_text(a)

        # 1. Queue proactive chat message
        enqueue_proactive_message(member_id, text, kind=kind)

        # 2. Email reminder
        _send_reminder_email(profile, a, kind)

        # 3. FCM push (best-effort)
        token = get_push_token(member_id)
        if token:
            titles = {
                "day_before": "Screening Reminder",
                "morning_of": "Screening Today",
                "missed": "Missed Appointment",
            }
            bodies = {
                "day_before": f"{a.get('screening_name') or a.get('measure_id')} tomorrow at {a.get('appointment_time')}",
                "morning_of": f"{a.get('screening_name') or a.get('measure_id')} today at {a.get('appointment_time')}",
                "missed":     f"Tap to reschedule your {a.get('screening_name') or a.get('measure_id')} screening",
            }
            send_push(token, titles[kind], bodies[kind],
                      data={"member_id": member_id, "appointment_id": a.get("appointment_id", ""), "kind": kind})

        _logger.info(f"[REMINDER/{kind}] fired for {member_id} appt {a.get('appointment_id')}")


def _query_appointments_for(target_date: str, status: str = "Scheduled") -> list[dict]:
    from src.neo4j_connection import get_knowledge_graph
    kg = get_knowledge_graph()
    rows = kg.run_query(
        """
        MATCH (a:Appointment)
        WHERE a.appointment_date = $d AND a.status = $s
        RETURN a.appointment_id AS appointment_id, a.member_id AS member_id,
               a.measure_id AS measure_id, a.screening_name AS screening_name,
               a.appointment_date AS appointment_date, a.appointment_time AS appointment_time,
               a.lab_location AS lab_location, a.status AS status
        """,
        {"d": target_date, "s": status},
    )
    return rows or []


def _mark_no_show(appointment_id: str, member_id: str = "", care_gap_id: str = "",
                  appointment_date: str = "") -> None:
    from src.neo4j_connection import get_knowledge_graph
    kg = get_knowledge_graph()
    kg.run_query(
        "MATCH (a:Appointment {appointment_id: $id}) SET a.status = 'No Show' RETURN a",
        {"id": appointment_id},
    )
    # Sync timeline event in reference DB
    if care_gap_id:
        try:
            from src.persona_sync import sync_appointment_no_show
            sync_appointment_no_show(
                member_id=member_id,
                care_gap_id=care_gap_id,
                appointment_id=appointment_id,
                appointment_date=appointment_date,
            )
        except Exception as exc:
            _logger.warning(f"[REMINDER] no-show timeline sync failed: {exc}")


# ── Scheduled job entrypoints ───────────────────────────────────────────────

def run_day_before():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    appts = _query_appointments_for(tomorrow)
    _logger.info(f"[REMINDER/day_before] scanning {tomorrow}: {len(appts)} appointments")
    _fire_reminders("day_before", appts)


def run_morning_of():
    today = datetime.now().strftime("%Y-%m-%d")
    appts = _query_appointments_for(today)
    _logger.info(f"[REMINDER/morning_of] scanning {today}: {len(appts)} appointments")
    _fire_reminders("morning_of", appts)


def run_missed_sweep():
    """Find appointments whose scheduled end is >2h ago and still Scheduled -> mark No Show."""
    from src.neo4j_connection import get_knowledge_graph
    kg = get_knowledge_graph()
    cutoff = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    rows = kg.run_query(
        """
        MATCH (a:Appointment)
        WHERE a.status = 'Scheduled'
          AND a.appointment_date + 'T' + a.appointment_time < $cutoff
        RETURN a.appointment_id AS appointment_id, a.member_id AS member_id,
               a.measure_id AS measure_id, a.screening_name AS screening_name,
               a.appointment_date AS appointment_date, a.appointment_time AS appointment_time,
               a.lab_location AS lab_location, a.status AS status,
               a.care_gap_id AS care_gap_id
        """,
        {"cutoff": cutoff},
    ) or []

    _logger.info(f"[REMINDER/missed] {len(rows)} appointments past their time")
    for row in rows:
        _mark_no_show(
            appointment_id=row["appointment_id"],
            member_id=row.get("member_id", ""),
            care_gap_id=row.get("care_gap_id", "") or "",
            appointment_date=row.get("appointment_date", ""),
        )
        # Emit socket event so portal refreshes
        try:
            from src.care_gap_api import emit_portal_event
            emit_portal_event("appointment_booked", {
                "member_id": row["member_id"],
                "appointment_id": row["appointment_id"],
                "status": "No Show",
                "source": "reminder_sweep",
            })
        except Exception:
            pass

    _fire_reminders("missed", rows)


# ── Scheduler bootstrap ─────────────────────────────────────────────────────

def start_mobile_reminder_scheduler():
    """DISABLED — recurring mobile reminder emails (day-before, morning-of,
    missed-sweep) are turned off to save the ACS daily quota. Email sending
    is now limited to the bulk-upload Proceed-with-Outreach flow and the
    per-member Auto Process button. Re-enable by restoring the original
    body if you need automatic appointment reminders again.
    """
    _logger.info("[REMINDER] mobile reminder scheduler is DISABLED (auto recurring emails turned off)")
    return None
