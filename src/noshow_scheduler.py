"""
No-show auto-cancel + re-outreach scheduler.

Runs daily at 09:00 IST. Finds appointments whose date is more than one
day in the past and whose status is still 'Scheduled' (not 'Completed').
For each:
  1. Mark the appointment as 'Cancelled_NoShow'
  2. Increment the member's retry counter
  3. If retries < 3 -> re-trigger the first-time outreach email (invite +
     appointment willingness link).
  4. If retries >= 3 -> mark member 'Unreachable', stop re-outreach.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.neo4j_connection import get_knowledge_graph
from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_member_profile,
)

_logger = logging.getLogger(__name__)

MAX_RETRIES = 3
GRACE_DAYS = 1  # appointments >1 day past without completion are treated as no-show


def find_no_show_appointments() -> list[dict]:
    """Return appointments whose date is more than GRACE_DAYS ago and still 'Scheduled'."""
    kg = get_knowledge_graph()
    cutoff = (datetime.utcnow().date() - timedelta(days=GRACE_DAYS)).isoformat()
    rows = kg.run_query(
        """
        MATCH (a:Appointment)
        WHERE a.appointment_date < $cutoff
          AND coalesce(a.status, 'Scheduled') = 'Scheduled'
        RETURN a.appointment_id AS appointment_id,
               a.member_id       AS member_id,
               a.measure_id      AS measure_id,
               a.appointment_date AS appointment_date
        """,
        {"cutoff": cutoff},
    )
    return rows


def mark_appointment_no_show(appointment_id: str):
    """Canonical status string is 'No Show' (used by portal + mobile).

    Also reopens the linked CareGap so the member can rebook the same screening.
    """
    kg = get_knowledge_graph()
    kg.execute_write(
        """
        MATCH (a:Appointment {appointment_id: $aid})
        SET a.status = 'No Show',
            a.cancelled_at = datetime(),
            a.cancel_reason = 'Member did not complete screening on scheduled date'
        WITH a
        OPTIONAL MATCH (g:CareGap {care_gap_id: a.care_gap_id})
        FOREACH (_ IN CASE WHEN g IS NULL THEN [] ELSE [1] END |
            SET g.is_open = true,
                g.gap_status = 'Open',
                g.last_no_show_at = datetime()
        )
        """,
        {"aid": appointment_id},
    )


def get_retry_count(member_id: str) -> int:
    kg = get_knowledge_graph()
    rows = kg.run_query(
        """
        MATCH (m:Member {member_id: $mid})
        RETURN coalesce(m.reoutreach_attempts, 0) AS attempts
        """,
        {"mid": member_id},
    )
    if not rows:
        return 0
    return int(rows[0].get("attempts", 0))


def increment_retry(member_id: str) -> int:
    kg = get_knowledge_graph()
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})
        SET m.reoutreach_attempts = coalesce(m.reoutreach_attempts, 0) + 1,
            m.last_reoutreach_at  = datetime()
        """,
        {"mid": member_id},
    )
    return get_retry_count(member_id) 


def mark_unreachable(member_id: str): 
    kg = get_knowledge_graph()
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})
        SET m.outreach_status = 'Unreachable',
            m.unreachable_at  = datetime()
        """,
        {"mid": member_id},
    )


def send_reoutreach_email(member_id: str) -> bool:
    """Re-trigger the first-time invite email for this member's open gaps."""
    from src.member_portal import _send_analysis_email, get_portal_url

    profile = get_member_profile(member_id)
    if not profile or not profile.get("email"):
        _logger.info(f"[NOSHOW] {member_id}: no email on file, cannot re-outreach")
        return False

    gaps = get_member_open_gaps(member_id)
    if not gaps:
        _logger.info(f"[NOSHOW] {member_id}: no open gaps, skipping re-outreach")
        return False

    try:
        _send_analysis_email(
            member_id=member_id,
            name=profile.get("name", member_id),
            email=profile["email"],
            gaps=gaps,
            portal_url=get_portal_url(member_id),
            recommendation_text=(
                "Your previously booked screening appointment was not completed on the "
                "scheduled date. We've reopened your care gap — please pick a new "
                "appointment time using the link below."
            ),
            care_gap_text="",
        )
        return True
    except Exception as exc:
        _logger.error(f"[NOSHOW] re-outreach email failed for {member_id}: {exc}")
        return False


def run_noshow_sweep():
    """Main job: process all no-show appointments."""
    _logger.info("[NOSHOW] Starting daily no-show sweep")
    appointments = find_no_show_appointments()
    _logger.info(f"[NOSHOW] Found {len(appointments)} no-show appointment(s)")

    for row in appointments:
        member_id = row["member_id"]
        appt_id = row["appointment_id"]

        try:
            mark_appointment_no_show(appt_id)
            attempts = increment_retry(member_id)

            if attempts >= MAX_RETRIES:
                mark_unreachable(member_id)
                _logger.info(
                    f"[NOSHOW] {member_id}: reached {attempts} attempts, marked Unreachable"
                )
                continue

            sent = send_reoutreach_email(member_id)
            _logger.info(
                f"[NOSHOW] {member_id}: attempt {attempts}/{MAX_RETRIES}, "
                f"email_sent={sent}, appointment={appt_id}"
            )
        except Exception as exc:
            _logger.error(f"[NOSHOW] failed for {appt_id}: {exc}", exc_info=True)

    _logger.info("[NOSHOW] Sweep complete")


_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    """DISABLED — the daily no-show sweep auto-emails missed-appointment
    members, which is exactly the kind of recurring email we now want OFF
    to preserve the ACS daily quota. The data-only auto-cancel pass in
    outreach_scheduler.py continues to flip past-due appointments to
    Cancelled_NoShow, but no email is sent. Email sending is now limited
    to the bulk-upload Proceed-with-Outreach flow and the per-member
    Auto Process button.
    """
    _logger.info("[NOSHOW] Scheduler is DISABLED (auto recurring emails turned off)")
    return None


def trigger_now():
    """Manual trigger for testing."""
    run_noshow_sweep()
