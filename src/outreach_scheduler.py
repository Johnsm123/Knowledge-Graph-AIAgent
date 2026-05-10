"""
Outreach reminder scheduler — runs in the background of the Flask app.

Two recurring jobs:

  1. **Rebook reminder** (hourly): for every appointment whose status is
     `Cancelled_NoShow` / `No Show` / `Cancelled` and whose underlying care
     gap is still open, send a reminder email with the booking link so the
     member can rebook through the portal.

  2. **Weekly reminder** (daily check, sent at most once / 7 days per
     member): for any member with at least one open care gap and no booked
     appointment, send a weekly reminder email with the booking link.

The scheduler is intentionally simple — a daemon thread polling on an
interval. It never blocks the request thread, and any failure inside a job
is logged but does not crash the loop.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger("outreach-scheduler")

# Interval in seconds between scheduler ticks. We intentionally pick a short
# tick (10 minutes) — each job decides when it actually wants to fire based
# on the per-member last-reminder timestamp stored on the member node.
TICK_SECONDS = 10 * 60

REBOOK_COOLDOWN_HOURS  = 24      # don't spam — at most one rebook nudge / day
WEEKLY_COOLDOWN_DAYS   = 7

_scheduler_started = False
_scheduler_lock = threading.Lock()


def start_scheduler() -> None:
    """Idempotent — only spawns the background thread once per process."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="outreach-scheduler")
    t.start()
    log.info("[outreach-scheduler] started (tick=%ds)", TICK_SECONDS)


def _scheduler_loop():
    # Recurring outreach emails (rebook + weekly) are intentionally NOT
    # called from the loop. Email sends are limited to the bulk-upload
    # "Proceed with Outreach" flow and the per-member "Auto Process" button
    # so we don't burn the Azure ACS daily quota on background nudges.
    # Data-only jobs (auto-close, auto-cancel no-shows) still run since they
    # never touch the email service.
    while True:
        try:
            run_auto_close_completed()
        except Exception:
            log.exception("auto-close pass failed")
        try:
            run_auto_cancel_no_shows()
        except Exception:
            log.exception("auto-cancel no-show pass failed")
        time.sleep(TICK_SECONDS)


# ─── Job 3 — auto-close care gaps for completed appointments ─────────────────

def run_auto_close_completed() -> int:
    """For every appointment marked Completed whose underlying CareGap is
    still open: generate a claim, close the gap, mark member compliant if
    all gaps are now closed. Replaces the manual "Force Close" UI flow."""
    # Use MATCH (not OPTIONAL MATCH) so already-closed gaps drop out of the
    # result set entirely — otherwise the row is still emitted with g=null
    # and the loop below blindly creates a fresh claim every tick. Only emit
    # rows where the gap is open AND has no claim yet.
    rows = _kg().run_query(
        """
        MATCH (m:Member)-[:HAS_APPOINTMENT]->(a:Appointment)
        WHERE a.status = 'Completed'
        MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: a.care_gap_id})
        WHERE coalesce(g.is_open, true) = true
          AND (g.claim_id IS NULL OR g.claim_id = '')
        RETURN m.member_id        AS member_id,
               a.care_gap_id      AS care_gap_id,
               coalesce(a.measure_id, g.measure_id) AS measure_id,
               a.cpt_codes        AS cpt_codes,
               a.icd_codes        AS icd_codes,
               a.appointment_date AS appointment_date
        """, {}
    ) or []
    import uuid as _uuid
    closed = 0
    for r in rows:
        mid = r.get("member_id"); cgid = r.get("care_gap_id")
        if not (mid and cgid):
            continue
        claim_id = f"AUTO-CLM-{mid}-{(r.get('measure_id') or 'GEN')}-{_uuid.uuid4().hex[:6]}"
        _kg().run_query(
            """
            MATCH (m:Member {member_id: $mid})
            MERGE (c:Claim {claim_id: $cid})
            SET c.member_id   = $mid, c.measure_id = $measure_id,
                c.cpt_code    = $cpt, c.icd_code   = $icd,
                c.service_date = $sdate, c.status  = 'Processed',
                c.created_on  = $now,  c.auto_generated = true
            MERGE (m)-[:HAS_CLAIM]->(c)
            WITH m
            MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: $cgid})
            SET g.is_open = false, g.gap_status = 'Closed',
                g.closed_on = $now, g.claim_id = $cid
            """,
            {"mid": mid, "cid": claim_id, "cgid": cgid,
             "measure_id": r.get("measure_id") or "",
             "cpt": r.get("cpt_codes") or "",
             "icd": r.get("icd_codes") or "",
             "sdate": r.get("appointment_date") or datetime.now().date().isoformat(),
             "now":   datetime.now().isoformat()},
        )
        # Keep the matching Appointment status in sync so the member panel
        # timer stops once the gap is closed.
        _kg().run_query(
            """
            MATCH (m:Member {member_id: $mid})-[:HAS_APPOINTMENT]->(a:Appointment)
            WHERE a.care_gap_id = $cgid AND a.status IN ['Scheduled','Booked']
            SET a.status = 'Completed', a.completed_at = $now, a.claim_id = $cid
            """,
            {"mid": mid, "cgid": cgid, "now": datetime.now().isoformat(), "cid": claim_id},
        )
        closed += 1
        try:
            from src.persona_sync import sync_gap_closed
            sync_gap_closed(mid, cgid)
        except Exception:
            pass
    if closed:
        # Recompute compliance flag per member.
        _kg().run_query(
            """
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE coalesce(g.is_open, true) = true
            WITH m, count(g) AS open_count
            SET m.health_status   = CASE WHEN open_count = 0 THEN 'Compliant' ELSE m.health_status END,
                m.compliance_score = CASE WHEN open_count = 0 THEN 100.0 ELSE coalesce(m.compliance_score, 0.0) END
            """, {}
        )
        log.info("[auto-close] closed %d gap(s) and recomputed compliance", closed)
    return closed


# ─── Job 4 — auto-cancel scheduled appointments past their scheduled time ─────

def run_auto_cancel_no_shows() -> int:
    """If a Scheduled appointment's date+time is in the past and the gap is
    still open, mark it Cancelled_NoShow so the rebook reminder kicks in."""
    rows = _kg().run_query(
        """
        MATCH (m:Member)-[:HAS_APPOINTMENT]->(a:Appointment)
        WHERE a.status IN ['Scheduled', 'Booked']
        RETURN m.member_id   AS member_id,
               a.appointment_id AS appointment_id,
               a.care_gap_id    AS care_gap_id,
               a.appointment_date AS d,
               a.appointment_time AS t
        """, {}
    ) or []
    flipped = 0
    now = datetime.now()
    for r in rows:
        try:
            d = r.get("d"); t = r.get("t") or "09:00"
            if not d:
                continue
            sched = datetime.fromisoformat(f"{d}T{t}")
            # Allow a 60-minute grace period after the scheduled time.
            if sched + timedelta(minutes=60) > now:
                continue
            _kg().run_query(
                """
                MATCH (a:Appointment {appointment_id: $aid})
                SET a.status = 'Cancelled_NoShow',
                    a.auto_cancelled_at = $now
                """,
                {"aid": r["appointment_id"], "now": now.isoformat()},
            )
            flipped += 1
            try:
                from src.persona_sync import sync_appointment_no_show
                sync_appointment_no_show(r["member_id"], r["care_gap_id"])
            except Exception:
                pass
        except Exception:
            continue
    if flipped:
        log.info("[auto-cancel] flipped %d past-due appointment(s) to Cancelled_NoShow", flipped)
    return flipped


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _kg():
    from src.neo4j_connection import get_knowledge_graph
    return get_knowledge_graph()


def _portal_url(member_id: str) -> str:
    try:
        from src.member_portal import get_portal_url
        return get_portal_url(member_id)
    except Exception:
        return f"http://localhost:5001/api/v1/portal/member/{member_id}"


def _send_email(to_addr: str, subject: str, html: str) -> bool:
    """Recurring email sends from the scheduler are DISABLED to preserve the
    Azure ACS daily quota for the only flows the user wants emails from:
    bulk upload Proceed-with-Outreach and the per-member Auto Process button.
    Re-enable by removing the early return below if you ever want background
    rebook / weekly nudges to resume."""
    log.info("[email-disabled] skipping send to %s — subject=%r", to_addr, subject)
    return False
    try:  # noqa: F841  (legacy code retained for reference)
        from azure.communication.email import EmailClient
        from config.settings import settings as cfg
        conn_str = cfg.azure_communication_connection_string
        sender   = cfg.azure_communication_sender
        if not (conn_str and sender and to_addr):
            return False
        client = EmailClient.from_connection_string(conn_str)
        msg = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to_addr}]},
            "content": {"subject": subject, "html": html},
        }
        client.begin_send(msg)
        return True
    except Exception as e:
        log.warning("email send failed to %s: %s", to_addr, e)
        return False


def _email_body(member_name: str, member_id: str, gaps: list, kind: str) -> str:
    portal_url = _portal_url(member_id)
    headline = (
        "Reminder — Please rebook your missed screening"
        if kind == "rebook"
        else "Weekly reminder — Your preventive screenings are still due"
    )
    intro = (
        "We noticed you missed your recent appointment. Please use the link "
        "below to rebook a convenient time — completing this screening is "
        "important for your long-term health."
        if kind == "rebook"
        else
        "This is your weekly reminder that the preventive screenings below "
        "are still due. Please use the link to schedule them at your "
        "convenience."
    )
    # Always render the FULL measure name in the email so the member can read
    # it without decoding HEDIS codes. Falls back to the code only if the
    # name is genuinely missing.
    from src.hedis_golden_reference import HEDIS_MEASURES as _HEDIS
    def _full_name(g):
        mname = g.get("measure_name")
        if mname:
            return mname
        mid = g.get("measure_id")
        if mid and mid in _HEDIS:
            return _HEDIS[mid].get("name") or mid
        return mid or "Annual wellness screening"
    gap_list = "".join(
        f"<li><strong>{_full_name(g)}</strong></li>"
        for g in (gaps or [])
    ) or "<li>Annual wellness visit</li>"
    return f"""
<html><body style="font-family:Arial,sans-serif;color:#1a1a2e;max-width:680px;margin:auto;">
  <div style="background:#0033A1;padding:20px 32px;border-radius:8px 8px 0 0;">
    <h1 style="color:white;margin:0;font-size:22px;">HealthCare Management Portal</h1>
    <p style="color:#b3c7f7;margin:4px 0 0;">{headline}</p>
  </div>
  <div style="border:1px solid #dce3f5;border-top:none;padding:32px;border-radius:0 0 8px 8px;">
    <p style="font-size:16px;">Dear <strong>{member_name}</strong>,</p>
    <p>{intro}</p>
    <ul style="font-size:14px;line-height:1.6;color:#1a1a2e;">{gap_list}</ul>
    <div style="text-align:center;margin:28px 0;">
      <a href="{portal_url}" style="background:#059669;color:white;padding:14px 36px;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">Book Appointment</a>
    </div>
    <p style="color:#666;font-size:13px;">If you've already scheduled, please disregard this message.</p>
  </div>
</body></html>"""


# ─── Job 1 — rebook reminders for missed appointments ────────────────────────

def run_rebook_reminders() -> int:
    """DISABLED — recurring rebook nudges are turned off to save the ACS
    daily quota. Returns 0 without sending. The data path (auto-cancel
    flipping past-due appointments to Cancelled_NoShow) still runs."""
    return 0


def _disabled_run_rebook_reminders() -> int:
    """Original implementation, kept here for reference."""
    rows = _kg().run_query(
        """
        MATCH (m:Member)-[:HAS_APPOINTMENT]->(a:Appointment)
        WHERE a.status IN ['Cancelled', 'Cancelled_NoShow', 'No Show']
        OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: a.care_gap_id})
        WHERE coalesce(g.is_open, true) = true
        WITH m, a, g, m.email AS email
        WHERE email IS NOT NULL AND email <> ''
        RETURN m.member_id           AS member_id,
               m.name                AS name,
               email,
               m.last_rebook_reminder_at AS last_sent,
               collect(DISTINCT {measure_id: g.measure_id, measure_name: g.measure_name}) AS gaps
        """, {}
    ) or []
    sent = 0
    cutoff = datetime.now() - timedelta(hours=REBOOK_COOLDOWN_HOURS)
    for r in rows:
        last = r.get("last_sent")
        try:
            if last and datetime.fromisoformat(str(last)) > cutoff:
                continue
        except Exception:
            pass
        ok = _send_email(
            r["email"],
            f"Action needed — please rebook your appointment",
            _email_body(r.get("name", ""), r["member_id"], r.get("gaps", []), kind="rebook"),
        )
        if ok:
            _kg().run_query(
                "MATCH (m:Member {member_id: $mid}) SET m.last_rebook_reminder_at = $now",
                {"mid": r["member_id"], "now": datetime.now().isoformat()},
            )
            sent += 1
    if sent:
        log.info("[rebook] sent %d reminder email(s)", sent)
    return sent


# ─── Job 2 — weekly reminder for never-booked members ────────────────────────

def run_weekly_reminders() -> int:
    """DISABLED — weekly reminder emails are turned off to save the ACS
    daily quota. Returns 0 without sending."""
    return 0


def _disabled_run_weekly_reminders() -> int:
    """Original implementation, kept here for reference."""
    rows = _kg().run_query(
        """
        MATCH (m:Member)
        WHERE m.email IS NOT NULL AND m.email <> ''
        OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
        WHERE coalesce(g.is_open, true) = true
        WITH m,
             collect(DISTINCT {measure_id: g.measure_id, measure_name: g.measure_name}) AS gaps,
             count(g) AS open_gap_count
        WHERE open_gap_count > 0
        OPTIONAL MATCH (m)-[:HAS_APPOINTMENT]->(a:Appointment)
        WHERE a.status IN ['Scheduled', 'Booked']
        WITH m, gaps, count(a) AS booked_count
        WHERE booked_count = 0
        RETURN m.member_id           AS member_id,
               m.name                AS name,
               m.email               AS email,
               m.last_weekly_reminder_at AS last_sent,
               gaps
        """, {}
    ) or []
    sent = 0
    cutoff = datetime.now() - timedelta(days=WEEKLY_COOLDOWN_DAYS)
    for r in rows:
        last = r.get("last_sent")
        try:
            if last and datetime.fromisoformat(str(last)) > cutoff:
                continue
        except Exception:
            pass
        ok = _send_email(
            r["email"],
            f"Weekly reminder — Your preventive screenings are still due",
            _email_body(r.get("name", ""), r["member_id"], r.get("gaps", []), kind="weekly"),
        )
        if ok:
            _kg().run_query(
                "MATCH (m:Member {member_id: $mid}) SET m.last_weekly_reminder_at = $now",
                {"mid": r["member_id"], "now": datetime.now().isoformat()},
            )
            sent += 1
    if sent:
        log.info("[weekly] sent %d reminder email(s)", sent)
    return sent
