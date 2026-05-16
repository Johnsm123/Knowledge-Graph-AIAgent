"""
Persona Sync Service
====================
Creates and maintains persona-based visualization data in the reference
(persona) Neo4j database.  The original DB and rule-based pipeline are
UNTOUCHED -- this module only writes to the reference DB for the purpose
of rich care-gap lifecycle visualization in the frontend.

Graph schema in reference DB:
  (:Member)  -[:HAS_PERSONA]->  (:Persona)
  (:Member)  -[:HAS_CARE_GAP]-> (:CareGap)  -[:FOR_MEASURE]-> (:Measure)
  (:CareGap) -[:HAS_ACTION]->   (:Action {type: analysis|outreach|appointment|closed})
  (:Member)  -[:HAS_PCP]->      (:Provider)

Lifecycle stages stored on CareGap nodes:
  stage = gap_identified | analysis_started | analysis_complete |
          outreach_sent  | appointment_booked | gap_closed
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _ref():
    """Get reference DB connection."""
    from src.neo4j_connection import get_reference_graph
    return get_reference_graph()


# ═══════════════════════════════════════════════════════════════════════════
#  Schema bootstrap -- run once on startup to create indexes / constraints
# ═══════════════════════════════════════════════════════════════════════════

def bootstrap_persona_schema():
    """Create indexes in the reference DB if they don't already exist."""
    ref = _ref()
    for q in [
        "CREATE INDEX IF NOT EXISTS FOR (m:Member)   ON (m.member_id)",
        "CREATE INDEX IF NOT EXISTS FOR (p:Persona)  ON (p.persona_id)",
        "CREATE INDEX IF NOT EXISTS FOR (g:CareGap)  ON (g.gap_id)",
        "CREATE INDEX IF NOT EXISTS FOR (a:Action)   ON (a.action_id)",
        "CREATE INDEX IF NOT EXISTS FOR (ms:Measure) ON (ms.measure_id)",
        "CREATE INDEX IF NOT EXISTS FOR (pr:Provider) ON (pr.provider_id)",
    ]:
        ref.execute_write(q)
    logger.info("[PERSONA-SYNC] Reference DB schema bootstrapped")


# ═══════════════════════════════════════════════════════════════════════════
#  Member  +  Persona creation
# ═══════════════════════════════════════════════════════════════════════════

def sync_member_persona(member_id: str, name: str, dob: str, gender: str,
                        age_str: str, chronic_conditions: list = None,
                        insurance_type: str = "", pcp_name: str = "",
                        pcp_id: str = ""):
    """
    Mirror a member into the reference DB and create a matching Persona node.
    Called after a member is added / updated in the original DB.
    """
    ref = _ref()
    now = datetime.now().isoformat()

    # Calculate age_years from age_str (e.g. "45 Years, 3 Months")
    age_years = 0
    try:
        if age_str:
            age_years = int(age_str.split()[0])
    except Exception:
        pass

    chronic = chronic_conditions or []
    chronic_str = ", ".join(chronic) if isinstance(chronic, list) else str(chronic)

    # -- Member node ----------------------------------------------------------
    ref.execute_write("""
        MERGE (m:Member {member_id: $mid})
        SET m.name    = $name,
            m.dob     = $dob,
            m.gender  = $gender,
            m.age_str = $age_str,
            m.age_years = $age_years,
            m.chronic_conditions = $chronic,
            m.insurance_type = $insurance,
            m.synced_at = $now
    """, {"mid": member_id, "name": name, "dob": dob, "gender": gender,
          "age_str": age_str, "age_years": age_years, "chronic": chronic_str,
          "insurance": insurance_type, "now": now})

    # -- Provider node --------------------------------------------------------
    if pcp_name or pcp_id:
        prov_id = pcp_id or pcp_name
        ref.execute_write("""
            MERGE (p:Provider {provider_id: $pid})
            SET p.name = $pname
            WITH p
            MATCH (m:Member {member_id: $mid})
            MERGE (m)-[:HAS_PCP]->(p)
        """, {"pid": prov_id, "pname": pcp_name or pcp_id, "mid": member_id})

    # -- Persona node ---------------------------------------------------------
    persona_id = f"PERSONA-{member_id}"
    gender_label = "Female" if gender == "F" else "Male" if gender == "M" else "Unknown"

    # Build a human-readable persona description
    desc_parts = [f"{name}"]
    if age_str:
        desc_parts.append(f"aged {age_str}")
    desc_parts.append(f"({gender_label})")
    if chronic_str:
        desc_parts.append(f"with {chronic_str}")
    if insurance_type:
        desc_parts.append(f"- {insurance_type} plan")
    description = ", ".join(desc_parts)

    ref.execute_write("""
        MERGE (p:Persona {persona_id: $pid})
        SET p.description        = $desc,
            p.gender             = $gender,
            p.gender_criteria_label = $gender_label,
            p.age_years          = $age_years,
            p.age_band_label     = $age_band,
            p.chronic_conditions = $chronic,
            p.insurance_type     = $insurance,
            p.care_gap_status    = 'ACTIVE',
            p.member_id          = $mid,
            p.synced_at          = $now
        WITH p
        MATCH (m:Member {member_id: $mid})
        MERGE (m)-[:HAS_PERSONA]->(p)
    """, {"pid": persona_id, "desc": description, "gender": gender,
          "gender_label": gender_label, "age_years": age_years,
          "age_band": _age_band(age_years), "chronic": chronic_str,
          "insurance": insurance_type, "mid": member_id, "now": now})

    logger.info(f"[PERSONA-SYNC] Synced member {member_id} + persona {persona_id}")
    return persona_id


def set_persona_reasoning(member_id: str, reasoning: str) -> None:
    """Write an LLM-generated 'why this persona matches the member' paragraph
    onto the Persona node so the lifecycle-graph tooltip can display it."""
    if not reasoning:
        return
    ref = _ref()
    ref.execute_write("""
        MATCH (m:Member {member_id: $mid})-[:HAS_PERSONA]->(p:Persona)
        SET p.reasoning = $reasoning
    """, {"mid": member_id, "reasoning": reasoning})


def _age_band(age: int) -> str:
    if age < 18: return "0-17"
    if age < 30: return "18-29"
    if age < 45: return "30-44"
    if age < 55: return "45-54"
    if age < 65: return "55-64"
    return "65+"


# ═══════════════════════════════════════════════════════════════════════════
#  Care-gap lifecycle tracking
# ═══════════════════════════════════════════════════════════════════════════

def reset_member_care_gaps(member_id: str) -> int:
    """Delete every CareGap (+ its Action nodes) attached to this member in
    the reference DB. Used before re-syncing on bulk upload so the reference
    DB never accumulates stale gaps from previous runs and always mirrors
    exactly the open gaps detected in the main DB by the HEDIS rulebook.

    Returns the number of CareGap nodes deleted.
    """
    ref = _ref()
    rows = ref.run_query("""
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        RETURN count(g) AS n
    """, {"mid": member_id})
    n = (rows[0]["n"] if rows else 0) or 0

    # Detach + delete actions first, then care gaps. DETACH DELETE drops
    # all relationships incident to the deleted nodes, so HAS_CARE_GAP /
    # HAS_ACTION / FOR_MEASURE edges go with them.
    ref.execute_write("""
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        OPTIONAL MATCH (g)-[:HAS_ACTION]->(a:Action)
        DETACH DELETE a
    """, {"mid": member_id})
    ref.execute_write("""
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        DETACH DELETE g
    """, {"mid": member_id})
    if n:
        logger.info(f"[PERSONA-SYNC] reset_member_care_gaps: removed {n} stale gap(s) for {member_id}")
    return n


def sync_care_gap(member_id: str, care_gap_id: str, measure_id: str,
                  measure_name: str, status: str = "Open"):
    """Create / update a CareGap node and link it to the Member and Measure.

    Idempotent w.r.t. lifecycle stage: when the gap already exists, the
    stage / identified_at / outreach / appointment / closure timestamps are
    preserved. Only the metadata (measure name, status) is refreshed. This
    is what lets the reference-DB timeline survive a backend restart — the
    startup full-sync no longer rewinds gaps that have already advanced to
    outreach_sent / appointment_booked / gap_closed.
    """
    ref = _ref()
    now = datetime.now().isoformat()

    # Measure node
    ref.execute_write("""
        MERGE (ms:Measure {measure_id: $msid})
        SET ms.name = $msname
    """, {"msid": measure_id, "msname": measure_name})

    # CareGap node — ON CREATE seeds initial stage; ON MATCH preserves it.
    ref.execute_write("""
        MERGE (g:CareGap {gap_id: $gid})
        ON CREATE SET g.stage = 'gap_identified', g.identified_at = $now
        SET g.measure_id   = $msid,
            g.measure_name = $msname,
            g.status       = $status
        WITH g
        MATCH (m:Member {member_id: $mid})
        MERGE (m)-[:HAS_CARE_GAP]->(g)
        WITH g
        MATCH (ms:Measure {measure_id: $msid})
        MERGE (g)-[:FOR_MEASURE]->(ms)
    """, {"gid": care_gap_id, "msid": measure_id, "msname": measure_name,
          "status": status, "mid": member_id, "now": now})

    # Only emit the "Gap Identified" action if the gap is still at that
    # stage — re-syncing a gap that already advanced shouldn't append another
    # identified action and reset the timeline.
    cur = ref.run_query(
        "MATCH (g:CareGap {gap_id: $gid}) RETURN g.stage AS stage",
        {"gid": care_gap_id},
    )
    cur_stage = (cur[0]["stage"] if cur else None)
    if cur_stage in (None, "gap_identified"):
        _add_action(care_gap_id, "identified", "Care gap identified by rule engine",
                    stage="gap_identified")

    logger.info(f"[PERSONA-SYNC] Care gap {care_gap_id} synced for {member_id} (stage={cur_stage})")


def sync_compliant_measure(member_id: str, measure_id: str, measure_name: str,
                           screening_date: str = ""):
    """
    Mirror a HEDIS measure that the member has *already* satisfied (e.g. via
    a PriorScreenings claim loaded during bulk upload, or any other completed
    claim within the lookback window) into the reference DB as a CLOSED
    CareGap node.

    The reference DB exists purely for visualization. The main DB's golden
    rulebook decides "this isn't a gap because the member is compliant", and
    we want the timeline to reflect that fact: a brief "Gap Identified → Gap
    Closed" lifecycle dated on the screening service date, so the care
    manager sees both the still-open gaps AND the compliant ones in one
    unified view, exactly matching what the rulebook says.
    """
    ref = _ref()
    now = datetime.now().isoformat()
    sd = (screening_date or "")[:10]
    iso_date = (sd + "T00:00:00") if sd else now

    # Stable ID per (member, measure) so re-running the sync is idempotent
    # and never creates duplicate closed gaps for the same prior screening.
    care_gap_id = f"PRIOR-{member_id}-{measure_id}"

    # Guard against duplicate timeline entries: if a CareGap already exists
    # for this (member, measure) under any id (e.g. an AUTO-* gap created
    # by sync_care_gap that subsequently advanced to gap_closed via the
    # outreach → appointment workflow), don't create a second PRIOR-* stub
    # alongside it. The existing one is the source of truth.
    existing = ref.run_query("""
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        WHERE g.measure_id = $msid
        RETURN g.gap_id AS gap_id, g.stage AS stage
        LIMIT 1
    """, {"mid": member_id, "msid": measure_id})
    if existing:
        logger.info(
            f"[PERSONA-SYNC] Skipping PRIOR sync for {member_id}/{measure_id} "
            f"— existing gap {existing[0]['gap_id']} already at stage "
            f"{existing[0]['stage']}"
        )
        return existing[0]["gap_id"]

    ref.execute_write("""
        MERGE (ms:Measure {measure_id: $msid})
        SET ms.name = $msname
    """, {"msid": measure_id, "msname": measure_name})

    ref.execute_write("""
        MERGE (g:CareGap {gap_id: $gid})
        SET g.measure_id    = $msid,
            g.measure_name  = $msname,
            g.status        = 'Closed',
            g.stage         = 'gap_closed',
            g.identified_at = $iso,
            g.closed_at     = $iso,
            g.source        = 'prior_screening'
        WITH g
        MATCH (m:Member {member_id: $mid})
        MERGE (m)-[:HAS_CARE_GAP]->(g)
        WITH g
        MATCH (ms:Measure {measure_id: $msid})
        MERGE (g)-[:FOR_MEASURE]->(ms)
    """, {"gid": care_gap_id, "msid": measure_id, "msname": measure_name,
          "iso": iso_date, "mid": member_id})

    _add_action(care_gap_id, "identified",
                f"Prior screening on file for {measure_name}",
                stage="gap_identified")
    _add_action(care_gap_id, "closed",
                f"Care gap closed — screening completed on {sd or 'a prior date'}",
                stage="gap_closed")

    logger.info(
        f"[PERSONA-SYNC] Compliant measure {measure_id} synced as CLOSED gap for {member_id}"
    )
    return care_gap_id


def _find_screening_date_from_claims(measure: dict, claims: list) -> str:
    """Return the most recent service_date from claims whose CPT matches one
    of the measure's accepted codes. Used when backfilling existing members
    where we don't have the original PriorScreenings excel mapping."""
    if not measure or not claims:
        return ""
    accepted = set()
    for key, codes in (measure.get("codes") or {}).items():
        kl = (key or "").lower()
        if isinstance(codes, list) and ("cpt" in kl or "hcpcs" in kl):
            for c in codes:
                if c:
                    accepted.add(str(c).strip())
    primary = (measure.get("primary_cpt") or "").strip()
    if primary:
        accepted.add(primary)
    for opt in (measure.get("screening_options") or []):
        for c in list(opt.get("cpt") or []) + list(opt.get("hcpcs") or []):
            if c:
                accepted.add(str(c).strip())

    # Claims come back ordered by service_date DESC, so the first match is
    # the most recent service date.
    for c in claims:
        if (c.get("cpt_code") or "").strip() in accepted:
            return (c.get("service_date") or "")[:10]
    return ""


def sync_analysis_started(member_id: str, care_gap_id: str = None):
    """Mark that agent analysis has started for a member's care gaps."""
    ref = _ref()
    now = datetime.now().isoformat()

    if care_gap_id:
        ref.execute_write("""
            MATCH (g:CareGap {gap_id: $gid})
            SET g.stage = 'analysis_started', g.analysis_started_at = $now
        """, {"gid": care_gap_id, "now": now})
        _add_action(care_gap_id, "analysis_start", "AI agent analysis initiated",
                    stage="analysis_started")
    else:
        # Update all open gaps for this member
        ref.execute_write("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.status = 'Open'
            SET g.stage = 'analysis_started', g.analysis_started_at = $now
        """, {"mid": member_id, "now": now})


def sync_analysis_complete(member_id: str, care_gap_id: str = None,
                           summary: str = ""):
    """Mark that analysis is complete for a member's care gaps."""
    ref = _ref()
    now = datetime.now().isoformat()

    if care_gap_id:
        ref.execute_write("""
            MATCH (g:CareGap {gap_id: $gid})
            SET g.stage = 'analysis_complete', g.analysis_completed_at = $now
        """, {"gid": care_gap_id, "now": now})
        _add_action(care_gap_id, "analysis_done",
                    summary[:200] or "AI analysis completed with recommendations",
                    stage="analysis_complete")
    else:
        ref.execute_write("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.stage = 'analysis_started'
            SET g.stage = 'analysis_complete', g.analysis_completed_at = $now
        """, {"mid": member_id, "now": now})
        # Create action for each gap
        gaps = ref.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.stage = 'analysis_complete'
            RETURN g.gap_id AS gap_id
        """, {"mid": member_id})
        for g in gaps:
            _add_action(g["gap_id"], "analysis_done",
                        summary[:200] or "AI analysis completed",
                        stage="analysis_complete")


def sync_outreach_sent(member_id: str, care_gap_id: str = None,
                       channel: str = "Email"):
    """Mark that outreach has been sent."""
    ref = _ref()
    now = datetime.now().isoformat()

    if care_gap_id:
        ref.execute_write("""
            MATCH (g:CareGap {gap_id: $gid})
            SET g.stage = 'outreach_sent', g.outreach_sent_at = $now,
                g.outreach_channel = $channel
        """, {"gid": care_gap_id, "now": now, "channel": channel})
        _add_action(care_gap_id, "outreach",
                    f"Outreach sent via {channel}", stage="outreach_sent")
    else:
        ref.execute_write("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.status = 'Open'
            SET g.stage = 'outreach_sent', g.outreach_sent_at = $now,
                g.outreach_channel = $channel
        """, {"mid": member_id, "now": now, "channel": channel})
        gaps = ref.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
            WHERE g.stage = 'outreach_sent'
            RETURN g.gap_id AS gap_id
        """, {"mid": member_id})
        for g in gaps:
            _add_action(g["gap_id"], "outreach",
                        f"Outreach sent via {channel}", stage="outreach_sent")


def sync_appointment_booked(member_id: str, care_gap_id: str,
                            appointment_id: str = "", appointment_date: str = "",
                            lab_location: str = ""):
    """Mark that an appointment has been booked for this gap."""
    ref = _ref()
    now = datetime.now().isoformat()

    # Verify the gap exists first
    check = ref.run_query(
        "MATCH (g:CareGap {gap_id: $gid}) RETURN g.gap_id AS gid, g.stage AS stage",
        {"gid": care_gap_id}
    )
    logger.info(f"[PERSONA-SYNC] Appointment booking — gap lookup for '{care_gap_id}': {check}")

    if not check:
        logger.warning(f"[PERSONA-SYNC] CareGap '{care_gap_id}' NOT FOUND in reference DB — creating it now")
        # Auto-create the gap node so we can still track the appointment
        ref.execute_write("""
            MERGE (g:CareGap {gap_id: $gid})
            SET g.status = 'Open', g.stage = 'outreach_sent',
                g.identified_at = $now
            WITH g
            MATCH (m:Member {member_id: $mid})
            MERGE (m)-[:HAS_CARE_GAP]->(g)
        """, {"gid": care_gap_id, "mid": member_id, "now": now})

    ref.execute_write("""
        MATCH (g:CareGap {gap_id: $gid})
        SET g.stage = 'appointment_booked', g.appointment_booked_at = $now,
            g.appointment_id = $appt_id, g.appointment_date = $appt_date,
            g.lab_location = $lab
    """, {"gid": care_gap_id, "now": now, "appt_id": appointment_id,
          "appt_date": appointment_date, "lab": lab_location})

    _add_action(care_gap_id, "appointment",
                f"Appointment booked — {appointment_date} at {lab_location}",
                stage="appointment_booked")

    logger.info(f"[PERSONA-SYNC] Appointment booked for gap {care_gap_id}")


def sync_appointment_cancelled(member_id: str, care_gap_id: str,
                               appointment_id: str = "", appointment_date: str = "",
                               cancelled_by: str = "member"):
    """Record an appointment cancellation in the reference DB so the timeline reflects it."""
    ref = _ref()
    now = datetime.now().isoformat()

    if care_gap_id:
        ref.execute_write("""
            MATCH (g:CareGap {gap_id: $gid})
            SET g.stage = 'appointment_cancelled',
                g.last_cancelled_at = $now,
                g.last_cancelled_appointment_id = $appt_id
        """, {"gid": care_gap_id, "now": now, "appt_id": appointment_id})

        _add_action(care_gap_id, "appointment_cancelled",
                    f"Appointment cancelled by {cancelled_by} ({appointment_date or 'unknown date'})",
                    stage="appointment_cancelled")

    logger.info(f"[PERSONA-SYNC] Appointment {appointment_id} cancelled for gap {care_gap_id}")


def sync_appointment_no_show(member_id: str, care_gap_id: str,
                             appointment_id: str = "", appointment_date: str = ""):
    """Record a no-show event in the reference DB timeline."""
    ref = _ref()
    now = datetime.now().isoformat()

    if care_gap_id:
        ref.execute_write("""
            MATCH (g:CareGap {gap_id: $gid})
            SET g.stage = 'appointment_no_show',
                g.last_no_show_at = $now,
                g.last_no_show_appointment_id = $appt_id
        """, {"gid": care_gap_id, "now": now, "appt_id": appointment_id})

        _add_action(care_gap_id, "appointment_no_show",
                    f"Member missed appointment on {appointment_date or 'unknown date'}",
                    stage="appointment_no_show")

    logger.info(f"[PERSONA-SYNC] No-show recorded for {appointment_id} on gap {care_gap_id}")


def sync_gap_closed(member_id: str, care_gap_id: str):
    """Mark a care gap as closed."""
    ref = _ref()
    now = datetime.now().isoformat()

    # Verify the gap exists; create if missing
    check = ref.run_query(
        "MATCH (g:CareGap {gap_id: $gid}) RETURN g.gap_id AS gid, g.stage AS stage",
        {"gid": care_gap_id}
    )
    logger.info(f"[PERSONA-SYNC] Gap closure — gap lookup for '{care_gap_id}': {check}")

    if not check:
        logger.info(f"[PERSONA-SYNC] CareGap '{care_gap_id}' missing in reference DB — auto-creating as closed (self-heal, expected)")
        ref.execute_write("""
            MERGE (g:CareGap {gap_id: $gid})
            SET g.status = 'Open', g.stage = 'appointment_booked',
                g.identified_at = $now
            WITH g
            MATCH (m:Member {member_id: $mid})
            MERGE (m)-[:HAS_CARE_GAP]->(g)
        """, {"gid": care_gap_id, "mid": member_id, "now": now})

    ref.execute_write("""
        MATCH (g:CareGap {gap_id: $gid})
        SET g.stage = 'gap_closed', g.status = 'Closed', g.closed_at = $now
    """, {"gid": care_gap_id, "now": now})

    _add_action(care_gap_id, "closed", "Care gap resolved and closed",
                stage="gap_closed")

    # Update persona status
    ref.execute_write("""
        MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap {gap_id: $gid})
        WITH m, count { (m)-[:HAS_CARE_GAP]->(g2:CareGap) WHERE g2.status = 'Open' } AS open_count
        MATCH (m)-[:HAS_PERSONA]->(p:Persona)
        SET p.care_gap_status = CASE WHEN open_count = 0 THEN 'COMPLIANT' ELSE 'ACTIVE' END
    """, {"gid": care_gap_id})

    logger.info(f"[PERSONA-SYNC] Gap {care_gap_id} closed for {member_id}")


# ═══════════════════════════════════════════════════════════════════════════
#  Bulk sync -- sync all existing members into the reference DB
# ═══════════════════════════════════════════════════════════════════════════

def sync_all_existing_members(preserve_progress: bool = True):
    """
    Full re-sync: for every Member in the main DB, rebuild the reference DB
    and persona-demo DB so they exactly mirror the rulebook's view —
    open gaps as Open, prior-screening compliant measures as Closed gaps,
    and a fresh IdealPersona twin in the persona-demo DB.

    `preserve_progress` (default True): if True, existing reference-DB
    CareGap nodes are kept intact so their lifecycle stage (outreach_sent /
    appointment_booked / gap_closed) survives the re-sync. This is what
    the backend-restart path uses so reopening a member panel after a
    server restart still shows the timeline at the stage it had reached.

    Pass `preserve_progress=False` only when you actually want a hard reset
    (e.g. an explicit admin "rebuild from scratch" action).
    """
    from src.neo4j_connection import get_knowledge_graph
    from src.care_gap_neo4j import (
        get_member_open_gaps, get_member_profile,
        get_member_claims_cpt_codes,
        get_member_family_history, get_member_medical_history,
        get_member_lifestyle,
    )
    from src.care_gap_agents import detect_care_gaps
    from src.hedis_golden_reference import HEDIS_MEASURES

    kg = get_knowledge_graph()
    members = kg.run_query("""
        MATCH (m:Member)
        OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
        RETURN m.member_id AS member_id, m.name AS name, m.dob AS dob,
               m.gender AS gender, m.age_str AS age_str,
               m.chronic_conditions AS chronic_conditions,
               m.insurance_type AS insurance_type,
               p.name AS pcp_name, m.pcp_id AS pcp_id
    """)

    count = 0
    for mem in members:
        mid = mem["member_id"]
        chronic = mem.get("chronic_conditions") or []
        if isinstance(chronic, str):
            chronic = [c.strip() for c in chronic.split(",") if c.strip()]

        # Wipe any stale reference-DB gaps from previous runs — only when
        # the caller explicitly asked for a hard reset. Default behaviour
        # preserves the lifecycle stage so a server restart doesn't rewind
        # the member-panel timeline.
        if not preserve_progress:
            reset_member_care_gaps(mid)

        sync_member_persona(
            member_id=mid,
            name=mem.get("name", ""),
            dob=mem.get("dob", ""),
            gender=mem.get("gender", ""),
            age_str=mem.get("age_str", ""),
            chronic_conditions=chronic,
            insurance_type=mem.get("insurance_type", ""),
            pcp_name=mem.get("pcp_name", ""),
            pcp_id=mem.get("pcp_id", ""),
        )

        # Re-detect against the rulebook so we know which measures are open
        # vs compliant right now (idempotent — closes stale opens, no-op
        # for already-compliant).
        try:
            gap_result = detect_care_gaps(mid) or {}
        except Exception as exc:
            logger.warning(f"[PERSONA-SYNC] detect_care_gaps failed for {mid}: {exc}")
            gap_result = {}

        # Open gaps → Open CareGap nodes
        open_gaps = get_member_open_gaps(mid)
        for g in open_gaps:
            sync_care_gap(
                member_id=mid,
                care_gap_id=g["care_gap_id"],
                measure_id=g["measure_id"],
                measure_name=g.get("measure_name", g["measure_id"]),
            )

        # Compliant measures → Closed CareGap nodes (timeline shows them
        # as Gap Identified → Gap Closed on the screening service date).
        claims = get_member_claims_cpt_codes(mid) or []
        completed_for_persona = []
        for compliant_id in (gap_result.get("compliant") or []):
            measure_def = HEDIS_MEASURES.get(compliant_id) or {}
            measure_name = measure_def.get("name", compliant_id)
            screening_date = _find_screening_date_from_claims(measure_def, claims)
            sync_compliant_measure(
                member_id=mid,
                measure_id=compliant_id,
                measure_name=measure_name,
                screening_date=screening_date,
            )
            completed_for_persona.append({
                "measure_id":       compliant_id,
                "measure_name":     measure_name,
                "primary_cpt_code": measure_def.get("primary_cpt", ""),
                "primary_icd10":    measure_def.get("primary_icd10", ""),
            })

        # Refresh the persona-demo DB twin so its pending/completed
        # screenings exactly match the rulebook view too.
        try:
            from src.persona_demo_writer import (
                build_persona_comparison, push_member_persona,
            )
            profile_pd = get_member_profile(mid) or {"member_id": mid, "name": mem.get("name", "")}
            profile_pd["member_id"] = mid
            cmp = build_persona_comparison(
                profile_pd,
                open_gaps,
                completed=completed_for_persona,
                family_history=get_member_family_history(mid) or [],
                medical_history=get_member_medical_history(mid) or {},
                lifestyle=get_member_lifestyle(mid) or {},
            )
            push_member_persona(profile_pd, cmp)
        except Exception as pd_err:
            logger.warning(f"[PERSONA-SYNC] persona-demo refresh failed for {mid}: {pd_err}")

        count += 1

    logger.info(f"[PERSONA-SYNC] Bulk synced {count} members to reference + persona-demo DBs")
    return count


# ═══════════════════════════════════════════════════════════════════════════
#  Internal helper
# ═══════════════════════════════════════════════════════════════════════════

def _add_action(care_gap_id: str, action_type: str, description: str,
                stage: str = ""):
    """Add an Action node linked to a CareGap for lifecycle tracking."""
    import uuid
    ref = _ref()
    action_id = f"ACT-{action_type[:4].upper()}-{uuid.uuid4().hex[:6]}"
    now = datetime.now().isoformat()

    ref.execute_write("""
        MATCH (g:CareGap {gap_id: $gid})
        CREATE (a:Action {
            action_id:   $aid,
            type:        $atype,
            description: $desc,
            stage:       $stage,
            timestamp:   $now
        })
        CREATE (g)-[:HAS_ACTION]->(a)
    """, {"gid": care_gap_id, "aid": action_id, "atype": action_type,
          "desc": description, "stage": stage, "now": now})


# ═══════════════════════════════════════════════════════════════════════════
#  Graph data fetchers for the visualization endpoints
# ═══════════════════════════════════════════════════════════════════════════

def get_dashboard_graph():
    """
    Return the full persona-based graph for the dashboard visualization.
    Returns nodes + edges with care gap lifecycle stages.
    """
    ref = _ref()
    nodes = []
    edges = []
    seen = set()

    def add(n):
        if n and n.get("id") and n["id"] not in seen:
            seen.add(n["id"])
            nodes.append(n)

    # Measures
    measures = ref.run_query("MATCH (ms:Measure) RETURN ms")
    for row in measures:
        ms = row["ms"]
        add({"id": ms["measure_id"], "label": "Measure",
             "name": ms.get("name", ms["measure_id"]),
             "measure_id": ms["measure_id"]})

    # All synced members (reference DB)
    members = ref.run_query("""
        MATCH (m:Member)
        WITH m ORDER BY m.synced_at DESC
        OPTIONAL MATCH (m)-[:HAS_PCP]->(prov:Provider)
        OPTIONAL MATCH (m)-[:HAS_PERSONA]->(p:Persona)
        OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)-[:FOR_MEASURE]->(ms:Measure)
        RETURN m {.member_id, .name, .gender, .age_years, .age_str,
                  .chronic_conditions, .insurance_type} AS member,
               prov {.provider_id, .name} AS provider,
               p {.persona_id, .description, .care_gap_status, .age_band_label,
                  .gender_criteria_label} AS persona,
               collect(DISTINCT g {.gap_id, .status, .stage, .measure_id,
                                   .measure_name}) AS care_gaps,
               collect(DISTINCT ms.measure_id) AS gap_measures
    """)

    for row in members:
        mem = row["member"]
        if not mem:
            continue
        add({"id": mem["member_id"], "label": "Member",
             "name": mem["name"], "gender": mem["gender"],
             "age": mem.get("age_years"), "age_str": mem.get("age_str"),
             "chronic_conditions": mem.get("chronic_conditions"),
             "insurance_type": mem.get("insurance_type"),
             "member_id": mem["member_id"]})

        # Provider
        prov = row.get("provider")
        if prov and prov.get("name"):
            pid = prov.get("provider_id") or prov["name"]
            add({"id": pid, "label": "Provider",
                 "name": prov["name"]})
            edges.append({"source": mem["member_id"], "target": pid,
                          "type": "HAS_PCP"})

        # Persona
        persona = row.get("persona")
        if persona and persona.get("persona_id"):
            add({"id": persona["persona_id"], "label": "Persona",
                 "name": persona["persona_id"],
                 "description": persona.get("description"),
                 "care_gap_status": persona.get("care_gap_status"),
                 "age_band": persona.get("age_band_label"),
                 "gender": persona.get("gender_criteria_label")})
            edges.append({"source": mem["member_id"],
                          "target": persona["persona_id"],
                          "type": "HAS_PERSONA"})

        # CareGaps
        for cg in (row.get("care_gaps") or []):
            if not cg or not cg.get("gap_id"):
                continue
            add({"id": cg["gap_id"], "label": "CareGap",
                 "name": cg.get("measure_name") or cg["gap_id"],
                 "status": cg["status"], "stage": cg.get("stage"),
                 "measure": cg.get("measure_id")})
            edges.append({"source": mem["member_id"],
                          "target": cg["gap_id"],
                          "type": "HAS_CARE_GAP"})
            # CareGap → Measure
            if cg.get("measure_id"):
                edges.append({"source": cg["gap_id"],
                              "target": cg["measure_id"],
                              "type": "FOR_MEASURE"})

    # Deduplicate edges
    unique_edges = []
    edge_set = set()
    for e in edges:
        key = (e["source"], e["target"], e["type"])
        if key not in edge_set:
            edge_set.add(key)
            unique_edges.append(e)

    return {"nodes": nodes, "edges": unique_edges}


def get_member_lifecycle_graph(member_id: str):
    """
    Return the full persona + care-gap lifecycle graph for a specific member.
    Includes Action nodes showing each step of the care gap journey.
    """
    ref = _ref()
    nodes = []
    edges = []
    seen = set()

    def add(n):
        if n and n.get("id") and n["id"] not in seen:
            seen.add(n["id"])
            nodes.append(n)

    # Member + Persona + Provider
    data = ref.run_query("""
        MATCH (m:Member {member_id: $mid})
        OPTIONAL MATCH (m)-[:HAS_PCP]->(prov:Provider)
        OPTIONAL MATCH (m)-[:HAS_PERSONA]->(p:Persona)
        RETURN m {.member_id, .name, .gender, .age_years, .age_str,
                  .chronic_conditions, .insurance_type} AS member,
               prov {.provider_id, .name} AS provider,
               p {.persona_id, .description, .care_gap_status,
                  .age_band_label, .gender_criteria_label, .reasoning} AS persona
    """, {"mid": member_id})

    if not data or not data[0].get("member"):
        return {"nodes": [], "edges": [], "member": None, "lifecycle": []}

    mem = data[0]["member"]
    add({"id": mem["member_id"], "label": "Member",
         "name": mem["name"], "gender": mem["gender"],
         "age": mem.get("age_years"), "age_str": mem.get("age_str"),
         "chronic_conditions": mem.get("chronic_conditions"),
         "insurance_type": mem.get("insurance_type")})

    prov = data[0].get("provider")
    if prov and prov.get("name"):
        pid = prov.get("provider_id") or prov["name"]
        add({"id": pid, "label": "Provider", "name": prov["name"]})
        edges.append({"source": mem["member_id"], "target": pid, "type": "HAS_PCP"})

    persona = data[0].get("persona")
    if persona and persona.get("persona_id"):
        add({"id": persona["persona_id"], "label": "Persona",
             "name": persona["persona_id"],
             "description": persona.get("description"),
             "care_gap_status": persona.get("care_gap_status"),
             "age_band": persona.get("age_band_label"),
             "gender": persona.get("gender_criteria_label"),
             "reasoning": persona.get("reasoning")})
        edges.append({"source": mem["member_id"],
                      "target": persona["persona_id"],
                      "type": "HAS_PERSONA"})

    # Care gaps + Actions (lifecycle)
    gaps = ref.run_query("""
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        OPTIONAL MATCH (g)-[:FOR_MEASURE]->(ms:Measure)
        OPTIONAL MATCH (g)-[:HAS_ACTION]->(a:Action)
        WITH g, ms, collect(a {.action_id, .type, .description, .stage,
                               .timestamp}) AS actions
        ORDER BY g.gap_id
        RETURN g {.gap_id, .status, .stage, .measure_id, .measure_name,
                  .identified_at, .analysis_started_at, .analysis_completed_at,
                  .outreach_sent_at, .outreach_channel, .appointment_booked_at,
                  .appointment_id, .appointment_date, .lab_location,
                  .closed_at} AS gap,
               ms {.measure_id, .name} AS measure,
               actions
    """, {"mid": member_id})

    lifecycle = []

    for row in gaps:
        g = row["gap"]
        if not g or not g.get("gap_id"):
            continue

        ms = row.get("measure")
        if ms and ms.get("measure_id"):
            add({"id": ms["measure_id"], "label": "Measure",
                 "name": ms.get("name", ms["measure_id"]),
                 "measure_id": ms["measure_id"]})

        add({"id": g["gap_id"], "label": "CareGap",
             "name": g.get("measure_name") or g["gap_id"],
             "status": g["status"], "stage": g.get("stage"),
             "measure": g.get("measure_id")})
        edges.append({"source": mem["member_id"],
                      "target": g["gap_id"],
                      "type": "HAS_CARE_GAP"})
        if ms and ms.get("measure_id"):
            edges.append({"source": g["gap_id"],
                          "target": ms["measure_id"],
                          "type": "FOR_MEASURE"})

        # Action nodes
        actions = sorted(row.get("actions") or [],
                         key=lambda a: a.get("timestamp", ""))
        for act in actions:
            if not act or not act.get("action_id"):
                continue
            add({"id": act["action_id"], "label": "Action",
                 "name": act.get("type", "").replace("_", " ").title(),
                 "description": act.get("description"),
                 "action_type": act.get("type"),
                 "stage": act.get("stage"),
                 "timestamp": act.get("timestamp")})
            edges.append({"source": g["gap_id"],
                          "target": act["action_id"],
                          "type": "HAS_ACTION"})

        # Build lifecycle timeline for this gap
        lifecycle.append({
            "gap_id": g["gap_id"],
            "measure_id": g.get("measure_id"),
            "measure_name": g.get("measure_name"),
            "status": g["status"],
            "stage": g.get("stage", "gap_identified"),
            "identified_at": g.get("identified_at"),
            "analysis_started_at": g.get("analysis_started_at"),
            "analysis_completed_at": g.get("analysis_completed_at"),
            "outreach_sent_at": g.get("outreach_sent_at"),
            "outreach_channel": g.get("outreach_channel"),
            "appointment_booked_at": g.get("appointment_booked_at"),
            "appointment_date": g.get("appointment_date"),
            "lab_location": g.get("lab_location"),
            "closed_at": g.get("closed_at"),
            "actions": actions,
        })

    # Deduplicate edges
    unique_edges = []
    edge_set = set()
    for e in edges:
        key = (e["source"], e["target"], e["type"])
        if key not in edge_set:
            edge_set.add(key)
            unique_edges.append(e)

    return {
        "member": mem,
        "nodes": nodes,
        "edges": unique_edges,
        "lifecycle": lifecycle,
    }
