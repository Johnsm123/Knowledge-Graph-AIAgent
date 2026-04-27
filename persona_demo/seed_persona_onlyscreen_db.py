"""
Persona-Comparison Demo Seeder
==============================
Bootstraps a *separate, isolated* Neo4j Aura instance with a persona-comparison
view of every member that exists in the main DB.

Goal of the demo
----------------
For each Member, create an :IdealPersona twin (same demographics, but with every
applicable HEDIS screening already completed). Then wire relationships so that
"pending care gaps" are derivable visually as the *difference* between
the persona's completed set and the member's completed set.

Schema written into the demo DB:

    (:Member)        -[:COMPARED_TO]->        (:IdealPersona)
    (:IdealPersona)  -[:WOULD_HAVE_COMPLETED]->  (:Screening)
    (:Member)        -[:HAS_COMPLETED]->      (:Screening)
    (:Member)        -[:HAS_PENDING]->        (:Screening)
    (:Member)        -[:EXCLUDED_FROM]->      (:Screening)

Where :Screening is a HEDIS measure node carrying primary CPT, ICD, age range,
gender requirement, lookback months, and exclusion rules — populated from the
golden reference (`hedis_golden_reference.HEDIS_MEASURES`).

NOT touched by this script
--------------------------
  - The main Neo4j DB (read-only access only)
  - The current reference (persona) DB used by the portal
  - Any application routes, schedulers, env vars, or deploy artifacts

This script is opt-in. Run only when invoked manually:

    python persona_demo/seed_persona_demo_db.py

It reads the demo-DB credentials from environment variables, NEVER from code:

    NEO4J_PERSONA_URI       neo4j+s://<your-id>.databases.neo4j.io
    NEO4J_PERSONA_USER      neo4j
    NEO4J_PERSONA_PASSWORD  ********

You can also drop them into  persona_demo/.env.persona-demo  (gitignored) and
the script will load them automatically.

Idempotent — re-running the script clears the demo DB and rebuilds it.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any

# Make the repo root importable so we can reuse the existing rules engine.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("persona-demo")


# ─── Credential loader ───────────────────────────────────────────────────────

def _load_env_file(path: str) -> None:
    """Tiny .env loader (no python-dotenv dependency)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _demo_db_creds() -> tuple[str, str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    _load_env_file(os.path.join(here, ".env.persona-demo"))
    uri = os.environ.get("NEO4J_PERSONA_URI", "")
    user = os.environ.get("NEO4J_PERSONA_USER", "")
    pw = os.environ.get("NEO4J_PERSONA_PASSWORD", "")
    if not (uri and user and pw):
        raise RuntimeError(
            "Persona-demo DB credentials missing. Set NEO4J_PERSONA_URI / "
            "NEO4J_PERSONA_USER / NEO4J_PERSONA_PASSWORD as env vars OR put them "
            "in persona_demo/.env.persona-demo (see .env.persona-demo.example)."
        )
    return uri, user, pw


# ─── Main DB reader (read-only) ──────────────────────────────────────────────

def _read_main_db() -> dict[str, Any]:
    """Pull every Member + their claims + their open/closed gaps from the main DB."""
    from src.neo4j_connection import get_knowledge_graph
    kg = get_knowledge_graph()
    members = kg.run_query("""
        MATCH (m:Member)
        OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
        RETURN m.member_id            AS member_id,
               m.name                 AS name,
               m.dob                  AS dob,
               m.gender               AS gender,
               m.age_str              AS age_str,
               m.email                AS email,
               m.chronic_conditions   AS chronic_conditions,
               m.pcp_id               AS pcp_id,
               m.zip_code             AS zip_code,
               m.insurance_type       AS insurance_type,
               p.name                 AS pcp_name,
               p.specialty            AS pcp_specialty
        ORDER BY m.member_id
    """) or []
    claims = kg.run_query("""
        MATCH (m:Member)-[:HAS_CLAIM]->(c:Claim)
        RETURN m.member_id   AS member_id,
               c.cpt_code    AS cpt_code,
               c.icd_code    AS icd_code,
               c.service_date AS service_date,
               c.status      AS status
    """) or []
    gaps = kg.run_query("""
        MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        RETURN m.member_id          AS member_id,
               q.measure_id         AS measure_id,
               g.is_open            AS is_open,
               g.gap_status         AS gap_status,
               g.created_on         AS created_on,
               g.closed_on          AS closed_on,
               g.primary_cpt_code   AS primary_cpt,
               g.primary_icd10      AS primary_icd
    """) or []

    log.info("[MAIN] read %d members, %d claims, %d care-gaps", len(members), len(claims), len(gaps))

    claims_by_member: dict[str, list[dict]] = {}
    for c in claims:
        claims_by_member.setdefault(c["member_id"], []).append(c)
    gaps_by_member: dict[str, list[dict]] = {}
    for g in gaps:
        gaps_by_member.setdefault(g["member_id"], []).append(g)

    return {"members": members, "claims_by_member": claims_by_member, "gaps_by_member": gaps_by_member}


# ─── Per-member rule evaluation (re-uses the deterministic engine) ───────────

def _evaluate_member(profile: dict, claims: list[dict]) -> dict[str, list]:
    """Returns {applicable, completed, pending, excluded} sets of measure_ids
    by re-running the same logic the production rules engine uses.
    """
    from src.hedis_golden_reference import HEDIS_MEASURES
    from src.care_gap_agents import (
        _measure_applies, _is_member_excluded_golden,
        _gap_already_satisfied, _gap_satisfied_multi_option,
        _measure_to_flat_dict, _parse_age, _icd_codes_from_conditions,
    )

    age = _parse_age(profile.get("age_str") or "0")
    gender = str(profile.get("gender") or "")
    claim_icd = [c.get("icd_code", "") for c in claims if c.get("icd_code")]
    claim_cpt = [c.get("cpt_code", "") for c in claims if c.get("cpt_code")]
    cond_icd = _icd_codes_from_conditions(profile.get("chronic_conditions") or [])
    icd_codes = list(set(claim_icd + cond_icd))

    applicable: list[str] = []
    completed: list[str] = []
    pending: list[str] = []
    excluded: list[tuple[str, str]] = []  # (measure_id, reason)

    for mid, raw in HEDIS_MEASURES.items():
        if not _measure_applies(raw, age, gender, icd_codes):
            continue
        applicable.append(mid)
        if _is_member_excluded_golden(raw, icd_codes, claim_cpt):
            ex_types = [e.get("type", "excluded") for e in (raw.get("exclusions", {}) or {}).get("required", []) or []]
            reason = ex_types[0] if ex_types else "excluded"
            excluded.append((mid, reason))
            continue
        flat = _measure_to_flat_dict(mid, raw)
        opts = flat.get("screening_options", [])
        satisfied = (
            _gap_satisfied_multi_option(claims, opts) if opts
            else _gap_already_satisfied(claims, flat.get("cpt_codes", ""), int(flat.get("lookback_months") or 12))
        )
        (completed if satisfied else pending).append(mid)

    return {
        "applicable": applicable,
        "completed":  completed,
        "pending":    pending,
        "excluded":   excluded,
    }


# ─── Demo DB writer ──────────────────────────────────────────────────────────

class DemoDB:
    """Thin wrapper around the persona-demo Aura connection."""

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.driver.verify_connectivity()
        log.info("[DEMO] connected to %s", uri)

    def close(self):
        self.driver.close()

    def run(self, query: str, params: dict | None = None) -> list[dict]:
        with self.driver.session() as s:
            return s.run(query, params or {}).data()

    def write(self, query: str, params: dict | None = None) -> None:
        with self.driver.session() as s:
            s.run(query, params or {}).consume()

    def reset(self):
        log.info("[DEMO] clearing existing nodes")
        self.write("MATCH (n) DETACH DELETE n")
        for q in [
            "CREATE INDEX IF NOT EXISTS FOR (m:Member)        ON (m.member_id)",
            "CREATE INDEX IF NOT EXISTS FOR (p:IdealPersona)  ON (p.persona_id)",
            "CREATE INDEX IF NOT EXISTS FOR (s:Screening)     ON (s.measure_id)",
        ]:
            self.write(q)

    def seed_screenings(self):
        """One :Screening node per HEDIS measure, with CPT/ICD/age/lookback metadata."""
        from src.hedis_golden_reference import HEDIS_MEASURES
        for mid, m in HEDIS_MEASURES.items():
            self.write(
                """
                MERGE (s:Screening {measure_id: $mid})
                SET s.name                 = $name,
                    s.description          = $desc,
                    s.primary_cpt          = $cpt,
                    s.primary_icd10        = $icd,
                    s.age_range            = $age,
                    s.gender_requirement   = $gen,
                    s.lookback_months      = $lb,
                    s.diagnosis_requirement = $diag
                """,
                {
                    "mid":  mid,
                    "name": m.get("name", mid),
                    "desc": (m.get("description") or "")[:300],
                    "cpt":  m.get("primary_cpt", ""),
                    "icd":  m.get("primary_icd10", ""),
                    "age":  m.get("age_range", ""),
                    "gen":  m.get("gender_requirement", "Any"),
                    "lb":   m.get("lookback_months") or 0,
                    "diag": m.get("diagnosis_requirement", ""),
                },
            )
        log.info("[DEMO] seeded %d Screening nodes", len(HEDIS_MEASURES))

    def seed_member_with_persona(self, profile: dict, evaluation: dict, ideal_completion_date: str):
        """Mirror member, create their ideal persona twin, wire all relationships."""
        mid = profile["member_id"]
        applicable = evaluation["applicable"]
        completed = evaluation["completed"]
        pending = evaluation["pending"]
        excluded = evaluation["excluded"]
        compliance = round((len(completed) / len(applicable)) * 100, 1) if applicable else 100.0
        health_status = "Compliant" if not pending else ("Critical" if len(pending) >= 3 else "Has gaps")

        # Member node
        self.write(
            """
            MERGE (m:Member {member_id: $mid})
            SET m.name                = $name,
                m.dob                 = $dob,
                m.gender              = $gender,
                m.age_str             = $age_str,
                m.email               = $email,
                m.chronic_conditions  = $chronic,
                m.pcp_id              = $pcp_id,
                m.pcp_name            = $pcp_name,
                m.pcp_specialty       = $pcp_specialty,
                m.zip_code            = $zip,
                m.insurance_type      = $ins,
                m.health_status       = $health_status,
                m.compliance_score    = $compliance,
                m.applicable_count    = $applicable_count,
                m.completed_count     = $completed_count,
                m.pending_count       = $pending_count,
                m.excluded_count      = $excluded_count
            """,
            {
                "mid":  mid,
                "name": profile.get("name", ""),
                "dob":  profile.get("dob", ""),
                "gender": profile.get("gender", ""),
                "age_str": profile.get("age_str", ""),
                "email":   profile.get("email", ""),
                "chronic": (profile.get("chronic_conditions") or []),
                "pcp_id":  profile.get("pcp_id", ""),
                "pcp_name": profile.get("pcp_name", ""),
                "pcp_specialty": profile.get("pcp_specialty", ""),
                "zip":     profile.get("zip_code", ""),
                "ins":     profile.get("insurance_type", ""),
                "health_status":    health_status,
                "compliance":       compliance,
                "applicable_count": len(applicable),
                "completed_count":  len(completed),
                "pending_count":    len(pending),
                "excluded_count":   len(excluded),
            },
        )

        # Ideal persona twin
        persona_id = f"IDEAL-{mid}"
        self.write(
            """
            MERGE (p:IdealPersona {persona_id: $pid})
            SET p.name              = $name,
                p.age_str           = $age_str,
                p.gender            = $gender,
                p.chronic_conditions = $chronic,
                p.model             = 'ideal-cohort-fully-compliant',
                p.compliance_score  = 100.0,
                p.applicable_count  = $applicable_count,
                p.completed_count   = $applicable_count,
                p.pending_count     = 0,
                p.summary           = $summary
            WITH p
            MATCH (m:Member {member_id: $mid})
            MERGE (m)-[r:COMPARED_TO]->(p)
            SET r.gap_count   = $pending_count,
                r.gap_measures = $pending_list
            """,
            {
                "pid":  persona_id,
                "mid":  mid,
                "name": mid,
                "age_str": profile.get("age_str", ""),
                "gender":  profile.get("gender", ""),
                "chronic": (profile.get("chronic_conditions") or []),
                "applicable_count": len(applicable),
                "pending_count":    len(pending),
                "pending_list":     pending,
                "summary":          (
                    f"Same demographics as {mid}; would have completed every applicable screening "
                    f"({len(applicable)} measures) within HEDIS lookback windows."
                ),
            },
        )

        # Persona → every applicable screening (the "ideal" set)
        for measure_id in applicable:
            self.write(
                """
                MATCH (p:IdealPersona {persona_id: $pid})
                MATCH (s:Screening {measure_id: $mea})
                MERGE (p)-[r:WOULD_HAVE_COMPLETED]->(s)
                SET r.ideal_date = $ideal_date
                """,
                {"pid": persona_id, "mea": measure_id, "ideal_date": ideal_completion_date},
            )

        # Member → completed (compliant)
        for measure_id in completed:
            self.write(
                """
                MATCH (m:Member {member_id: $mid})
                MATCH (s:Screening {measure_id: $mea})
                MERGE (m)-[r:HAS_COMPLETED]->(s)
                SET r.recorded_at = $now
                """,
                {"mid": mid, "mea": measure_id, "now": datetime.now().date().isoformat()},
            )

        # Member → pending (open gaps)
        for measure_id in pending:
            self.write(
                """
                MATCH (m:Member {member_id: $mid})
                MATCH (s:Screening {measure_id: $mea})
                MERGE (m)-[r:HAS_PENDING]->(s)
                SET r.identified_on = $now,
                    r.urgency       = $urgency
                """,
                {
                    "mid": mid, "mea": measure_id,
                    "now": datetime.now().date().isoformat(),
                    "urgency": "high" if measure_id in {"BCS", "COL", "CCS"} else "standard",
                },
            )

        # Member → excluded
        for measure_id, reason in excluded:
            self.write(
                """
                MATCH (m:Member {member_id: $mid})
                MATCH (s:Screening {measure_id: $mea})
                MERGE (m)-[r:EXCLUDED_FROM]->(s)
                SET r.reason = $reason
                """,
                {"mid": mid, "mea": measure_id, "reason": reason},
            )


# ─── Entrypoint ──────────────────────────────────────────────────────────────

def main():
    log.info("Persona-Comparison Demo Seeder starting")
    main_data = _read_main_db()
    creds = _demo_db_creds()
    db = DemoDB(*creds)

    try:
        db.reset()
        db.seed_screenings()

        ideal_date = (datetime.now().date() - timedelta(days=30)).isoformat()
        n_members = 0
        n_pending = 0
        n_completed = 0
        n_excluded = 0

        for member in main_data["members"]:
            mid = member["member_id"]
            claims = main_data["claims_by_member"].get(mid, [])
            evalr = _evaluate_member(member, claims)
            db.seed_member_with_persona(member, evalr, ideal_completion_date=ideal_date)
            n_members += 1
            n_pending  += len(evalr["pending"])
            n_completed += len(evalr["completed"])
            n_excluded += len(evalr["excluded"])
            if n_members % 25 == 0:
                log.info("[DEMO] seeded %d / %d members", n_members, len(main_data["members"]))

        log.info("=" * 60)
        log.info("DONE — seeded %d members + %d ideal personas", n_members, n_members)
        log.info("  Pending screenings (HAS_PENDING):     %d", n_pending)
        log.info("  Completed screenings (HAS_COMPLETED): %d", n_completed)
        log.info("  Exclusions (EXCLUDED_FROM):           %d", n_excluded)
        log.info("=" * 60)
        log.info("Open Neo4j Browser pointed at the demo DB and try the queries in")
        log.info("  persona_demo/persona_demo_queries.cypher")
    finally:
        db.close()


if __name__ == "__main__":
    main()