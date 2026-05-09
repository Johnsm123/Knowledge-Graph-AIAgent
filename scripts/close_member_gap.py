"""
Manually close care gaps for a member who completed an appointment.

Replaces the old "Force Close" button. For demos: when the care manager
confirms a member finished their screening, run this script — it will
generate a claim, close the matching CareGap, mirror the closure into the
reference DB so the member-panel lifecycle visualization advances to "Gap
Closed", and recompute member compliance.

Usage:
    python scripts/close_member_gap.py M0042                # close every open gap
    python scripts/close_member_gap.py M0042 BCS           # close just BCS
    python scripts/close_member_gap.py --all               # close every open gap with a Completed appt
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime

# Make the repo root importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.neo4j_connection import get_knowledge_graph


def close_gap(member_id: str, measure_id: str | None = None) -> int:
    """Close care gaps for `member_id`.

    Behaviour:
      • If `measure_id` is given → close that one gap (must be open).
      • If `measure_id` is omitted → close ONLY gaps that have a non-Cancelled
        Appointment attached. Avoids accidentally closing every gap when the
        operator only intended to close the one they booked an appointment for.

    Idempotent:
      • Re-running for an already-closed gap is a no-op (no new claim).
      • If a claim already exists for the gap (g.claim_id is set), reuses it
        instead of creating a duplicate.

    Returns the number of gaps newly closed by this invocation.
    """
    kg = get_knowledge_graph()

    # Sweep orphan AUTO-CLM-* claims for this member: any auto-generated claim
    # whose claim_id isn't referenced by any CareGap.claim_id is leftover from
    # an earlier buggy run. Removes them so re-runs don't accumulate duplicates.
    orphan = kg.run_query("""
        MATCH (m:Member {member_id: $mid})-[:HAS_CLAIM]->(c:Claim)
        WHERE c.auto_generated = true
          AND NOT EXISTS { MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap) WHERE g.claim_id = c.claim_id }
        WITH c, count(c) AS cc DETACH DELETE c RETURN sum(cc) AS n
    """, {"mid": member_id})
    orphan_count = (orphan[0]["n"] if orphan else 0) or 0
    if orphan_count:
        print(f"[{member_id}] cleaned up {orphan_count} orphan auto-claim(s) from prior runs")

    if measure_id:
        cypher = """
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE coalesce(g.is_open, true) = true
              AND g.measure_id = $mea
            RETURN g.care_gap_id AS care_gap_id,
                   g.measure_id  AS measure_id,
                   g.measure_name AS measure_name,
                   g.primary_cpt_code AS primary_cpt,
                   g.primary_icd10    AS primary_icd,
                   g.claim_id          AS existing_claim_id
        """
        params = {"mid": member_id, "mea": measure_id}
    else:
        # No measure specified → only close gaps that the user booked an
        # appointment for. Prevents the script from sweeping unrelated gaps.
        cypher = """
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE coalesce(g.is_open, true) = true
            MATCH (m)-[:HAS_APPOINTMENT]->(a:Appointment)
            WHERE a.care_gap_id = g.care_gap_id
              AND coalesce(a.status,'Scheduled') IN ['Scheduled','Booked','Completed']
            RETURN DISTINCT g.care_gap_id AS care_gap_id,
                   g.measure_id  AS measure_id,
                   g.measure_name AS measure_name,
                   g.primary_cpt_code AS primary_cpt,
                   g.primary_icd10    AS primary_icd,
                   g.claim_id          AS existing_claim_id
        """
        params = {"mid": member_id}

    rows = kg.run_query(cypher, params) or []
    if not rows:
        if measure_id:
            print(f"[{member_id}] no open gap for {measure_id}")
        else:
            print(f"[{member_id}] no open gaps with a booked appointment "
                  "(use `python close_member_gap.py M0001 <MEASURE>` to close a specific gap)")
        return 0

    now = datetime.now().isoformat()
    today = datetime.now().date().isoformat()
    closed = 0
    for r in rows:
        cgid = r["care_gap_id"]
        mid_norm = r.get("measure_id") or "GEN"
        # Reuse existing claim id if one was previously stamped on the gap;
        # otherwise generate a new one. This stops re-runs from creating
        # duplicate claim rows for the same screening.
        claim_id = r.get("existing_claim_id") or f"AUTO-CLM-{member_id}-{mid_norm}-{uuid.uuid4().hex[:6]}"
        kg.run_query(
            """
            MATCH (m:Member {member_id: $mid})
            MERGE (c:Claim {claim_id: $cid})
            SET c.member_id    = $mid,
                c.measure_id   = $measure_id,
                c.cpt_code     = $cpt,
                c.icd_code     = $icd,
                c.service_date = $sdate,
                c.status       = 'Processed',
                c.created_on   = $now,
                c.auto_generated = true
            MERGE (m)-[:HAS_CLAIM]->(c)
            WITH m
            MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: $cgid})
            SET g.is_open = false,
                g.gap_status = 'Closed',
                g.closed_on  = $now,
                g.claim_id   = $cid
            """,
            {"mid": member_id, "cid": claim_id, "cgid": cgid,
             "measure_id": r.get("measure_id") or "",
             "cpt": r.get("primary_cpt") or "",
             "icd": r.get("primary_icd") or "",
             "sdate": today, "now": now},
        )
        # Flip the matching Appointment to Completed so the member panel's
        # Appointments tab + Booking Details modal stop showing a live timer.
        kg.run_query(
            """
            MATCH (m:Member {member_id: $mid})-[:HAS_APPOINTMENT]->(a:Appointment)
            WHERE a.care_gap_id = $cgid
              AND a.status IN ['Scheduled','Booked']
            SET a.status = 'Completed',
                a.completed_at = $now,
                a.claim_id = $cid
            """,
            {"mid": member_id, "cgid": cgid, "now": now, "cid": claim_id},
        )
        # Mark the matching Outreach record(s) as Completed so the dashboard
        # outreach completion-rate reflects the closure.
        kg.run_query(
            """
            MATCH (o:Outreach)-[:TARGETS]->(g:CareGap {care_gap_id: $cgid})
            SET o.status = 'Completed',
                o.completed_at = $now
            """,
            {"cgid": cgid, "now": now},
        )
        closed += 1
        print(f"[{member_id}] closed gap {cgid} ({r.get('measure_name') or r.get('measure_id')}) "
              f"with claim {claim_id}")
        # Mirror to reference DB so the lifecycle visualization advances.
        try:
            from src.persona_sync import sync_gap_closed
            sync_gap_closed(member_id, cgid)
        except Exception as e:
            print(f"  (reference-DB sync skipped: {e})")

    # Recompute compliance for this member.
    kg.run_query(
        """
        MATCH (m:Member {member_id: $mid})
        OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
        WHERE coalesce(g.is_open, true) = true
        WITH m, count(g) AS open_count
        SET m.health_status     = CASE WHEN open_count = 0 THEN 'Compliant' ELSE m.health_status END,
            m.compliance_score  = CASE WHEN open_count = 0 THEN 100.0 ELSE coalesce(m.compliance_score, 0.0) END
        """,
        {"mid": member_id},
    )

    # Notify a running Flask server (if any) so any open member panel
    # auto-refreshes without the user having to hit Refresh. Best-effort —
    # if the server isn't running, silently ignore.
    if closed:
        try:
            import urllib.request, json as _json
            req = urllib.request.Request(
                "http://127.0.0.1:5001/api/v1/admin/notify-gap-update",
                data=_json.dumps({"member_id": member_id, "source": "close_member_gap"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    return closed


def close_all_completed_appointments() -> int:
    """Close every open CareGap that has a Completed Appointment — same logic
    the in-app scheduler runs periodically, runnable on demand."""
    from src.outreach_scheduler import run_auto_close_completed
    n = run_auto_close_completed()
    print(f"closed {n} gap(s) across all members with Completed appointments")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("member_id", nargs="?", help="Member ID (e.g. M0042). Omit with --all.")
    ap.add_argument("measure_id", nargs="?", help="Optional measure_id (e.g. BCS) to close just one gap")
    ap.add_argument("--all", action="store_true",
                    help="Close every open gap that has a Completed appointment, across ALL members")
    args = ap.parse_args()

    if args.all:
        close_all_completed_appointments()
        return
    if not args.member_id:
        ap.print_help()
        sys.exit(1)
    close_gap(args.member_id, args.measure_id)


if __name__ == "__main__":
    main()
