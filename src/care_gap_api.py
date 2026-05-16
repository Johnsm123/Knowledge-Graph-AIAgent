"""
REST API endpoints for Care Gap workflows.
Run: python -m src.care_gap_api
"""
import json
import logging
import os
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
from flask_socketio import SocketIO, join_room

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Socket.IO async mode:
#   - "threading"  → works with the Flask/werkzeug dev server (`app.run`). Default for local dev.
#   - "gevent"     → required when serving via `gunicorn -k gevent wsgi:app` in production.
# Override via SOCKETIO_ASYNC_MODE env var in production deployments.
_SIO_ASYNC = os.environ.get("SOCKETIO_ASYNC_MODE", "threading")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=_SIO_ASYNC)
agent_system = None
logger = logging.getLogger(__name__)

# Background outreach reminder scheduler — auto-rebook nudges for missed
# appointments and a weekly reminder for members who never booked.
try:
    from src.outreach_scheduler import start_scheduler as _start_outreach_scheduler
    _start_outreach_scheduler()
except Exception as _sched_exc:
    logger.warning(f"Outreach scheduler not started: {_sched_exc}")


@socketio.on("join_portal")
def _on_join_portal(_data=None):
    """Portal clients join the 'portal' room to receive live updates."""
    join_room("portal")


def emit_portal_event(event: str, payload: dict):
    """Broadcast a real-time update to the web portal."""
    try:
        socketio.emit(event, payload, to="portal")
    except Exception as exc:
        logger.warning(f"[SOCKET] emit {event} failed: {exc}")


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
        # After bulk load, run hygiene so newly written gaps have canonical CPT/ICD
        try:
            from src.care_gap_cleanup import cleanup_all
            stats = cleanup_all()
            logger.info(f"[LOAD-DATA] post-load cleanup: {stats}")
        except Exception as exc:
            logger.warning(f"[LOAD-DATA] post-load cleanup skipped: {exc}")
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
        # Demo scope — same env-var convention used in detect_care_gaps and
        # get_member_open_gaps. When set (default 'BCS,CCS,COL'), out-of-scope
        # CareGap nodes are excluded from the per-member open-gap counts +
        # measure list so the dashboard tiles, pill counts, and measure
        # filter all stay consistent with the email/PDF/member panel.
        import os as _os_demo
        _enabled_raw_demo = _os_demo.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL").strip()
        _enabled_demo = None
        if _enabled_raw_demo not in ("*", "all", "ALL"):
            _enabled_demo = [m.strip().upper() for m in _enabled_raw_demo.split(",") if m.strip()]
        _demo_clause = "AND coalesce(g.measure_id, q.measure_id, '') IN $en" if _enabled_demo else ""
        _demo_params = {"en": _enabled_demo} if _enabled_demo else {}

        # Collect each member's open-gap measure_ids — mirror the same coalesce
        # logic used in dashboard/stats so we never drop a CareGap whose
        # measure_id lives on the related QualityMeasure node instead of the
        # gap itself. This list powers the dashboard's "Filter by Measure"
        # dropdown — picking GSD must surface every member who has GSD open,
        # even if they also have COL / BCS / etc. open at the same time.
        member_open_measures_rows = kg.run_query(f"""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            OPTIONAL MATCH (g)-[:RELATES_TO]->(q:QualityMeasure)
            WITH m.member_id AS member_id,
                 coalesce(g.measure_id, q.measure_id) AS measure_id
            WHERE measure_id IS NOT NULL
              {('AND measure_id IN $en' if _enabled_demo else '')}
            RETURN member_id, collect(DISTINCT measure_id) AS open_gap_measures
        """, _demo_params) or []
        open_measures_by_member = {
            row["member_id"]: row["open_gap_measures"] for row in member_open_measures_rows
        }

        members = kg.run_query(f"""
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            OPTIONAL MATCH (g)-[:RELATES_TO]->(q:QualityMeasure)
            WITH m, g, q,
                 // Scope-mask: gap counts towards open/closed only if its
                 // measure is in the enabled set (or no scope is set).
                 CASE
                   WHEN $en IS NULL THEN true
                   ELSE coalesce(g.measure_id, q.measure_id, '') IN $en
                 END AS in_scope
            WITH m,
                 count(DISTINCT CASE WHEN g.is_open = true  AND in_scope THEN g.care_gap_id ELSE null END) AS open_gaps,
                 count(DISTINCT CASE WHEN g.is_open = false AND in_scope THEN g.care_gap_id ELSE null END) AS closed_gaps
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
        """, {"en": _enabled_demo})

        for member in members:
            member["open_gap_measures"] = open_measures_by_member.get(member.get("member_id"), [])
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

        # Final demo-scope guard. Belt-and-suspenders — even if a future change
        # bypasses get_member_open_gaps, the response payload is still filtered
        # so AAP / KED / etc. never reach the member panel.
        import os as _os_demo
        _raw = _os_demo.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL").strip()
        if _raw not in ("*", "all", "ALL"):
            _en = {m.strip().upper() for m in _raw.split(",") if m.strip()}
            if _en:
                gaps        = [g for g in (gaps or [])        if (g.get("measure_id") or "").upper() in _en]
                closed_gaps = [g for g in (closed_gaps or []) if (g.get("measure_id") or "").upper() in _en]

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
    """Get dashboard statistics.

    Demo scope: members-with-gaps / compliant-members / total-open-gaps /
    outreach counts are filtered to the three cancer-screening measures
    we're demoing (BCS, CCS, COL). gaps_by_measure stays unscoped so the
    frontend can still inspect every measure if needed; analytics charts
    apply their own demo filter on the JS side.
    """
    try:
        kg = get_knowledge_graph()

        # Demo measure scope — when broadening the demo, just add measure
        # IDs to this list and the dashboard counters will follow.
        DEMO_MEASURES = ["BCS", "CCS", "COL"]

        # Total members
        total_members = kg.run_query("MATCH (m:Member) RETURN count(m) as count", {})[0]["count"]

        # Members with open gaps in the demo measure set
        members_with_gaps = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
              AND coalesce(g.measure_id, '') IN $demo
            RETURN count(DISTINCT m) as count
        """, {"demo": DEMO_MEASURES})[0]["count"]

        # Members without demo-scope gaps (compliant for the demo)
        compliant_members = total_members - members_with_gaps

        # Total open gaps — distinct (member, measure) pairs scoped to demo
        total_open_gaps = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
              AND coalesce(g.measure_id, '') IN $demo
            RETURN count(DISTINCT m.member_id + '|' + coalesce(g.measure_id, g.care_gap_id)) as count
        """, {"demo": DEMO_MEASURES})[0]["count"]

        # Gaps by measure — UNSCOPED. Frontend filters per-chart.
        gaps_by_measure = kg.run_query("""
            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.is_open = true
            OPTIONAL MATCH (g)-[:RELATES_TO]->(q:QualityMeasure)
            WITH coalesce(g.measure_id, q.measure_id, 'UNKNOWN') AS measure_id,
                 coalesce(q.name, g.measure_id, 'Unknown Measure')  AS measure_name,
                 m.member_id AS member_id,
                 g.created_on AS created_on
            RETURN measure_id, measure_name,
                   count(DISTINCT member_id) as gap_count,
                   collect(DISTINCT member_id)  AS member_ids,
                   min(created_on) AS earliest_created,
                   max(created_on) AS latest_created
            ORDER BY gap_count DESC
        """, {})

        # Outreach — count per outreach EVENT (one email send per member per
        # day), not per care gap. The merge_outreach() pipeline writes one
        # Outreach node per (member, gap) pair, so a single email targeting
        # 3 gaps creates 3 nodes. Collapsing to distinct (member_id, date)
        # gives the count care managers actually intuit ("how many outreach
        # touches happened?"). Requires the CareGap to still be attached to
        # a Member (orphan filter).
        recent_outreach_rows = kg.run_query("""
            MATCH (o:Outreach)-[:TARGETS]->(g:CareGap)<-[:HAS_CARE_GAP]-(m:Member)
            WHERE coalesce(g.measure_id, '') IN $demo
            // Group multiple per-gap rows into one event per (member, date)
            WITH m.member_id AS mid,
                 substring(coalesce(o.date, ''), 0, 10) AS day,
                 collect(o.status) AS statuses
            // An event is "Completed" iff EVERY constituent outreach is Completed.
            // It's "Scheduled" if any are still Scheduled (and not all Completed).
            WITH mid, day,
                 CASE WHEN ALL(s IN statuses WHERE s = 'Completed') THEN 'Completed'
                      WHEN ANY(s IN statuses WHERE s = 'Scheduled') THEN 'Scheduled'
                      ELSE 'Sent' END AS event_status
            RETURN count(*)                                                 AS total_outreach,
                   sum(CASE WHEN event_status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                   sum(CASE WHEN event_status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled
        """, {"demo": DEMO_MEASURES})
        recent_outreach = recent_outreach_rows[0] if recent_outreach_rows else {
            "total_outreach": 0, "completed": 0, "scheduled": 0,
        }
        
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


@app.route("/api/v1/admin/cleanup-care-gaps", methods=["POST"])
def admin_cleanup_care_gaps():
    """Backfill primary CPT/ICD on every CareGap + delete duplicate (member, measure) gaps.

    Idempotent. Run after data fixes or whenever care-gap fields look inconsistent.
    Result includes counts of what was fixed.
    """
    try:
        from src.care_gap_cleanup import cleanup_all
        stats = cleanup_all()
        # Notify any open portal sessions to refresh
        try:
            emit_portal_event("care_gap_updated", {"source": "admin_cleanup", "stats": stats})
        except Exception:
            pass
        return jsonify({"status": "ok", "stats": stats})
    except Exception as exc:
        logger.error(f"admin_cleanup_care_gaps error: {exc}", exc_info=True)
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route("/api/v1/admin/audit-buggy-members", methods=["GET"])
def admin_audit_buggy_members():
    """List members with multi-CPT/ICD codes per gap, missing codes, or duplicate gaps.

    NON-DESTRUCTIVE. Use this to preview what /admin/purge-buggy-members would delete.
    """
    try:
        from src.care_gap_cleanup import find_buggy_members
        buggy = find_buggy_members()
        return jsonify({
            "status": "ok",
            "count": len(buggy),
            "members": buggy,
        })
    except Exception as exc:
        logger.error(f"admin_audit_buggy_members error: {exc}", exc_info=True)
        return jsonify({"status": "error", "error": str(exc)}), 500


@app.route("/api/v1/admin/purge-buggy-members", methods=["POST"])
def admin_purge_buggy_members():
    """Permanently delete members whose CareGap data is buggy from main + reference DBs.

    Required body:  {"confirm": "DELETE"}
    Optional query: ?dry_run=true   → audit only, no deletion (default false here)
    """
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "DELETE":
        return jsonify({
            "status": "error",
            "error": "Destructive op — POST body must include {\"confirm\": \"DELETE\"}",
        }), 400

    dry_run = (request.args.get("dry_run", "false").lower() == "true")
    try:
        from src.care_gap_cleanup import purge_buggy_members
        result = purge_buggy_members(dry_run=dry_run)
        if not dry_run and result.get("deleted"):
            try:
                emit_portal_event("members_purged", {
                    "deleted_count": len(result["deleted"]),
                    "deleted_ids": [d.get("member_id") for d in result["deleted"]],
                })
            except Exception:
                pass
        return jsonify({"status": "ok", **result})
    except Exception as exc:
        logger.error(f"admin_purge_buggy_members error: {exc}", exc_info=True)
        return jsonify({"status": "error", "error": str(exc)}), 500


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

        # Push a real-time event so any open member panel auto-refreshes
        # without a manual reload after the appointment is booked.
        try:
            emit_portal_event("appointment_booked", {
                "member_id": member_id,
                "care_gap_id": care_gap_id,
                "measure_id": measure_id,
                "appointment_id": appointment_id,
            })
            emit_portal_event("care_gap_updated", {
                "member_id": member_id,
                "source": "appointment_booked",
            })
        except Exception:
            pass

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
    """Delete a member and all their relationships from every DB the project
    writes to: main DB, reference (persona-sync) DB, and persona-demo DB.
    Each is best-effort — failure to reach the persona/reference DBs must not
    block the primary deletion in the main DB.
    """
    try:
        kg = get_knowledge_graph()
        # Check member exists in main DB
        exists = kg.run_query(
            "MATCH (m:Member {member_id: $mid}) RETURN m.name as name",
            {"mid": member_id},
        )
        if not exists:
            return jsonify({"status": "error", "error": f"Member {member_id} not found"}), 404

        member_name = exists[0]["name"]

        # 1. Main DB — full member subgraph (claims, gaps, lifestyle,
        #    family-history, medical-history, appointments, outreach…)
        kg.run_query(
            """
            MATCH (m:Member {member_id: $mid})
            OPTIONAL MATCH (m)-[:HAS_LIFESTYLE]->(l:Lifestyle)
            OPTIONAL MATCH (m)-[:HAS_RELATIVE]->(fm:FamilyMember)
            OPTIONAL MATCH (m)-[:HAS_MEDICAL_HISTORY]->(mh:MedicalHistoryEntry)
            OPTIONAL MATCH (m)-[:HAS_CLAIM]->(c:Claim)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            OPTIONAL MATCH (m)-[:HAS_APPOINTMENT]->(a:Appointment)
            OPTIONAL MATCH (o:Outreach)-[:CONTACTS]->(m)
            DETACH DELETE l, fm, mh, c, g, a, o, m
            """,
            {"mid": member_id},
        )

        deleted_from = ["main"]

        # 2. Reference DB (persona_sync) — same member_id may exist there
        try:
            from src.neo4j_connection import get_reference_graph
            ref = get_reference_graph()
            if ref is not None:
                # Delete the Member and member-owned subgraph, but keep the
                # Persona node intact (personas are shared / re-usable).
                ref.run_query(
                    """
                    MATCH (m:Member {member_id: $mid})
                    OPTIONAL MATCH (m)-[:HAS_LIFESTYLE]->(l:Lifestyle)
                    OPTIONAL MATCH (m)-[:HAS_RELATIVE]->(fm:FamilyMember)
                    OPTIONAL MATCH (m)-[:HAS_MEDICAL_HISTORY]->(mh:MedicalHistoryEntry)
                    OPTIONAL MATCH (m)-[:HAS_CARE_GAP|HAS_GAP]->(g:CareGap)
                    OPTIONAL MATCH (g)-[:HAS_ACTION]->(act:Action)
                    DETACH DELETE act, g, l, fm, mh, m
                    """,
                    {"mid": member_id},
                )
                deleted_from.append("reference")
        except Exception as ref_exc:
            logger.warning(f"Reference-DB delete skipped for {member_id}: {ref_exc}")

        # 3. Persona-demo DB — clean up Member + IdealPersona twin
        try:
            from src.persona_demo_writer import _get_driver as _get_persona_driver
            pd_driver = _get_persona_driver()
            if pd_driver is not None:
                with pd_driver.session() as s:
                    # Delete Member + member-owned nodes (Lifestyle,
                    # FamilyMember, MedicalHistoryEntry). Keep IdealPersona
                    # and Screening nodes — they are shared/re-usable.
                    s.run(
                        """
                        MATCH (m:Member {member_id: $mid})
                        OPTIONAL MATCH (m)-[:HAS_LIFESTYLE]->(l:Lifestyle)
                        OPTIONAL MATCH (m)-[:HAS_RELATIVE]->(fm:FamilyMember)
                        OPTIONAL MATCH (m)-[:HAS_MEDICAL_HISTORY]->(mh:MedicalHistoryEntry)
                        DETACH DELETE l, fm, mh, m
                        """,
                        {"mid": member_id},
                    ).consume()
                deleted_from.append("persona-demo")
        except Exception as pd_exc:
            logger.warning(f"Persona-demo delete skipped for {member_id}: {pd_exc}")

        return jsonify({
            "status": "success",
            "message": f"Member {member_name} ({member_id}) deleted successfully",
            "deleted_from": deleted_from,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/care-gaps/auto-close-completed", methods=["POST"])
def auto_close_completed_appointments():
    """Backend automation that replaces the per-card "Force Close" button:
    for every appointment marked Completed whose underlying CareGap is still
    open, generate a Claim, close the CareGap, and recompute member
    compliance. If a member's open-gap count reaches zero the member is
    flagged compliant. Runs across the whole member roster — safe to call
    repeatedly (idempotent on already-closed gaps).
    """
    try:
        kg = get_knowledge_graph()
        # MATCH (not OPTIONAL MATCH) — closed gaps must NOT emit a row, or
        # the loop below would mint a new AUTO-CLM-* claim every call. Also
        # require g.claim_id to be empty so re-runs are true no-ops.
        rows = kg.run_query(
            """
            MATCH (m:Member)-[:HAS_APPOINTMENT]->(a:Appointment)
            WHERE a.status = 'Completed'
            MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: a.care_gap_id})
            WHERE coalesce(g.is_open, true) = true
              AND (g.claim_id IS NULL OR g.claim_id = '')
            RETURN m.member_id          AS member_id,
                   a.appointment_id     AS appointment_id,
                   a.care_gap_id        AS care_gap_id,
                   coalesce(a.measure_id, g.measure_id) AS measure_id,
                   a.cpt_codes          AS cpt_codes,
                   a.icd_codes          AS icd_codes,
                   a.appointment_date   AS appointment_date
            """, {}
        ) or []

        from datetime import datetime as _dt
        import uuid as _uuid
        closed = 0
        compliant_now = []
        for r in rows:
            mid  = r.get("member_id"); cgid = r.get("care_gap_id")
            if not (mid and cgid):
                continue
            claim_id = f"AUTO-CLM-{mid}-{(r.get('measure_id') or 'GEN')}-{_uuid.uuid4().hex[:6]}"
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
                WITH c, m
                MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: $cgid})
                SET g.is_open    = false,
                    g.gap_status = 'Closed',
                    g.closed_on  = $now,
                    g.claim_id   = $cid
                """,
                {"mid": mid, "cid": claim_id, "cgid": cgid,
                 "measure_id": r.get("measure_id") or "",
                 "cpt": r.get("cpt_codes") or "",
                 "icd": r.get("icd_codes") or "",
                 "sdate": r.get("appointment_date") or _dt.now().date().isoformat(),
                 "now":   _dt.now().isoformat()},
            )
            # Mirror appointment status so the member-panel timer stops.
            kg.run_query(
                """
                MATCH (m:Member {member_id: $mid})-[:HAS_APPOINTMENT]->(a:Appointment)
                WHERE a.care_gap_id = $cgid AND a.status IN ['Scheduled','Booked']
                SET a.status = 'Completed', a.completed_at = $now, a.claim_id = $cid
                """,
                {"mid": mid, "cgid": cgid, "now": _dt.now().isoformat(), "cid": claim_id},
            )
            closed += 1

            # Persona-sync: mirror the closure into the reference DB so the
            # member-panel lifecycle visualization updates automatically.
            try:
                from src.persona_sync import sync_gap_closed
                sync_gap_closed(mid, cgid)
            except Exception:
                pass

        # Recompute compliance per member.
        compliance_rows = kg.run_query(
            """
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE coalesce(g.is_open, true) = true
            WITH m, count(g) AS open_count
            SET m.health_status = CASE WHEN open_count = 0 THEN 'Compliant' ELSE m.health_status END,
                m.compliance_score = CASE WHEN open_count = 0 THEN 100.0 ELSE coalesce(m.compliance_score, 0.0) END
            RETURN m.member_id AS member_id, open_count
            """, {}
        ) or []
        compliant_now = [r["member_id"] for r in compliance_rows if r.get("open_count") == 0]

        return jsonify({
            "status": "success",
            "gaps_closed": closed,
            "members_now_compliant": compliant_now,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/outreach/run-rebook-reminders", methods=["POST"])
def run_rebook_reminders_endpoint():
    """Manually trigger the rebook-reminder pass (also runs hourly in the
    background). Useful for demos and ops verification."""
    try:
        from src.outreach_scheduler import run_rebook_reminders
        sent = run_rebook_reminders()
        return jsonify({"status": "success", "emails_sent": sent})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/outreach/run-weekly-reminders", methods=["POST"])
def run_weekly_reminders_endpoint():
    """Manually trigger the weekly-reminder pass (also runs daily in the
    background). Useful for demos and ops verification."""
    try:
        from src.outreach_scheduler import run_weekly_reminders
        sent = run_weekly_reminders()
        return jsonify({"status": "success", "emails_sent": sent})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/providers/list", methods=["GET"])
def get_providers():
    """Get all providers for dropdown selection. Each provider includes the
    list of members they're the PCP for, so the frontend explorer can show
    related members when a provider is selected without a second round-trip.
    """
    try:
        kg = get_knowledge_graph()
        # Two simple queries, joined in Python — keeps Cypher straightforward
        # and survives providers with empty rosters.
        providers = kg.run_query("""
            MATCH (p:Provider)
            RETURN p.provider_id   AS provider_id,
                   p.name          AS name,
                   p.specialty     AS specialty,
                   p.network_status AS network_status
            ORDER BY p.name
        """, {}) or []

        # Roster via :ASSIGNED_TO relationship
        rel_rows = kg.run_query("""
            MATCH (m:Member)-[:ASSIGNED_TO]->(p:Provider)
            RETURN p.provider_id AS provider_id,
                   m.member_id   AS member_id,
                   m.name        AS name,
                   m.age_str     AS age_str,
                   m.gender      AS gender
        """, {}) or []
        # Roster via pcp_id property (fallback for members not linked via relationship)
        prop_rows = kg.run_query("""
            MATCH (m:Member) WHERE m.pcp_id IS NOT NULL AND m.pcp_id <> ''
            RETURN m.pcp_id    AS provider_id,
                   m.member_id AS member_id,
                   m.name      AS name,
                   m.age_str   AS age_str,
                   m.gender    AS gender
        """, {}) or []

        roster_by_pid: dict = {}
        for r in rel_rows + prop_rows:
            pid = r.get("provider_id")
            mid = r.get("member_id")
            if not pid or not mid:
                continue
            seen = roster_by_pid.setdefault(pid, {})
            if mid not in seen:
                seen[mid] = {
                    "member_id": mid,
                    "name":      r.get("name", ""),
                    "age_str":   r.get("age_str", ""),
                    "gender":    r.get("gender", ""),
                }

        for p in providers:
            p["members"] = list(roster_by_pid.get(p.get("provider_id"), {}).values())
        return jsonify({"providers": providers})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/dashboard/main-graph", methods=["GET"])
def dashboard_main_graph():
    """Return the main knowledge graph in three pre-built shapes — one per
    Knowledge-Explorer filter tab. The frontend renders the active subgraph
    in a Neo4j-style force layout and filters it down to a single node + its
    neighborhood when the user clicks a node.

    Each subgraph has the form: { nodes: [{id, label, name, props}], edges: [{source, target, type}] }.
    """
    try:
        from src.hedis_golden_reference import HEDIS_MEASURES
        kg = get_knowledge_graph()

        # ── 1. MEMBERS graph: Member → CareGap → QualityMeasure  +  Member → Provider
        members_rows = kg.run_query("""
            MATCH (m:Member)
            OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            WHERE coalesce(g.is_open, true) = true
            WITH m,
                 collect(DISTINCT q.measure_id) AS measure_ids,
                 collect(DISTINCT {gid: g.care_gap_id, mid: q.measure_id}) AS gaps
            OPTIONAL MATCH (p:Provider {provider_id: m.pcp_id})
            RETURN m.member_id   AS member_id,
                   m.name        AS name,
                   m.gender      AS gender,
                   m.age_str     AS age_str,
                   m.pcp_id      AS pcp_id,
                   p.name        AS pcp_name,
                   [x IN measure_ids WHERE x IS NOT NULL] AS measure_ids,
                   [x IN gaps WHERE x.gid IS NOT NULL]    AS gaps
        """, {}) or []

        m_nodes, m_edges = [], []
        seen_measure_ids = set()
        seen_provider_ids = set()
        for r in members_rows:
            mid = r["member_id"]
            m_nodes.append({
                "id":    f"M:{mid}",
                "label": "Member",
                "name":  f"{mid} — {r.get('name','')}",
                "props": {
                    "Member ID": mid,
                    "Name":      r.get("name", ""),
                    "Gender":    r.get("gender", ""),
                    "Age":       r.get("age_str", ""),
                    "PCP":       r.get("pcp_name", "") or r.get("pcp_id", ""),
                },
            })
            # link to PCP if any
            if r.get("pcp_id"):
                pid = r["pcp_id"]
                if pid not in seen_provider_ids:
                    m_nodes.append({
                        "id":    f"P:{pid}",
                        "label": "Provider",
                        "name":  r.get("pcp_name", pid),
                        "props": {"Provider ID": pid, "Name": r.get("pcp_name", "") or pid},
                    })
                    seen_provider_ids.add(pid)
                m_edges.append({"source": f"M:{mid}", "target": f"P:{pid}", "type": "HAS_PCP"})
            # link to each open-gap measure
            for measure_id in r.get("measure_ids", []) or []:
                if not measure_id:
                    continue
                if measure_id not in seen_measure_ids:
                    md = HEDIS_MEASURES.get(measure_id, {})
                    m_nodes.append({
                        "id":    f"Q:{measure_id}",
                        "label": "Measure",
                        "name":  f"{measure_id} · {md.get('name', measure_id)}",
                        "props": {"Measure ID": measure_id, "Name": md.get("name", "")},
                    })
                    seen_measure_ids.add(measure_id)
                m_edges.append({"source": f"M:{mid}", "target": f"Q:{measure_id}", "type": "OPEN_GAP"})

        # ── 2. PROVIDERS graph: Provider → Member  (full roster)
        # Members are linked to providers via either an :ASSIGNED_TO relationship
        # OR by storing pcp_id as a property; we union both in Python so we
        # don't lose providers with empty rosters and we keep Cypher simple.
        prov_rows = kg.run_query("""
            MATCH (p:Provider)
            RETURN p.provider_id   AS provider_id,
                   p.name          AS name,
                   p.specialty     AS specialty,
                   p.network_status AS network_status
            ORDER BY p.name
        """, {}) or []
        rel_link_rows = kg.run_query("""
            MATCH (m:Member)-[:ASSIGNED_TO]->(p:Provider)
            RETURN p.provider_id AS pid, m.member_id AS member_id,
                   m.name AS name, m.age_str AS age_str, m.gender AS gender
        """, {}) or []
        prop_link_rows = kg.run_query("""
            MATCH (m:Member) WHERE m.pcp_id IS NOT NULL AND m.pcp_id <> ''
            RETURN m.pcp_id AS pid, m.member_id AS member_id,
                   m.name AS name, m.age_str AS age_str, m.gender AS gender
        """, {}) or []
        roster_by_pid: dict = {}
        for r in rel_link_rows + prop_link_rows:
            pid = r.get("pid"); mid = r.get("member_id")
            if not pid or not mid:
                continue
            roster_by_pid.setdefault(pid, {})
            roster_by_pid[pid].setdefault(mid, {
                "member_id": mid, "name": r.get("name", ""),
                "age_str":   r.get("age_str", ""),
                "gender":    r.get("gender", ""),
            })
        # Re-shape to the same schema the rest of the function expects
        for r in prov_rows:
            r["roster"] = list(roster_by_pid.get(r.get("provider_id"), {}).values())

        p_nodes, p_edges = [], []
        seen_member_in_prov = set()
        for r in prov_rows:
            pid = r["provider_id"]
            p_nodes.append({
                "id":    f"P:{pid}",
                "label": "Provider",
                "name":  f"{pid} — {r.get('name','')}",
                "props": {
                    "Provider ID":    pid,
                    "Name":           r.get("name", ""),
                    "Specialty":      r.get("specialty", "") or "—",
                    "Network status": r.get("network_status", "") or "—",
                    "Members":        len(r.get("roster", []) or []),
                },
            })
            for m in (r.get("roster") or []):
                mid = m["member_id"]
                if mid not in seen_member_in_prov:
                    p_nodes.append({
                        "id":    f"M:{mid}",
                        "label": "Member",
                        "name":  f"{mid} — {m.get('name','')}",
                        "props": {
                            "Member ID": mid,
                            "Name":      m.get("name", ""),
                            "Gender":    m.get("gender", ""),
                            "Age":       m.get("age_str", ""),
                        },
                    })
                    seen_member_in_prov.add(mid)
                p_edges.append({"source": f"P:{pid}", "target": f"M:{mid}", "type": "HAS_MEMBER"})

        # ── 3. MEASURES graph: Measure → AgeRange / Gender / CPT / ICD / Lookback / Exclusion
        q_nodes, q_edges = [], []
        for mid, md in HEDIS_MEASURES.items():
            q_nodes.append({
                "id":    f"Q:{mid}",
                "label": "Measure",
                "name":  f"{mid} · {md.get('name', mid)}",
                "props": {
                    "Measure ID":  mid,
                    "Name":        md.get("name", ""),
                    "Description": (md.get("description", "") or "")[:240],
                },
            })
            # Age criteria leaf
            ar = md.get("age_range", "")
            if ar:
                aid = f"AGE:{mid}"
                q_nodes.append({"id": aid, "label": "AgeRange", "name": ar, "props": {"Age range": ar}})
                q_edges.append({"source": f"Q:{mid}", "target": aid, "type": "AGE"})
            # Gender leaf
            gen = md.get("gender_requirement", "Any")
            if gen and gen != "Any":
                gid = f"GEN:{mid}"
                q_nodes.append({"id": gid, "label": "Gender", "name": gen, "props": {"Gender requirement": gen}})
                q_edges.append({"source": f"Q:{mid}", "target": gid, "type": "GENDER"})
            # Lookback leaf
            lb = md.get("lookback_months")
            if lb:
                lbid = f"LB:{mid}"
                q_nodes.append({"id": lbid, "label": "Lookback", "name": f"{lb} months", "props": {"Lookback (months)": lb, "Description": md.get("lookback_description", "")}})
                q_edges.append({"source": f"Q:{mid}", "target": lbid, "type": "LOOKBACK"})
            # Primary CPT leaf
            cpt = md.get("primary_cpt", "")
            if cpt:
                cid = f"CPT:{mid}"
                q_nodes.append({"id": cid, "label": "CPT", "name": cpt, "props": {"Primary CPT": cpt}})
                q_edges.append({"source": f"Q:{mid}", "target": cid, "type": "PRIMARY_CPT"})
            # Primary ICD leaf
            icd = md.get("primary_icd10", "")
            if icd:
                iid = f"ICD:{mid}"
                q_nodes.append({"id": iid, "label": "ICD", "name": icd, "props": {"Primary ICD-10": icd}})
                q_edges.append({"source": f"Q:{mid}", "target": iid, "type": "PRIMARY_ICD"})
            # Diagnosis prerequisite leaf — labelled "Disease" so the
            # Knowledge Explorer legend reads in plain clinical language.
            diag = md.get("diagnosis_requirement", "")
            if diag:
                did = f"DIAG:{mid}"
                q_nodes.append({"id": did, "label": "Disease", "name": diag[:48], "props": {"Disease": diag}})
                q_edges.append({"source": f"Q:{mid}", "target": did, "type": "DIAGNOSIS_REQ"})
            # Exclusion leaves intentionally omitted — Knowledge Explorer keeps
            # the Measure subgraph focused on positive criteria; the operational
            # exclusion rules are still applied by the rules engine.

        return jsonify({
            "members_graph":   {"nodes": m_nodes, "edges": m_edges},
            "providers_graph": {"nodes": p_nodes, "edges": p_edges},
            "measures_graph":  {"nodes": q_nodes, "edges": q_edges},
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/measures/list", methods=["GET"])
def list_measures():
    """Return all HEDIS measures with their rulebook metadata.

    Frontend uses this to power the Quality Measure filter in the Knowledge
    Explorer — selecting a measure shows its age range, gender, exclusions,
    primary CPT/ICD, lookback window, and description.
    """
    try:
        from src.hedis_golden_reference import HEDIS_MEASURES
        out = []
        for mid, m in HEDIS_MEASURES.items():
            exclusions = []
            for ex in (m.get("exclusions", {}) or {}).get("required", []) or []:
                exclusions.append({
                    "type":        ex.get("type", ""),
                    "description": ex.get("description", ""),
                    "icd10":       ex.get("icd10", []) or [],
                    "cpt":         ex.get("cpt", []) or [],
                })
            out.append({
                "measure_id":            mid,
                "name":                  m.get("name", ""),
                "description":           m.get("description", ""),
                "age_range":             m.get("age_range", ""),
                "min_age":               m.get("min_age"),
                "max_age":               m.get("max_age"),
                "gender_requirement":    m.get("gender_requirement", "Any"),
                "diagnosis_requirement": m.get("diagnosis_requirement", ""),
                "lookback_months":       m.get("lookback_months"),
                "lookback_description":  m.get("lookback_description", ""),
                "primary_cpt":           m.get("primary_cpt", ""),
                "primary_icd10":         m.get("primary_icd10", ""),
                "numerator_criteria":    m.get("numerator_criteria", ""),
                "denominator_criteria":  m.get("denominator_criteria", ""),
                "screening_options":     m.get("screening_options", []) or [],
                "exclusions":            exclusions,
                "product_lines":         m.get("product_lines", []) or [],
            })
        return jsonify({"measures": out, "count": len(out)})
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
            # Also captured into prior_screenings_map so we can later mark the
            # corresponding measures as Closed gaps in the reference + persona-demo
            # DBs with the actual screening date — keeping the visualization in
            # exact sync with what the golden rulebook decides about compliance.
            prior_screenings_map: dict = {}
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
                    prior_screenings_map[mid_part] = svc_date
                    logger.info(f"[BULK] Prior screening claim created: {claim_id} ({mid_part} on {svc_date})")

            # Detect care gaps (pure Python — fast)
            gap_result = detect_care_gaps(member_id)
            open_gaps = get_member_open_gaps(member_id)
            profile = get_member_profile(member_id)

            # Build the "completed" list once — every measure the rulebook
            # marked compliant becomes a closed gap in ref DB + a completed
            # screening on the persona-demo twin. Service date comes from
            # the Excel PriorScreenings column when present, otherwise from
            # the most recent matching claim.
            from src.hedis_golden_reference import HEDIS_MEASURES as _HM
            from src.persona_sync import _find_screening_date_from_claims
            from src.care_gap_neo4j import get_member_claims_cpt_codes as _gccc
            _claims_for_dates = _gccc(member_id) or []
            completed_measures = []
            for _cmid in (gap_result.get("compliant") or []):
                _mdef = _HM.get(_cmid) or {}
                _mname = _mdef.get("name", _cmid)
                _sdate = (
                    prior_screenings_map.get(_cmid)
                    or _find_screening_date_from_claims(_mdef, _claims_for_dates)
                )
                completed_measures.append({
                    "measure_id":       _cmid,
                    "measure_name":     _mname,
                    "primary_cpt_code": _mdef.get("primary_cpt", ""),
                    "primary_icd10":    _mdef.get("primary_icd10", ""),
                    "service_date":     _sdate,
                })

            # ── Sync persona to reference DB for visualization ──────
            try:
                from src.persona_sync import (
                    sync_member_persona, sync_care_gap, reset_member_care_gaps,
                    sync_compliant_measure,
                )
                # Wipe any stale CareGap nodes left from a previous upload of
                # this member so the reference DB ends up mirroring exactly the
                # open + closed gaps the rulebook just decided — no extras.
                reset_member_care_gaps(member_id)
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
                # Closed gaps for prior-screening / already-compliant measures.
                for _cm in completed_measures:
                    sync_compliant_measure(
                        member_id=member_id,
                        measure_id=_cm["measure_id"],
                        measure_name=_cm["measure_name"],
                        screening_date=_cm.get("service_date", ""),
                    )
            except Exception as ps_err:
                logger.warning(f"Persona sync failed for {member_id}: {ps_err}")

            # ── Persona reasoning: LLM-generated 'why this persona matches' ──
            # Same flow as care-gap reason analysis but for the Persona node;
            # the tooltip on the Persona node in the lifecycle graph displays it.
            try:
                from src.persona_reason import generate_persona_reason
                from src.persona_sync import set_persona_reasoning
                from src.care_gap_neo4j import (
                    get_member_family_history as _gfh_pr,
                    get_member_medical_history as _gmh_pr,
                    get_member_lifestyle      as _gls_pr,
                )
                _profile_pr = profile or {"member_id": member_id, "name": name}
                _profile_pr["member_id"] = member_id
                _persona_reasoning = generate_persona_reason(
                    member=_profile_pr,
                    open_gaps=open_gaps,
                    family_history=_gfh_pr(member_id) or [],
                    medical_history=_gmh_pr(member_id) or {},
                    lifestyle=_gls_pr(member_id) or {},
                )
                set_persona_reasoning(member_id, _persona_reasoning)
            except Exception as pr_err:
                logger.warning(f"Persona reasoning failed for {member_id}: {pr_err}")

            # ── Persona-Demo DB: write Member + IdealPersona relationship ──
            # Happens during INITIAL bulk upload (not after outreach), so the
            # persona DB stays in sync with what's in main + reference DBs.
            try:
                from src.persona_demo_writer import (
                    build_persona_comparison as _bpc,
                    push_member_persona as _ppm,
                )
                from src.care_gap_neo4j import (
                    get_member_family_history as _gfh,
                    get_member_medical_history as _gmh,
                    get_member_lifestyle as _gls,
                )
                _profile_pd = profile or {"member_id": member_id, "name": name}
                _profile_pd["member_id"] = member_id
                _cmp = _bpc(
                    _profile_pd,
                    open_gaps,
                    completed=completed_measures,
                    family_history=_gfh(member_id) or [],
                    medical_history=_gmh(member_id) or {},
                    lifestyle=_gls(member_id) or {},
                )
                _ppm(_profile_pd, _cmp)
            except Exception as pd_err:
                logger.warning(f"Persona-demo write failed for {member_id}: {pd_err}")

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

    # After bulk upload, run hygiene so every newly created CareGap has
    # canonical primary CPT/ICD codes from the golden reference.
    try:
        from src.care_gap_cleanup import cleanup_all
        cleanup_stats = cleanup_all()
        logger.info(f"[BULK-UPLOAD] post-upload cleanup: {cleanup_stats}")
    except Exception as exc:
        logger.warning(f"[BULK-UPLOAD] post-upload cleanup skipped: {exc}")

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
            email_error_msg = ""
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
                    email_error_msg = str(email_err)[:200]

            # Persona-comparison side-effect — mirror member + ideal twin into
            # the persona-demo DB so the upload page can animate the
            # persona-vs-member comparison in real time. Best-effort: if the
            # persona DB is unreachable we still complete the main flow.
            persona_comparison = None
            try:
                from src.persona_demo_writer import build_persona_comparison, push_member_persona
                from src.care_gap_neo4j import get_member_profile as _get_profile_p
                from src.care_gap_neo4j import get_member_open_gaps as _get_open_p
                from src.care_gap_neo4j import (
                    get_member_family_history as _get_family_p,
                    get_member_medical_history as _get_medical_p,
                    get_member_lifestyle as _get_lifestyle_p,
                )
                _profile_p = _get_profile_p(mid) or {"member_id": mid, "name": mname}
                _profile_p["member_id"] = mid
                _open_p = _get_open_p(mid) or []
                _family_p  = _get_family_p(mid) or []
                _medical_p = _get_medical_p(mid) or {}
                _lifestyle_p = _get_lifestyle_p(mid) or {}
                persona_comparison = build_persona_comparison(
                    _profile_p, _open_p,
                    completed=[],
                    family_history=_family_p,
                    medical_history=_medical_p,
                    lifestyle=_lifestyle_p,
                )
                push_member_persona(_profile_p, persona_comparison)
            except Exception as p_exc:
                logger.warning(f"Persona-demo push failed for {mid}: {p_exc}")

            with lock:
                processing_results[mid] = {
                    "member_id": mid,
                    "name": mname,
                    "status": "completed",
                    "email_sent": email_sent,
                    "email_error": email_error_msg,
                    "analysis_summary": str(analysis.get("summary", ""))[:500] if isinstance(analysis, dict) else str(analysis)[:500],
                    "persona_comparison": persona_comparison,
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


@app.route("/api/v1/members/bulk-preview-persona", methods=["POST"])
def bulk_preview_persona():
    """Persona-based care-gap discovery for the bulk-upload PREVIEW step.
    Decoupled from outreach: runs rules-engine + persona-demo writer per
    member, returns the comparison summaries the bulk-upload UI animates.
    No emails, no Outreach nodes, no claim generation.
    """
    data = request.json or {}
    member_list = data.get("members", [])
    if not member_list:
        return jsonify({"status": "error", "error": "No members provided"}), 400
    results = []
    try:
        from src.persona_demo_writer import build_persona_comparison, push_member_persona
        from src.care_gap_neo4j import (
            get_member_profile as _get_profile,
            get_member_open_gaps as _get_open,
            get_member_family_history as _get_family,
            get_member_medical_history as _get_medical,
            get_member_lifestyle as _get_lifestyle,
        )
        from src.care_gap_reason import generate_reasons_for_member
        from src.persona_match_reason import generate_persona_match_bullets
        for m in member_list:
            mid = m.get("member_id")
            if not mid:
                continue
            try:
                profile = _get_profile(mid) or {"member_id": mid, "name": m.get("name", mid)}
                profile["member_id"] = mid
                family   = _get_family(mid) or []
                medical  = _get_medical(mid) or {}
                lifestyle = _get_lifestyle(mid) or {}
                open_gaps = _get_open(mid) or []
                cmp = build_persona_comparison(
                    profile,
                    open_gaps,
                    completed=[],
                    family_history=family,
                    medical_history=medical,
                    lifestyle=lifestyle,
                )
                # Generate one LLM reason per pending screening so the bulk-
                # upload UI can show them on hover. Runs in parallel across
                # measures; falls back to a rulebook-derived sentence on
                # any per-measure failure.
                try:
                    pending_ids = [p.get("measure_id") for p in (cmp.get("pending_screenings") or []) if p.get("measure_id")]
                    reason_map = generate_reasons_for_member(
                        member=profile,
                        pending_measure_ids=pending_ids,
                        family_history=family,
                        medical_history=medical,
                        lifestyle=lifestyle,
                    )
                    for p in (cmp.get("pending_screenings") or []):
                        rid = p.get("measure_id")
                        if rid and reason_map.get(rid):
                            p["reason"] = reason_map[rid]
                except Exception as r_err:
                    logger.warning(f"[BULK-PREVIEW] reason generation failed for {mid}: {r_err}")

                # Persona-match analysis bullets — shown on hover of the
                # green IDEAL persona node in the preview graph.
                try:
                    cmp["persona_match_bullets"] = generate_persona_match_bullets(
                        member=profile,
                        pending=cmp.get("pending_screenings") or [],
                        family_history=family,
                        medical_history=medical,
                        lifestyle=lifestyle,
                    )
                except Exception as pmr_err:
                    logger.warning(f"[BULK-PREVIEW] persona-match bullets failed for {mid}: {pmr_err}")
                    cmp["persona_match_bullets"] = []

                push_member_persona(profile, cmp)
                results.append({"status": "ok", "member_id": mid, "name": m.get("name", mid),
                                "email": m.get("email", ""), "persona_comparison": cmp})
            except Exception as one_exc:
                results.append({"status": "error", "member_id": mid,
                                "name": m.get("name", mid), "error": str(one_exc)})
        return jsonify({"status": "success", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


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
.modal{background:#fff;border-radius:0;width:97%;max-width:1500px;height:95vh;max-height:95vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 8px 48px rgba(0,0,72,0.2)}
.modal-header{background:#000048;color:#fff;padding:18px 28px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
.modal-header h2{font-size:20px}
.modal-close{background:none;border:none;color:#fff;font-size:28px;cursor:pointer}
.modal-body{overflow-y:auto;overflow-x:hidden;padding:20px 28px;flex:1;min-height:0}
.modal-scroll{overflow-y:auto;overflow-x:hidden;padding:20px 28px;flex:1 1 auto;min-height:0;display:block}
.modal-footer{padding:14px 28px;border-top:1px solid #E8E8E6;display:flex;justify-content:space-between;align-items:center;background:#F7F7F5;flex-shrink:0}

.summary-bar{display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.summary-item{background:rgba(47,120,196,0.06);padding:14px 20px;border-radius:0;text-align:center;min-width:160px;flex:1}
.summary-item .num{font-size:26px;font-weight:700;color:#000048;line-height:1}
.summary-item .lbl{font-size:11px;color:#53565A;text-transform:uppercase;letter-spacing:0.4px;margin-top:6px;font-weight:600}
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

/* Realtime persona-comparison panel */
.persona-panel{display:none;margin-top:24px;background:linear-gradient(135deg,#f6f9ff 0%,#eef3ff 100%);border-radius:12px;padding:20px 24px;box-shadow:0 2px 12px rgba(0,0,72,0.08)}
.persona-panel.persona-panel--in-modal{margin:18px 0 0;width:100%}
.persona-panel.persona-panel--in-modal.show{display:block}
.persona-panel--in-modal .persona-list{display:grid;grid-template-columns:1fr;gap:14px}
.persona-panel--in-modal .pgraph-card{padding:14px 18px}
.persona-panel--in-modal .pgc-svg{min-height:480px}
.persona-panel.show{display:block}
.persona-panel-head h2{margin:0 0 4px;color:#000048;font-size:18px}
.persona-panel-head p{margin:0 0 16px;color:#53565A;font-size:13px}
.persona-list{display:grid;grid-template-columns:1fr;gap:18px}

/* Per-member graph card */
.pgraph-card{background:#fff;border-radius:12px;padding:18px 22px;border:1px solid #dde4f7;animation:fadeUp .5s ease both;box-shadow:0 1px 4px rgba(0,0,72,0.04)}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.pgc-head{display:flex;align-items:flex-start;gap:14px;margin-bottom:12px}
.pgc-avatar{width:42px;height:42px;border-radius:50%;background:#000048;color:#fff;font-weight:700;font-size:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.pgc-identity{flex:1;min-width:0}
.pgc-name{font-weight:700;color:#000048;font-size:16px;margin-bottom:4px}
.pgc-meta{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:#374151;margin-top:2px}
.pgc-meta strong{color:#6B7280;font-weight:500;margin-right:3px}
.pgc-meta-row2{margin-top:4px;color:#475569}
.pgc-stage{font-size:11.5px;color:#3B82F6;background:#EFF6FF;padding:6px 14px;border-radius:999px;font-weight:600;white-space:nowrap;align-self:center}
.pgc-stage--gap{color:#B81F2D;background:#FEF2F2}
.pgc-stage--ok{color:#059669;background:#ECFDF5}

.pgc-graph-wrap{position:relative;background:#0b1220;border-radius:10px;padding:6px;margin:6px 0 12px}
.pgc-svg{width:100%;height:auto;display:block;background:radial-gradient(circle at center,#0f172a 0%,#0b1220 80%);border-radius:6px}
/* SVG-internal <animate> tags drive the node + edge fade-in. CSS keyframes
   are deliberately not used on SVG <g>/<line> elements because animating
   CSS transform overrides the SVG transform="translate(x,y)" attribute and
   collapses the geometry to (0,0). */

.pgc-legend{display:flex;align-items:center;gap:6px;font-size:11px;color:#cbd5e1;padding:6px 10px}
.pgc-legend .lg-dot{display:inline-block;width:9px;height:9px;border-radius:50%}
.pgc-legend .lg-edge{display:inline-block;width:24px;height:0;border-top:2px solid #10B981}
.pgc-legend .lg-edge--dashed{border-top:2px dashed #B81F2D}

.pgc-gaps{font-size:12px;color:#374151;margin-top:6px;padding-top:10px;border-top:1px dashed #E5E7EB}
.pgc-gap-title{font-weight:600;margin-bottom:6px;color:#B81F2D}
.pgc-gap-chip{display:inline-block;background:#FEF2F2;color:#B81F2D;border:1px solid #FECACA;padding:3px 8px;margin:3px 4px 0 0;border-radius:999px;font-size:11px;font-weight:500}
.pgc-gap-ok{color:#059669;font-weight:500}

.pgc-history{margin-top:12px;padding-top:10px;border-top:1px dashed #E5E7EB;font-size:12px}
.pgc-hist-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.pgc-hist-col{background:#F9FAFB;border-radius:8px;padding:10px 12px;border:1px solid #E5E7EB}
.pgc-hist-title{font-weight:700;color:#000048;margin-bottom:8px;font-size:12px}
.pgc-fam-row{padding:6px 0;border-bottom:1px solid #F1F5F9;display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.pgc-fam-row:last-child{border-bottom:none}
.pgc-fam-row strong{color:#000048;text-transform:capitalize;min-width:70px}
.pgc-fam-status{font-size:10px;padding:2px 8px;border-radius:999px;font-weight:600}
.pgc-fam-status.alive{background:#ECFDF5;color:#059669}
.pgc-fam-status.deceased{background:#FEF2F2;color:#B81F2D}
.pgc-fam-chip{background:#EEF2FF;color:#4338CA;border:1px solid #C7D2FE;padding:2px 8px;border-radius:999px;font-size:10.5px}
.pgc-med-row{padding:5px 0;display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.pgc-med-label{color:#6B7280;font-weight:600;min-width:90px;font-size:11px}
.pgc-med-chip{background:#F0F9FF;color:#0369A1;border:1px solid #BAE6FD;padding:2px 8px;border-radius:999px;font-size:10.5px}
.pgc-empty{color:#9CA3AF;font-size:11px;font-style:italic}
.result-card .status-badge.success{background:rgba(45,184,31,0.1);color:#2DB81F}
.result-card .status-badge.error{background:rgba(184,31,45,0.08);color:#B81F2D}
</style></head><body>
<div class="header">
  <h1>&#128228; Bulk Upload Members</h1>
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
    <!-- Single scrollable region containing both the member checklist and
         the realtime persona visualization, so the user can scroll the whole
         thing freely inside the modal. -->
    <div class="modal-scroll">
      <div id="previewBody"></div>
      <div class="persona-panel persona-panel--in-modal" id="personaPanel">
        <div class="persona-panel-head">
          <h2>🧬 Persona-Based Care-Gap Discovery — Live</h2>
          <p id="personaStatus">Generating closest-fit ideal personas…</p>
        </div>
        <div class="persona-list" id="personaList"></div>
      </div>
    </div>

    <div class="modal-footer">
      <div>
        <button class="cancel-btn" onclick="closeModal()">Cancel</button>
        <span class="selected-count" id="selectedCount" style="margin-left:16px"></span>
      </div>
      <button class="approve-btn" id="approveBtn" onclick="approveAndProcess()">Proceed with Outreach</button>
    </div>
  </div>
</div>

<!-- Processing Overlay -->
<div class="processing-overlay" id="processingOverlay">
  <div class="processing-box">
    <div class="spinner"></div>
    <h2>Outreach In Progress…</h2>
    <p id="processingMsg">Sending outreach emails to all selected members and finalising their care-gap records. This may take a few minutes.</p>
  </div>
</div>

<!-- Results Area -->
<div class="results-area" id="resultsArea">
  <h2 style="color:#000048;margin-bottom:16px">&#9989; Processing Complete</h2>
  <div id="resultsContainer"></div>
  <div style="text-align:center;margin-top:24px">
    <button class="upload-btn" onclick="location.reload()">Upload Another File</button>
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
      <div class="summary-item"><div class="num">${withGaps}</div><div class="lbl">Members with Gaps</div></div>
      <div class="summary-item"><div class="num">${compliant}</div><div class="lbl">Compliant</div></div>
      <div class="summary-item"><div class="num">${totalGaps}</div><div class="lbl">Care Gaps Found</div></div>
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

  // ── Kick off persona-based care-gap discovery NOW (during preview),
  //    before the user presses "Proceed with Outreach". This decouples the
  //    realtime visualization from the Azure email send so it's always
  //    visible — even if the email send is throttled / fails later.
  loadPreviewPersonaPanel(members);
}

// ── Persona-graph helpers (top-level so showPreview/loadPreviewPersonaPanel
// can reach them; previously these were nested inside approveAndProcess and
// silently undefined at preview time). ───────────────────────────────────
const PG_VB_W = 900, PG_VB_H = 520, PG_MX = 180, PG_PX = 720, PG_CY = 260;

// Per-graph registry so we can drag nodes and have connected edges follow,
// Neo4j-Browser-style. mid → { nodes: {nodeId: {x,y,el}}, edges: [{el, from, fromOff, to, toOff}] }
const PG_REGISTRY = {};

function pgRegisterNode(mid, nodeId, x, y, el){
  PG_REGISTRY[mid] = PG_REGISTRY[mid] || {nodes:{}, edges:[]};
  PG_REGISTRY[mid].nodes[nodeId] = {x, y, el};
}
function pgRegisterEdge(mid, fromId, toId, lineEl, fromOff, toOff){
  PG_REGISTRY[mid] = PG_REGISTRY[mid] || {nodes:{}, edges:[]};
  PG_REGISTRY[mid].edges.push({el: lineEl, from: fromId, to: toId,
    fromOff: fromOff || {dx:0, dy:0}, toOff: toOff || {dx:0, dy:0}});
}
function pgMoveNode(mid, nodeId, nx, ny){
  const reg = PG_REGISTRY[mid]; if (!reg) return;
  const node = reg.nodes[nodeId]; if (!node) return;
  node.x = nx; node.y = ny;
  node.el.setAttribute('transform', `translate(${nx},${ny})`);
  reg.edges.forEach(e => {
    if (e.from === nodeId){
      e.el.setAttribute('x1', nx + e.fromOff.dx);
      e.el.setAttribute('y1', ny + e.fromOff.dy);
    }
    if (e.to === nodeId){
      e.el.setAttribute('x2', nx + e.toOff.dx);
      e.el.setAttribute('y2', ny + e.toOff.dy);
    }
  });
}

// Attach drag handlers to a graph card's SVG (called once per card).
function pgAttachDrag(mid){
  const svg = document.getElementById(`pgc-svg-${mid}`);
  if (!svg || svg.dataset.dragWired) return;
  svg.dataset.dragWired = '1';
  let dragging = null; // {nodeId, dx, dy}
  function svgPoint(evt){
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return {x: evt.clientX, y: evt.clientY};
    const inv = ctm.inverse();
    const p = pt.matrixTransform(inv);
    return {x: p.x, y: p.y};
  }
  svg.addEventListener('mousedown', evt => {
    const g = evt.target.closest('g[data-pg-node-id]');
    if (!g) return;
    const id = g.dataset.pgNodeId;
    const node = (PG_REGISTRY[mid]?.nodes||{})[id];
    if (!node) return;
    const p = svgPoint(evt);
    dragging = { nodeId: id, dx: p.x - node.x, dy: p.y - node.y };
    svg.style.cursor = 'grabbing';
    evt.preventDefault();
  });
  window.addEventListener('mousemove', evt => {
    if (!dragging) return;
    const p = svgPoint(evt);
    pgMoveNode(mid, dragging.nodeId, p.x - dragging.dx, p.y - dragging.dy);
  });
  window.addEventListener('mouseup', () => {
    if (dragging) { svg.style.cursor=''; dragging = null; }
  });
}

function pgFadeIn(dur){
  dur = dur || '0.45s';
  return `<animate attributeName="opacity" from="0" to="1" dur="${dur}" fill="freeze"/>`;
}

// ── Care-gap reason tooltip (shared single floating element) ────────────────
let _cgTipEl = null;
function _ensureCgTip(){
  if (_cgTipEl) return _cgTipEl;
  const t = document.createElement('div');
  t.id = 'cg-tooltip';
  t.style.cssText = [
    'position:fixed','z-index:99999','pointer-events:none',
    'max-width:340px','background:#0f172a','color:#e2e8f0',
    'font-size:12px','line-height:1.45','padding:10px 14px',
    'border:1px solid #1e293b','border-radius:8px',
    'box-shadow:0 10px 30px rgba(0,0,0,0.45)',
    'opacity:0','transform:translateY(4px)',
    'transition:opacity 0.15s ease, transform 0.15s ease',
  ].join(';');
  t.innerHTML = '';
  document.body.appendChild(t);
  _cgTipEl = t;
  return t;
}
function cgShowTooltip(evt){
  const el = evt.currentTarget;
  const reason  = el?.dataset?.cgReason || '';
  const measure = el?.dataset?.cgMeasure || '';
  if (!reason) return;
  const tip = _ensureCgTip();
  tip.innerHTML = (
    `<div style="font-weight:700;color:#fca5a5;margin-bottom:6px;font-size:11px;letter-spacing:0.3px;">CARE GAP · ${measure}</div>` +
    `<div>${reason.replace(/</g,'&lt;')}</div>`
  );
  const r = el.getBoundingClientRect();
  const top  = Math.max(8, r.top  - 8);
  const left = Math.min(window.innerWidth - 360, r.right + 12);
  tip.style.top  = `${top}px`;
  tip.style.left = `${left}px`;
  tip.style.opacity = '1';
  tip.style.transform = 'translateY(0)';
}
function cgHideTooltip(){
  if (!_cgTipEl) return;
  _cgTipEl.style.opacity = '0';
  _cgTipEl.style.transform = 'translateY(4px)';
}

// ── Persona match tooltip — bullet-point analysis on hover of IDEAL node ────
let _personaTipEl = null;
function _ensurePersonaTip(){
  if (_personaTipEl) return _personaTipEl;
  const t = document.createElement('div');
  t.id = 'persona-tooltip';
  t.style.cssText = [
    'position:fixed','z-index:99999','pointer-events:none',
    'max-width:420px','background:#0f172a','color:#e2e8f0',
    'font-size:12px','line-height:1.5','padding:12px 16px',
    'border:1px solid #10B981','border-radius:10px',
    'box-shadow:0 10px 30px rgba(16,185,129,0.25)',
    'opacity:0','transform:translateY(4px)',
    'transition:opacity 0.15s ease, transform 0.15s ease',
  ].join(';');
  document.body.appendChild(t);
  _personaTipEl = t;
  return t;
}
function personaShowTooltip(evt){
  const el = evt.currentTarget;
  let bullets = [];
  try { bullets = JSON.parse(el?.dataset?.personaBullets || '[]'); }
  catch(e){ bullets = []; }
  const pid = el?.dataset?.personaId || 'P??';
  if (!bullets.length) return;
  const tip = _ensurePersonaTip();
  const items = bullets.map(b =>
    `<li style="margin:4px 0;">${String(b).replace(/</g,'&lt;')}</li>`
  ).join('');
  tip.innerHTML = (
    `<div style="font-weight:700;color:#6ee7b7;margin-bottom:6px;font-size:11px;letter-spacing:0.3px;">PERSONA MATCH ANALYSIS · ${pid}</div>` +
    `<div style="color:#94a3b8;font-size:10px;margin-bottom:8px;">Why the agents picked this persona for this member</div>` +
    `<ul style="margin:0;padding-left:18px;">${items}</ul>`
  );
  const r = el.getBoundingClientRect();
  const top  = Math.max(8, r.top - 8);
  // Tooltip prefers to sit to the LEFT of the persona node (which lives on
  // the right side of the graph) so it stays inside the viewport.
  const left = Math.max(8, r.left - 440);
  tip.style.top  = `${top}px`;
  tip.style.left = `${left}px`;
  tip.style.opacity = '1';
  tip.style.transform = 'translateY(0)';
}
function personaHideTooltip(){
  if (!_personaTipEl) return;
  _personaTipEl.style.opacity = '0';
  _personaTipEl.style.transform = 'translateY(4px)';
}
function pgClearGraph(mid){
  const n = document.getElementById(`pgc-nodes-${mid}`);
  const e = document.getElementById(`pgc-edges-${mid}`);
  if (n) n.innerHTML = '';
  if (e) e.innerHTML = '';
}
function pgAppendNode(mid, html){
  const el = document.getElementById(`pgc-nodes-${mid}`);
  if (el) el.insertAdjacentHTML('beforeend', html);
}
function pgAppendEdge(mid, html){
  const el = document.getElementById(`pgc-edges-${mid}`);
  if (el) el.insertAdjacentHTML('beforeend', html);
}

function renderGraphCard(m){
  const initials = (m.name || '?').split(' ').map(s => s[0]).slice(0, 2).join('').toUpperCase();
  return `
    <div class="pgraph-card" id="pgc-${m.member_id}">
      <div class="pgc-head">
        <div class="pgc-avatar">${initials}</div>
        <div class="pgc-identity">
          <div class="pgc-name">${m.name||'—'}</div>
          <div class="pgc-meta" id="pgc-meta-${m.member_id}">
            <span><strong>ID:</strong> ${m.member_id}</span>
            <span><strong>Email:</strong> ${m.email||'—'}</span>
          </div>
          <div class="pgc-meta pgc-meta-row2" id="pgc-meta2-${m.member_id}">
            <span><strong>Age:</strong> —</span>
            <span><strong>Gender:</strong> —</span>
            <span><strong>PCP:</strong> —</span>
            <span><strong>Insurance:</strong> —</span>
          </div>
        </div>
        <div class="pgc-stage" id="pgc-stage-${m.member_id}">⏳ Connecting to graph…</div>
      </div>
      <div class="pgc-graph-wrap">
        <svg class="pgc-svg" id="pgc-svg-${m.member_id}" viewBox="0 0 900 520" preserveAspectRatio="xMidYMid meet">
          <g id="pgc-edges-${m.member_id}"></g>
          <g id="pgc-nodes-${m.member_id}"></g>
        </svg>
        <div class="pgc-legend">
          <span class="lg-dot" style="background:#000048"></span> Member
          <span class="lg-dot" style="background:#10B981;margin-left:10px"></span> Persona
          <span class="lg-dot" style="background:#3B82F6;margin-left:10px"></span> Screening
          <span class="lg-edge lg-edge--solid" style="margin-left:10px"></span> Completed
          <span class="lg-edge lg-edge--dashed" style="margin-left:10px"></span> Care Gap
        </div>
      </div>
      <div class="pgc-gaps" id="pgc-gaps-${m.member_id}"><em>Awaiting comparison…</em></div>
    </div>`;
}

function memberNodeHtml(cmp){
  const initials = (cmp.member_name||'?').split(' ').map(s=>s[0]).slice(0,2).join('').toUpperCase();
  return `
    <g transform="translate(${PG_MX},${PG_CY})" opacity="0">${pgFadeIn()}
      <circle r="40" fill="#000048" stroke="#fff" stroke-width="3"/>
      <text text-anchor="middle" dy="-2" fill="#fff" font-size="13" font-weight="700">${initials}</text>
      <text text-anchor="middle" dy="14" fill="#bcd0ff" font-size="9">${cmp.member_id}</text>
      <text text-anchor="middle" dy="60" fill="#bcd0ff" font-size="11" font-weight="600">Member · ${(cmp.member_name||'').slice(0,18)}</text>
    </g>`;
}
function personaNodeHtml(cmp){
  // Random persona ID allocated by the backend (e.g. P12, P45) — jumbled, not derived from member_id.
  const pid = cmp.persona_id || 'P??';
  return `
    <g transform="translate(${PG_PX},${PG_CY})" opacity="0">${pgFadeIn()}
      <circle r="36" fill="#10B981" stroke="#fff" stroke-width="3"/>
      <text text-anchor="middle" dy="-2" fill="#fff" font-size="11" font-weight="700">IDEAL</text>
      <text text-anchor="middle" dy="12" fill="#d1fae5" font-size="9">${pid}</text>
      <text text-anchor="middle" dy="56" fill="#a7f3d0" font-size="11" font-weight="600">Persona · closest fit</text>
    </g>`;
}

async function animateGraph(mid, cmp){
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  pgClearGraph(mid);
  PG_REGISTRY[mid] = {nodes:{}, edges:[]};
  pgAttachDrag(mid);

  // Helper: append a draggable node and register it.
  const addNode = (nodeId, x, y, innerSVG, opts) => {
    const ns = 'http://www.w3.org/2000/svg';
    const g = document.createElementNS(ns, 'g');
    g.setAttribute('transform', `translate(${x},${y})`);
    g.setAttribute('opacity', '0');
    g.setAttribute('data-pg-node-id', nodeId);
    g.style.cursor = 'grab';
    g.innerHTML = `${pgFadeIn()}${innerSVG}`;
    document.getElementById(`pgc-nodes-${mid}`).appendChild(g);
    pgRegisterNode(mid, nodeId, x, y, g);
    return g;
  };
  const addEdge = (fromId, toId, fromOff, toOff, attrs, label) => {
    const ns = 'http://www.w3.org/2000/svg';
    const fromN = PG_REGISTRY[mid].nodes[fromId];
    const toN   = PG_REGISTRY[mid].nodes[toId];
    if (!fromN || !toN) return;
    const x1 = fromN.x + (fromOff?.dx||0);
    const y1 = fromN.y + (fromOff?.dy||0);
    const x2 = toN.x   + (toOff?.dx||0);
    const y2 = toN.y   + (toOff?.dy||0);
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
    Object.entries(attrs||{}).forEach(([k,v]) => line.setAttribute(k, v));
    line.setAttribute('opacity', '0');
    line.innerHTML = `<animate attributeName="opacity" from="0" to="${attrs.opacity!=null?attrs.opacity:1}" dur="0.45s" fill="freeze"/>`;
    document.getElementById(`pgc-edges-${mid}`).appendChild(line);
    pgRegisterEdge(mid, fromId, toId, line, fromOff, toOff);
    if (label){
      const txt = document.createElementNS(ns, 'text');
      txt.setAttribute('x', (x1+x2)/2);
      txt.setAttribute('y', (y1+y2)/2 - 4);
      txt.setAttribute('text-anchor', 'middle');
      txt.setAttribute('font-size', '9');
      txt.setAttribute('fill', label.color||'#9CA3AF');
      txt.textContent = label.text;
      txt.setAttribute('opacity', '0');
      txt.innerHTML += `<animate attributeName="opacity" from="0" to="1" dur="0.45s" begin="0.15s" fill="freeze"/>`;
      document.getElementById(`pgc-edges-${mid}`).appendChild(txt);
      // Track the label too: re-anchor between the two nodes when either moves.
      pgRegisterEdge(mid, fromId, toId, txt, fromOff, toOff);
      // Override the line-only update to also recompute midpoint for the text:
      const reg = PG_REGISTRY[mid];
      const lastEdge = reg.edges[reg.edges.length - 1];
      lastEdge.isLabel = true;
    }
  };

  // Override pgMoveNode to also reposition labels at the midpoint.
  if (!window.__pgMoveNodePatched){
    const original = pgMoveNode;
    window.pgMoveNode = function(mid, nodeId, nx, ny){
      const reg = PG_REGISTRY[mid]; if (!reg) return;
      const node = reg.nodes[nodeId]; if (!node) return;
      node.x = nx; node.y = ny;
      node.el.setAttribute('transform', `translate(${nx},${ny})`);
      reg.edges.forEach(e => {
        if (e.isLabel){
          const f = reg.nodes[e.from], t = reg.nodes[e.to];
          if (!f || !t) return;
          const x1 = f.x + (e.fromOff.dx||0), y1 = f.y + (e.fromOff.dy||0);
          const x2 = t.x + (e.toOff.dx  ||0), y2 = t.y + (e.toOff.dy  ||0);
          e.el.setAttribute('x', (x1+x2)/2);
          e.el.setAttribute('y', (y1+y2)/2 - 4);
        } else {
          if (e.from === nodeId){ e.el.setAttribute('x1', nx + e.fromOff.dx); e.el.setAttribute('y1', ny + e.fromOff.dy); }
          if (e.to   === nodeId){ e.el.setAttribute('x2', nx + e.toOff.dx);   e.el.setAttribute('y2', ny + e.toOff.dy);   }
        }
      });
    };
    window.__pgMoveNodePatched = true;
  }

  // Member node (draggable)
  addNode('member', PG_MX, PG_CY, `
    <circle r="40" fill="#000048" stroke="#fff" stroke-width="3"/>
    <text text-anchor="middle" dy="-2" fill="#fff" font-size="13" font-weight="700">${(cmp.member_name||'?').split(' ').map(s=>s[0]).slice(0,2).join('').toUpperCase()}</text>
    <text text-anchor="middle" dy="14" fill="#bcd0ff" font-size="9">${cmp.member_id}</text>
    <text text-anchor="middle" dy="60" fill="#bcd0ff" font-size="11" font-weight="600">Member · ${(cmp.member_name||'').slice(0,18)}</text>
  `);
  await sleep(450);
  // Persona node — also carries the bullet-point match analysis tooltip
  const personaNodeEl = addNode('persona', PG_PX, PG_CY, `
    <circle r="36" fill="#10B981" stroke="#fff" stroke-width="3"/>
    <text text-anchor="middle" dy="-2" fill="#fff" font-size="11" font-weight="700">IDEAL</text>
    <text text-anchor="middle" dy="12" fill="#d1fae5" font-size="9">${cmp.persona_id||'P??'}</text>
    <text text-anchor="middle" dy="56" fill="#a7f3d0" font-size="11" font-weight="600">Persona · closest fit</text>
  `);
  // Hover tooltip — bullet-point analysis explaining WHY this persona was matched.
  if (personaNodeEl && Array.isArray(cmp.persona_match_bullets) && cmp.persona_match_bullets.length){
    personaNodeEl.dataset.personaBullets = JSON.stringify(cmp.persona_match_bullets);
    personaNodeEl.dataset.personaId = cmp.persona_id || 'P??';
    personaNodeEl.addEventListener('mouseenter', personaShowTooltip);
    personaNodeEl.addEventListener('mouseleave', personaHideTooltip);
    // Hint cursor so users discover it's interactive.
    personaNodeEl.style.cursor = 'help';
  }
  await sleep(450);
  // COMPARED_TO edge
  addEdge('member', 'persona', {dx:0,dy:0}, {dx:0,dy:0},
    {stroke:'#10B981', 'stroke-width':'2.5', opacity:1},
    {text:'COMPARED_TO', color:'#10B981'});
  await sleep(450);

  // Lifestyle parameter nodes between member and persona (top arc).
  // Each chip shows the member's actual value alongside the persona's
  // healthy band, with a green/red dot indicating whether the member
  // already sits inside the healthy band.
  const lc = cmp.lifestyle_compare || {};
  const paramSpecs = [
    { key:'BMI',      f:'bmi'                },
    { key:'Smoking',  f:'smoking_status'     },
    { key:'Exercise', f:'exercise_frequency' },
    { key:'Diet',     f:'diet_type'          },
  ];
  const params = paramSpecs.map(s => ({
    key:    s.key,
    actual: (lc[s.f]||{}).actual || '—',
    ideal:  (lc[s.f]||{}).ideal_range || (cmp.ideal_lifestyle||{})[s.f] || '',
    healthy: (lc[s.f]||{}).is_healthy,  // true / false / null
  }));
  for (let i = 0; i < params.length; i++){
    const t = (i+1)/(params.length+1);
    const px = PG_MX + t*(PG_PX-PG_MX);
    const py = PG_CY - 110;
    const dotColor = params[i].healthy === true ? '#10B981'
                   : params[i].healthy === false ? '#EF4444' : '#94a3b8';
    const ringColor = params[i].healthy === false ? '#EF4444' : '#7373D8';
    addNode(`param-${i}`, px, py, `
      <rect x="-72" y="-22" width="144" height="44" rx="10" ry="10" fill="#1e293b" stroke="${ringColor}" stroke-width="1.5"/>
      <circle cx="-58" cy="0" r="4" fill="${dotColor}"/>
      <text text-anchor="middle" dy="-9" fill="#cbd5e1" font-size="9" font-weight="700">${params[i].key}</text>
      <text text-anchor="middle" dy="3" fill="#fde68a" font-size="8">member: ${(params[i].actual||'—').toString().slice(0,18)}</text>
      <text text-anchor="middle" dy="14" fill="#a7f3d0" font-size="8">persona: ${(params[i].ideal||'').toString().slice(0,22)}</text>
    `);
    addEdge('member', `param-${i}`, {dx:0,dy:-12}, {dx:0,dy:18},
      {stroke:'#64748b','stroke-width':'1.4','stroke-dasharray':'3 3',opacity:0.65});
    addEdge(`param-${i}`, 'persona', {dx:0,dy:18}, {dx:0,dy:-12},
      {stroke:'#10B981','stroke-width':'1.4',opacity:0.65});
    await sleep(220);
  }

  // Screening nodes — fan arc beneath
  const screenings = [...(cmp.completed_screenings||[]), ...(cmp.pending_screenings||[])];
  if (screenings.length){
    const arcY = PG_CY + 120, arcRadius = 200, arcCenterX = (PG_MX+PG_PX)/2;
    const totalArc = Math.min(Math.PI*0.7, Math.PI*0.18*screenings.length);
    const startAngle = Math.PI/2 - totalArc/2;
    for (let i = 0; i < screenings.length; i++){
      const s = screenings[i];
      const completed = i < (cmp.completed_screenings||[]).length;
      const angle = startAngle + (screenings.length===1 ? totalArc/2 : (totalArc*i)/(screenings.length-1));
      const sx = arcCenterX + arcRadius*Math.cos(angle);
      const sy = arcY + 30 - arcRadius*Math.sin(angle)*0.45;
      const fill = completed ? '#3B82F6' : '#FCA5A5';
      const ring = completed ? '#1D4ED8' : '#B81F2D';
      const labelColor = completed ? '#bfdbfe' : '#fecaca';
      const nodeId = `scr-${i}`;
      const nodeEl = addNode(nodeId, sx, sy, `
        <circle r="22" fill="${fill}" stroke="${ring}" stroke-width="2"/>
        <text text-anchor="middle" dy="3" fill="#fff" font-size="10" font-weight="700">${(s.measure_id||'').slice(0,4)}</text>
        <text text-anchor="middle" dy="38" fill="${labelColor}" font-size="9" font-weight="500">${(s.measure_name||s.measure_id||'').slice(0,18)}</text>
      `);
      // Care-gap hover tooltip — shows the LLM-generated clinical reason
      // for pending screenings only (completed ones don't need an
      // explanation).
      if (!completed && s.reason && nodeEl){
        nodeEl.classList.add('cg-tooltip-anchor');
        nodeEl.dataset.cgReason = s.reason;
        nodeEl.dataset.cgMeasure = `${s.measure_id||''} · ${s.measure_name||''}`;
        nodeEl.addEventListener('mouseenter', cgShowTooltip);
        nodeEl.addEventListener('mouseleave', cgHideTooltip);
      }
      addEdge('member', nodeId,
        {dx:0,dy:18}, {dx:0,dy:-18},
        completed
          ? {stroke:'#10B981','stroke-width':'2',opacity:1}
          : {stroke:'#B81F2D','stroke-width':'2','stroke-dasharray':'6 4',opacity:1},
        {text: completed ? 'HAS_COMPLETED' : 'CARE_GAP', color: completed ? '#34d399' : '#fca5a5'});
      addEdge('persona', nodeId,
        {dx:0,dy:18}, {dx:0,dy:-18},
        {stroke:'#3B82F6','stroke-width':'1.3',opacity:0.55});
      await sleep(280);
    }
  }

  // Family / Ancestral history (left side, purple)
  const fam = (cmp.family_history||[]).slice(0,4);
  for (let i = 0; i < fam.length; i++){
    const f = fam[i];
    const fy = 80 + i*80, fx = 124;
    const nodeId = `fam-${i}`;
    addNode(nodeId, fx, fy, `
      <rect x="-84" y="-16" width="168" height="32" rx="14" ry="14" fill="#1e1b4b" stroke="#8B5CF6" stroke-width="1.5"/>
      <text x="-74" y="-2" fill="#ddd6fe" font-size="10" font-weight="700">${f.relation}</text>
      <text x="-74" y="11" fill="#c4b5fd" font-size="8">${(f.conditions||[]).slice(0,2).join(', ').slice(0,28) || (f.alive ? 'no conditions' : 'deceased')}</text>
    `);
    addEdge('member', nodeId, {dx:-30,dy:-15}, {dx:84,dy:0},
      {stroke:'#8B5CF6','stroke-width':'1.4',opacity:0.7},
      {text:'HAS_RELATIVE', color:'#c4b5fd'});
    await sleep(180);
  }

  // Medical history (right side)
  const med = cmp.medical_history || {};
  const medItems = [
    ...(med.current_conditions||[]).slice(0,2).map(x => ({type:'Current', label:x, color:'#0EA5E9'})),
    ...(med.medications||[]).slice(0,2).map(x => ({type:'Med', label:x, color:'#14B8A6'})),
    ...(med.allergies||[]).slice(0,1).map(x => ({type:'Allergy', label:x, color:'#F97316'})),
  ];
  for (let i = 0; i < medItems.length; i++){
    const item = medItems[i];
    const my = 80 + i*80, mx_pos = 770;
    const nodeId = `med-${i}`;
    addNode(nodeId, mx_pos, my, `
      <rect x="-90" y="-16" width="180" height="32" rx="14" ry="14" fill="#0c2540" stroke="${item.color}" stroke-width="1.5"/>
      <text x="0" y="-2" text-anchor="middle" fill="#cbd5e1" font-size="9" font-weight="700">${item.type}</text>
      <text x="0" y="11" text-anchor="middle" fill="#e2e8f0" font-size="9">${(item.label||'').slice(0,28)}</text>
    `);
    addEdge('member', nodeId, {dx:30,dy:-15}, {dx:-90,dy:0},
      {stroke:item.color,'stroke-width':'1.4',opacity:0.7},
      {text:'HAS_MEDICAL', color:item.color});
    await sleep(180);
  }

  return; // legacy step-based renderer below is unused
}

async function _legacyAnimateGraph_unused(mid, cmp){
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  pgClearGraph(mid);
  pgAppendNode(mid, memberNodeHtml(cmp));   await sleep(450);
  pgAppendNode(mid, personaNodeHtml(cmp));  await sleep(450);
  pgAppendEdge(mid, `
    <line x1="${PG_MX}" y1="${PG_CY}" x2="${PG_PX}" y2="${PG_CY}"
          stroke="#10B981" stroke-width="2.5" opacity="0">${pgFadeIn('0.5s')}</line>
    <text x="${(PG_MX+PG_PX)/2}" y="${PG_CY-10}" text-anchor="middle" fill="#10B981"
          font-size="12" font-weight="700" opacity="0">${pgFadeIn('0.5s')}COMPARED_TO</text>
  `);
  await sleep(550);

  const params = [
    { key: 'BMI',      ideal: (cmp.ideal_lifestyle||{}).bmi },
    { key: 'Smoking',  ideal: (cmp.ideal_lifestyle||{}).smoking_status },
    { key: 'Exercise', ideal: (cmp.ideal_lifestyle||{}).exercise_frequency },
    { key: 'Diet',     ideal: (cmp.ideal_lifestyle||{}).diet_type },
  ];
  const paramY = PG_CY - 110;
  for (let i = 0; i < params.length; i++){
    const t = (i + 1) / (params.length + 1);
    const px = PG_MX + t * (PG_PX - PG_MX);
    const p = params[i];
    pgAppendEdge(mid, `<line x1="${PG_MX}" y1="${PG_CY-12}" x2="${px}" y2="${paramY+18}" stroke="#64748b" stroke-width="1.4" stroke-dasharray="3 3" opacity="0"><animate attributeName="opacity" from="0" to="0.65" dur="0.4s" fill="freeze"/></line>`);
    pgAppendNode(mid, `
      <g transform="translate(${px},${paramY})" opacity="0">${pgFadeIn()}
        <rect x="-46" y="-16" width="92" height="32" rx="16" ry="16" fill="#1e293b" stroke="#7373D8" stroke-width="1.5"/>
        <text text-anchor="middle" dy="-2" fill="#cbd5e1" font-size="9" font-weight="600">${p.key}</text>
        <text text-anchor="middle" dy="9" fill="#a7f3d0" font-size="8">${(p.ideal||'').toString().slice(0,16)}</text>
      </g>`);
    pgAppendEdge(mid, `<line x1="${px}" y1="${paramY+18}" x2="${PG_PX}" y2="${PG_CY-12}" stroke="#10B981" stroke-width="1.4" opacity="0"><animate attributeName="opacity" from="0" to="0.65" dur="0.4s" fill="freeze"/></line>`);
    await sleep(280);
  }

  const screenings = [...(cmp.completed_screenings||[]), ...(cmp.pending_screenings||[])];
  if (!screenings.length) return;
  const arcY = PG_CY + 120, arcRadius = 200, arcCenterX = (PG_MX + PG_PX) / 2;
  const totalArc = Math.min(Math.PI * 0.7, Math.PI * 0.18 * screenings.length);
  const startAngle = Math.PI/2 - totalArc/2;
  for (let i = 0; i < screenings.length; i++){
    const s = screenings[i];
    const completed = i < (cmp.completed_screenings||[]).length;
    const angle = startAngle + (screenings.length === 1 ? totalArc/2 : (totalArc * i) / (screenings.length - 1));
    const sx = arcCenterX + arcRadius * Math.cos(angle);
    const sy = arcY + 30 - arcRadius * Math.sin(angle) * 0.45;
    const memberStroke = completed ? '#10B981' : '#B81F2D';
    const memberDash   = completed ? '' : 'stroke-dasharray="6 4"';
    pgAppendEdge(mid, `
      <line x1="${PG_MX}" y1="${PG_CY+18}" x2="${sx}" y2="${sy-18}" stroke="${memberStroke}" stroke-width="2" ${memberDash} opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.45s" fill="freeze"/>
      </line>
      <text x="${(PG_MX+sx)/2}" y="${(PG_CY+sy)/2 - 4}" fill="${completed ? '#34d399' : '#fca5a5'}" font-size="9" text-anchor="middle" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.45s" begin="0.2s" fill="freeze"/>
        ${completed ? 'HAS_COMPLETED' : 'CARE_GAP'}
      </text>`);
    pgAppendEdge(mid, `<line x1="${PG_PX}" y1="${PG_CY+18}" x2="${sx}" y2="${sy-18}" stroke="#3B82F6" stroke-width="1.3" opacity="0"><animate attributeName="opacity" from="0" to="0.55" dur="0.45s" fill="freeze"/></line>`);
    const fill = completed ? '#3B82F6' : '#FCA5A5';
    const ring = completed ? '#1D4ED8' : '#B81F2D';
    const labelColor = completed ? '#bfdbfe' : '#fecaca';
    pgAppendNode(mid, `
      <g transform="translate(${sx},${sy})" opacity="0">${pgFadeIn()}
        <circle r="22" fill="${fill}" stroke="${ring}" stroke-width="2"/>
        <text text-anchor="middle" dy="3" fill="#fff" font-size="10" font-weight="700">${(s.measure_id||'').slice(0,4)}</text>
        <text text-anchor="middle" dy="38" fill="${labelColor}" font-size="9" font-weight="500">${(s.measure_name||s.measure_id||'').slice(0,18)}</text>
      </g>`);
    await sleep(320);
  }

  // Step 6 — Family / Ancestral History nodes (rendered along the LEFT
  // side, attached to the Member with HAS_RELATIVE edges). Each node carries
  // the relative's relation + chronic conditions so the graph illustrates
  // the hereditary risk evidence the comparison uses.
  const fam = (cmp.family_history||[]).slice(0, 4);
  for (let i = 0; i < fam.length; i++){
    const f = fam[i];
    const fy = 80 + i * 80;
    const fx = 40;
    pgAppendEdge(mid, `
      <line x1="${PG_MX-30}" y1="${PG_CY-15}" x2="${fx+44}" y2="${fy}"
            stroke="#8B5CF6" stroke-width="1.4" opacity="0">
        <animate attributeName="opacity" from="0" to="0.7" dur="0.4s" fill="freeze"/>
      </line>
      <text x="${(PG_MX+fx)/2 - 30}" y="${(PG_CY+fy)/2}" fill="#c4b5fd"
            font-size="9" text-anchor="middle" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.4s" fill="freeze"/>
        HAS_RELATIVE
      </text>
    `);
    pgAppendNode(mid, `
      <g transform="translate(${fx},${fy})" opacity="0">${pgFadeIn()}
        <rect x="0" y="-16" width="170" height="32" rx="14" ry="14"
              fill="#1e1b4b" stroke="#8B5CF6" stroke-width="1.5"/>
        <text x="10" y="-2" fill="#ddd6fe" font-size="10" font-weight="700">${f.relation}</text>
        <text x="10" y="11" fill="#c4b5fd" font-size="8">${(f.conditions||[]).slice(0,2).join(', ').slice(0,28) || (f.alive ? 'no conditions' : 'deceased')}</text>
      </g>
    `);
    await sleep(220);
  }

  // Step 7 — Medical History nodes (Current conditions / Allergies /
  // Medications) rendered on the RIGHT side, attached to the Member with
  // HAS_MEDICAL edges. Mirrors what the rules engine actually consults to
  // identify open gaps.
  const med = cmp.medical_history || {};
  const medItems = [
    ...(med.current_conditions||[]).slice(0,2).map(x => ({type:'Current', label:x, color:'#0EA5E9'})),
    ...(med.medications||[]).slice(0,2).map(x => ({type:'Med', label:x, color:'#14B8A6'})),
    ...(med.allergies||[]).slice(0,1).map(x => ({type:'Allergy', label:x, color:'#F97316'})),
  ];
  for (let i = 0; i < medItems.length; i++){
    const item = medItems[i];
    const my = 80 + i * 80;
    const mx_pos = 700;
    pgAppendEdge(mid, `
      <line x1="${PG_MX+30}" y1="${PG_CY-15}" x2="${mx_pos-10}" y2="${my}"
            stroke="${item.color}" stroke-width="1.4" opacity="0">
        <animate attributeName="opacity" from="0" to="0.7" dur="0.4s" fill="freeze"/>
      </line>
      <text x="${(PG_MX+mx_pos)/2 + 30}" y="${(PG_CY+my)/2}" fill="${item.color}"
            font-size="9" text-anchor="middle" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur="0.4s" fill="freeze"/>
        HAS_MEDICAL
      </text>
    `);
    pgAppendNode(mid, `
      <g transform="translate(${mx_pos},${my})" opacity="0">${pgFadeIn()}
        <rect x="-90" y="-16" width="180" height="32" rx="14" ry="14"
              fill="#0c2540" stroke="${item.color}" stroke-width="1.5"/>
        <text x="0" y="-2" text-anchor="middle" fill="#cbd5e1" font-size="9" font-weight="700">${item.type}</text>
        <text x="0" y="11" text-anchor="middle" fill="#e2e8f0" font-size="9">${(item.label||'').slice(0,28)}</text>
      </g>
    `);
    await sleep(220);
  }
}

async function loadPreviewPersonaPanel(members){
  const personaPanel = document.getElementById('personaPanel');
  const personaList  = document.getElementById('personaList');
  const personaStatus= document.getElementById('personaStatus');
  if(!personaPanel) return;

  // Use members that have at least one open gap (the action set).
  const subjects = (members||[]).filter(m => !m.error && (m.open_gaps||[]).length > 0)
    .map(m => ({member_id:m.member_id, name:m.name, email:m.email}));
  if (!subjects.length) return;

  personaPanel.classList.add('show');
  personaList.innerHTML = subjects.map(renderGraphCard).join('');
  subjects.forEach(m => drawSkeletonCard(m));

  const stages = [
    '🔍 Loading member profile…',
    '🧬 Generating closest-fit ideal persona…',
    '⚖ Comparing screening history…',
    '📊 Surfacing missing links…',
  ];
  let stageIdx = 0;
  const stageTimer = setInterval(() => {
    stageIdx = (stageIdx + 1) % stages.length;
    personaStatus.textContent = stages[stageIdx];
  }, 1400);

  try{
    const res = await fetch('/api/v1/members/bulk-preview-persona', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({members:subjects}),
    });
    const data = await res.json();
    clearInterval(stageTimer);
    (data.results||[]).forEach(r => fillPersonaCard(r));
    personaStatus.textContent = `Persona comparison complete for ${(data.results||[]).filter(r=>r.persona_comparison).length} member(s).`;
  }catch(e){
    clearInterval(stageTimer);
    personaStatus.textContent = 'Persona comparison failed: ' + e.message;
  }
}

// Skeleton (Member + Persona placeholders) for one card.
function drawSkeletonCard(m){
  const nodesG = document.getElementById(`pgc-nodes-${m.member_id}`);
  const edgesG = document.getElementById(`pgc-edges-${m.member_id}`);
  if(!nodesG || !edgesG) return;
  const MX=180, PX=720, CY=260;
  const initials = (m.name||'?').split(' ').map(s=>s[0]).slice(0,2).join('').toUpperCase();
  edgesG.innerHTML = `
    <line x1="${MX}" y1="${CY}" x2="${PX}" y2="${CY}"
          stroke="#475569" stroke-width="1.5" stroke-dasharray="4 4"/>
    <text x="${(MX+PX)/2}" y="${CY-10}" text-anchor="middle" fill="#94a3b8"
          font-size="11">analyzing…</text>
  `;
  nodesG.innerHTML = `
    <g transform="translate(${MX},${CY})">
      <circle r="40" fill="#000048" stroke="#fff" stroke-width="3"/>
      <text text-anchor="middle" dy="-2" fill="#fff" font-size="13" font-weight="700">${initials}</text>
      <text text-anchor="middle" dy="14" fill="#bcd0ff" font-size="9">${m.member_id}</text>
      <text text-anchor="middle" dy="60" fill="#bcd0ff" font-size="11" font-weight="600">Member</text>
    </g>
    <g transform="translate(${PX},${CY})">
      <circle r="36" fill="#10B981" stroke="#fff" stroke-width="3"/>
      <text text-anchor="middle" dy="-2" fill="#fff" font-size="11" font-weight="700">IDEAL</text>
      <text text-anchor="middle" dy="56" fill="#a7f3d0" font-size="11" font-weight="600">Persona</text>
    </g>
  `;
}

// Fill one persona card with the comparison response (animates the graph too).
function fillPersonaCard(r){
  const cmp   = r.persona_comparison;
  // Cache comparison per member_id so approveAndProcess can re-animate
  // graphs during outreach without refetching.
  if (cmp && r.member_id){
    window.__lastPersonaCmp = window.__lastPersonaCmp || {};
    window.__lastPersonaCmp[r.member_id] = cmp;
  }
  const stage = document.getElementById(`pgc-stage-${r.member_id}`);
  const gaps  = document.getElementById(`pgc-gaps-${r.member_id}`);
  const meta2 = document.getElementById(`pgc-meta2-${r.member_id}`);
  const histEl= document.getElementById(`pgc-history-${r.member_id}`);
  if(!cmp){
    if(stage){ stage.textContent='⚠ No persona data'; stage.dataset.done='1'; }
    return;
  }
  if(meta2){
    meta2.innerHTML = `
      <span><strong>Age:</strong> ${cmp.age||'—'}</span>
      <span><strong>Gender:</strong> ${cmp.gender||'—'}</span>
      <span><strong>PCP:</strong> ${cmp.pcp_name||'—'}</span>
      <span><strong>Insurance:</strong> ${cmp.insurance_type||'—'}</span>
      ${cmp.chronic && cmp.chronic.length ? `<span><strong>Conditions:</strong> ${cmp.chronic.slice(0,3).join(', ')}</span>` : ''}
    `;
  }
  if(stage){
    stage.textContent = cmp.missing_link_count > 0
      ? `🩺 ${cmp.missing_link_count} care gap(s) found`
      : '✅ Fully compliant vs ideal';
    stage.dataset.done='1';
    stage.classList.add(cmp.missing_link_count > 0 ? 'pgc-stage--gap' : 'pgc-stage--ok');
  }
  if(gaps){
    gaps.innerHTML = cmp.missing_link_count > 0
      ? '<div class="pgc-gap-title">Missing links vs persona:</div>' +
        cmp.pending_screenings.map(p =>
          `<span class="pgc-gap-chip">${p.measure_id} · ${p.measure_name}</span>`
        ).join('')
      : '<div class="pgc-gap-ok">No gaps — member matches ideal twin.</div>';
  }
  // family/medical content is rendered as graph nodes inside animateGraph.
  animateGraph(r.member_id, cmp);
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

  // Keep the preview modal OPEN so the persona panel inside it stays visible
  // during outreach. Disable the action buttons while emails are being sent.
  const approveBtn = document.getElementById('approveBtn');
  const cancelBtn  = document.querySelector('.cancel-btn');
  if (approveBtn) { approveBtn.disabled = true; approveBtn.textContent = 'Sending outreach…'; }
  if (cancelBtn)  { cancelBtn.disabled  = true; }

  // Status banner inside the panel.
  const personaStatus = document.getElementById('personaStatus');
  if (personaStatus) personaStatus.textContent = '📨 Outreach in progress — sending emails to selected members…';

  // Re-animate every persona graph card so the realtime edge formation is
  // visible during the outreach phase too (idempotent — pgClearGraph wipes
  // the existing nodes/edges before re-drawing).
  document.querySelectorAll('.pgraph-card').forEach(card => {
    const mid = card.id.replace('pgc-','');
    if (window.__lastPersonaCmp && window.__lastPersonaCmp[mid]) {
      animateGraph(mid, window.__lastPersonaCmp[mid]);
    }
  });

  try{
    const res = await fetch('/api/v1/members/bulk-process',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({members:selected})
    });
    const data = await res.json();
    const container=document.getElementById('resultsContainer');
    const results=data.results||[];
    container.innerHTML=results.map(r=>`
      <div class="result-card">
        <div class="icon">${r.status==='completed'?'&#9989;':'&#10060;'}</div>
        <div class="info">
          <div class="name">${r.name} (${r.member_id})</div>
          <div class="detail">${r.status==='completed'?
            (r.email_sent
              ? 'Outreach email sent'
              : (r.email_error
                  ? 'Processed — email failed: ' + r.email_error
                  : 'Processed (no email address on file)')):
            'Error: '+(r.error||'Unknown error')}</div>
        </div>
        <span class="status-badge ${r.status==='completed'?'success':'error'}">${r.status==='completed'?'Completed':'Failed'}</span>
      </div>
    `).join('');
    if (personaStatus) personaStatus.textContent = '✅ Outreach complete — persona graphs above show every member compared with their ideal twin. You can close this modal.';
    if (approveBtn) { approveBtn.disabled = false; approveBtn.textContent = 'Done'; approveBtn.onclick = () => { closeModal(); document.getElementById('uploadArea').style.display='none'; document.getElementById('resultsArea').classList.add('show'); }; }
    if (cancelBtn)  { cancelBtn.disabled  = false; }
    document.getElementById('resultsArea').classList.add('show');
  } catch(e){
    if (personaStatus) personaStatus.textContent = '⚠ Outreach failed: ' + e.message;
    if (approveBtn) { approveBtn.disabled = false; approveBtn.textContent = 'Retry Outreach'; }
    if (cancelBtn)  { cancelBtn.disabled  = false; }
    alert('Outreach failed: '+e.message);
  }
}

async function _legacy_approveAndProcess_unused(){ /* removed — see approveAndProcess */ }

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

        # ── Reconcile compliant measures (prior screenings) ─────────────
        # Two-pass backfill so the timeline always shows prior screenings as
        # closed gaps in the reference DB, regardless of when / how the member
        # was uploaded.
        #
        # Pass A — rulebook-driven: detect_care_gaps() in the main DB tells us
        #   which measures are currently compliant. Anything compliant whose
        #   corresponding ref-DB CareGap is missing or not yet at gap_closed
        #   gets created/updated via sync_compliant_measure().
        #
        # Pass B — claim-driven fallback: scan every PRIOR-* claim attached to
        #   the member and ensure each one has a closed CareGap mirroring it.
        #   This is the safety net for members where detect_care_gaps fails or
        #   the measure isn't in the compliant list (e.g. stale BenefitPlan,
        #   missing diagnosis), so the visualization can still rely on the raw
        #   "the member has a completed screening claim" fact.
        try:
            from src.persona_sync import (
                sync_compliant_measure, _ref, _find_screening_date_from_claims,
            )
            from src.care_gap_neo4j import get_member_claims_cpt_codes
            from src.hedis_golden_reference import HEDIS_MEASURES

            ref = _ref()
            existing = ref.run_query("""
                MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
                RETURN g.measure_id AS measure_id, g.stage AS stage
            """, {"mid": member_id})
            ref_stage_by_measure = {
                r["measure_id"]: r.get("stage")
                for r in existing if r.get("measure_id")
            }
            claims = get_member_claims_cpt_codes(member_id) or []

            compliant_seen: set = set()

            # Pass A — rulebook
            try:
                from src.care_gap_agents import detect_care_gaps
                gap_result = detect_care_gaps(member_id) or {}
                for cmid in (gap_result.get("compliant") or []):
                    compliant_seen.add(cmid)
                    if ref_stage_by_measure.get(cmid) == "gap_closed":
                        continue
                    measure_def = HEDIS_MEASURES.get(cmid) or {}
                    sdate = _find_screening_date_from_claims(measure_def, claims)
                    sync_compliant_measure(
                        member_id=member_id,
                        measure_id=cmid,
                        measure_name=measure_def.get("name", cmid),
                        screening_date=sdate,
                    )
                    logger.info(f"[RECONCILE-A] Backfilled closed gap for {member_id}/{cmid} (date={sdate or 'unknown'})")
            except Exception as ra_err:
                logger.warning(f"[RECONCILE-A] rulebook pass failed for {member_id}: {ra_err}")

            # Pass B — direct PRIOR-* claim scan
            kg = get_knowledge_graph()
            prior_claims = kg.run_query("""
                MATCH (m:Member {member_id: $mid})-[:HAS_CLAIM]->(c:Claim)
                WHERE c.claim_id STARTS WITH 'PRIOR-'
                RETURN c.claim_id AS claim_id, c.cpt_code AS cpt_code,
                       c.service_date AS service_date
            """, {"mid": member_id})
            for pc in prior_claims:
                cid = pc.get("claim_id") or ""
                # Format: PRIOR-{member_id}-{measure_id}
                parts = cid.split("-")
                if len(parts) < 3:
                    continue
                cmid = parts[-1].upper()
                if cmid in compliant_seen and ref_stage_by_measure.get(cmid) == "gap_closed":
                    continue
                if ref_stage_by_measure.get(cmid) == "gap_closed":
                    continue
                measure_def = HEDIS_MEASURES.get(cmid)
                if not measure_def:
                    continue
                sdate = (pc.get("service_date") or "")[:10]
                sync_compliant_measure(
                    member_id=member_id,
                    measure_id=cmid,
                    measure_name=measure_def.get("name", cmid),
                    screening_date=sdate,
                )
                logger.info(f"[RECONCILE-B] Backfilled closed gap from PRIOR claim for {member_id}/{cmid} (date={sdate or 'unknown'})")
        except Exception as comp_err:
            logger.warning(f"[RECONCILE] Compliant-measure reconciliation failed: {comp_err}")

        result = get_member_lifecycle_graph(member_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Reference member personas error: {e}", exc_info=True)
        return jsonify({"nodes": [], "edges": [], "member": None, "lifecycle": []})


@app.route("/api/v1/admin/notify-gap-update", methods=["POST"])
def notify_gap_update():
    """Lightweight hook for external scripts (e.g. close_member_gap.py) to
    push a `care_gap_updated` event into the portal SocketIO channel so any
    open member panel auto-refreshes."""
    try:
        data = request.json or {}
        mid = data.get("member_id")
        if not mid:
            return jsonify({"status": "error", "error": "member_id required"}), 400
        emit_portal_event("care_gap_updated", {
            "member_id": mid,
            "source": data.get("source", "external"),
        })
        return jsonify({"status": "ok", "member_id": mid})
    except Exception as e:
        logger.error(f"notify_gap_update error: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/v1/admin/cleanup-orphans", methods=["POST"])
def cleanup_orphan_records():
    """
    One-shot cleanup of records left behind when Members were deleted from
    the main DB without cascading their dependents. Removes:
      • Outreach nodes with no inbound CONTACTS / TARGETS-to-Member chain
      • CareGap nodes with no inbound HAS_CARE_GAP from any Member
      • Email nodes with no associated Member
      • Appointment nodes orphaned by member deletion
      • Claim nodes orphaned by member deletion

    Returns counts of deleted nodes so the caller can verify. Safe to run
    repeatedly — only deletes nodes that have no living Member parent.
    """
    try:
        kg = get_knowledge_graph()
        deleted = {}

        for label, query in [
            ("outreach", """
                MATCH (o:Outreach)
                WHERE NOT EXISTS { MATCH (o)-[:CONTACTS]->(:Member) }
                  AND NOT EXISTS { MATCH (o)-[:TARGETS]->(:CareGap)<-[:HAS_CARE_GAP]-(:Member) }
                WITH o
                DETACH DELETE o
                RETURN count(o) AS n
            """),
            ("care_gaps", """
                MATCH (g:CareGap)
                WHERE NOT EXISTS { MATCH (:Member)-[:HAS_CARE_GAP]->(g) }
                WITH g
                DETACH DELETE g
                RETURN count(g) AS n
            """),
            ("emails", """
                MATCH (e:Email)
                WHERE NOT EXISTS { MATCH (e)-[:SENT_TO|:RECEIVED_FROM]->(:Member) }
                  AND NOT EXISTS { MATCH (:Member)-[:HAS_EMAIL|:RECEIVED]->(e) }
                WITH e
                DETACH DELETE e
                RETURN count(e) AS n
            """),
            ("appointments", """
                MATCH (a:Appointment)
                WHERE NOT EXISTS { MATCH (:Member)-[:HAS_APPOINTMENT]->(a) }
                WITH a
                DETACH DELETE a
                RETURN count(a) AS n
            """),
            ("claims", """
                MATCH (c:Claim)
                WHERE NOT EXISTS { MATCH (:Member)-[:HAS_CLAIM]->(c) }
                WITH c
                DETACH DELETE c
                RETURN count(c) AS n
            """),
        ]:
            try:
                rows = kg.run_query(query, {})
                deleted[label] = (rows[0]["n"] if rows else 0) or 0
            except Exception as q_err:
                logger.warning(f"[CLEANUP-ORPHANS] {label} query failed: {q_err}")
                deleted[label] = f"error: {q_err}"

        logger.info(f"[CLEANUP-ORPHANS] removed: {deleted}")
        return jsonify({"status": "success", "deleted": deleted})
    except Exception as e:
        logger.error(f"cleanup_orphan_records error: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500


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

# Register mobile APK API Blueprint
from src.mobile_api import mobile_bp
app.register_blueprint(mobile_bp)


@app.route("/api/v1/noshow/trigger", methods=["POST"])
def noshow_trigger():
    """Manual trigger for the no-show sweep (useful for ops/testing)."""
    from src.noshow_scheduler import trigger_now
    try:
        trigger_now()
        return jsonify({"status": "ok"})
    except Exception as exc:
        logger.error(f"no-show trigger failed: {exc}", exc_info=True)
        return jsonify({"status": "error", "error": str(exc)}), 500


if __name__ == "__main__":
    # Make startup banners actually visible regardless of project log config.
    import logging as _logging, os as _boot_os
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("=" * 70)
    print("[BOOT] care_gap_api starting — demo-scope filter:",
          _boot_os.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL (default)"))
    print("=" * 70)

    # Bootstrap persona reference DB schema on startup
    try:
        from src.persona_sync import bootstrap_persona_schema
        bootstrap_persona_schema()
        print("[BOOT] persona reference DB schema ready")
    except Exception as e:
        print(f"[BOOT] persona schema bootstrap skipped: {e}")

    # Backfill prior-screening closed gaps + clean up orphan records left
    # over from previous member deletions. Runs in a background thread so
    # it never blocks server startup. Best-effort.
    try:
        import threading as _bg_t
        def _startup_full_sync():
            # Demo-scope sweep — hard-delete CareGap nodes whose measure is
            # outside CARE_GAP_ENABLED_MEASURES so out-of-scope gaps left
            # over from older uploads never surface in the dashboard /
            # email / PDF on a fresh start.
            try:
                import os as _os_demo
                _enabled_raw_demo = _os_demo.environ.get(
                    "CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL"
                ).strip()
                if _enabled_raw_demo not in ("*", "all", "ALL"):
                    _enabled_demo = [m.strip().upper()
                                     for m in _enabled_raw_demo.split(",") if m.strip()]
                    if _enabled_demo:
                        kg_demo = get_knowledge_graph()
                        rows = kg_demo.run_query("""
                            MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
                            WHERE NOT coalesce(g.measure_id,'') IN $en
                            WITH g, count(g) AS c DETACH DELETE g
                            RETURN sum(c) AS n
                        """, {"en": _enabled_demo})
                        n_demo = (rows[0]["n"] if rows else 0) or 0
                        print(f"[BOOT][STARTUP-DEMO-SCOPE] removed {n_demo} out-of-scope CareGap node(s)")
            except Exception as exc:
                print(f"[BOOT][STARTUP-DEMO-SCOPE] sweep skipped: {exc}")

            # Orphan cleanup first — removes Outreach/CareGap/Claim/Email
            # /Appointment nodes whose Members were deleted, so dashboard
            # counts (e.g. Outreach Activity) self-correct without manual
            # intervention.
            try:
                kg_local = get_knowledge_graph()
                for label, q in [
                    ("outreach", """
                        MATCH (o:Outreach)
                        WHERE NOT EXISTS { MATCH (o)-[:CONTACTS]->(:Member) }
                          AND NOT EXISTS { MATCH (o)-[:TARGETS]->(:CareGap)<-[:HAS_CARE_GAP]-(:Member) }
                        WITH o DETACH DELETE o RETURN count(o) AS n
                    """),
                    ("care_gaps", """
                        MATCH (g:CareGap)
                        WHERE NOT EXISTS { MATCH (:Member)-[:HAS_CARE_GAP]->(g) }
                        WITH g DETACH DELETE g RETURN count(g) AS n
                    """),
                    ("appointments", """
                        MATCH (a:Appointment)
                        WHERE NOT EXISTS { MATCH (:Member)-[:HAS_APPOINTMENT]->(a) }
                        WITH a DETACH DELETE a RETURN count(a) AS n
                    """),
                    ("claims", """
                        MATCH (c:Claim)
                        WHERE NOT EXISTS { MATCH (:Member)-[:HAS_CLAIM]->(c) }
                        WITH c DETACH DELETE c RETURN count(c) AS n
                    """),
                ]:
                    try:
                        rows = kg_local.run_query(q, {})
                        n = (rows[0]["n"] if rows else 0) or 0
                        if n:
                            logger.info(f"[STARTUP-CLEANUP] removed {n} orphan {label}")
                    except Exception as cq_err:
                        logger.warning(f"[STARTUP-CLEANUP] {label} skipped: {cq_err}")
            except Exception as exc:
                logger.warning(f"[STARTUP-CLEANUP] orphan sweep skipped: {exc}")

            # Then refresh ref + persona-demo DBs from the now-clean main DB.
            try:
                from src.persona_sync import sync_all_existing_members
                n = sync_all_existing_members()
                logger.info(f"[STARTUP-SYNC] reference + persona-demo DBs refreshed for {n} members")
            except Exception as exc:
                logger.warning(f"[STARTUP-SYNC] full sync skipped: {exc}")
        _bg_t.Thread(target=_startup_full_sync, daemon=True).start()
    except Exception as e:
        logger.warning(f"Startup full-sync thread failed to start: {e}")

    # Start the no-show auto-cancel + re-outreach scheduler
    try:
        from src.noshow_scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"No-show scheduler failed to start: {e}")

    # Use socketio.run so the Socket.IO async mode (threading/gevent/eventlet)
    # picks the matching server automatically. Eliminates the websocket-upgrade
    # 500s that occur when async_mode and the underlying WSGI server disagree.
    socketio.run(app, debug=True, host="0.0.0.0", port=5001, use_reloader=False,
                 allow_unsafe_werkzeug=True)
