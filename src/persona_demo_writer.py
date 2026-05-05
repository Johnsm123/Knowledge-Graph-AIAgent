"""
Persona-Demo DB writer — used by the bulk-upload pipeline.

This is the *third* Neo4j instance in the project:
  • Main DB        — care-gap discovery via the golden HEDIS reference
  • Reference DB   — dashboard + member-panel persona / lifecycle visualization
  • Persona-Demo DB (this module) — drives the realtime persona-comparison
                     animation rendered on the bulk-upload page

For every member processed in bulk upload we:
  1. Build a *closest-fit* IdealPersona (same demographics + every applicable
     screening completed + ideal lifestyle baseline).
  2. Write Member, IdealPersona, Screening nodes and relationships to the
     persona-demo DB so the live visualization can read them.
  3. Return a JSON-serialisable comparison dict the upload UI animates through.

Credentials are read from persona_demo/.env.persona-demo (gitignored). If
credentials are missing the writer becomes a no-op so the bulk-upload flow
never breaks because of an optional demo-only side-effect.
"""
from __future__ import annotations

import logging
import os
import random
import threading
from datetime import datetime
from typing import Any

# Random persona IDs in the range 1..99 (always under 100). Persona IDs MAY
# repeat across members — multiple members can share the same IdealPersona,
# since personas are reusable templates. The only guarantee is that the SAME
# member_id always receives the SAME persona ID (idempotent re-runs).
_PERSONA_ID_LOCK = threading.Lock()
_PERSONA_ID_BY_MEMBER: dict[str, str] = {}


def _allocate_persona_id(member_id: str) -> str:
    """Return a stable random persona id (P01..P99) for `member_id`.

    The same member_id always returns the same id within the process; different
    members may collide on the same id (allowed — personas are shared).
    """
    with _PERSONA_ID_LOCK:
        existing = _PERSONA_ID_BY_MEMBER.get(member_id)
        if existing:
            return existing
        n = random.randint(1, 99)
        pid = f"P{n:02d}"
        _PERSONA_ID_BY_MEMBER[member_id] = pid
        return pid

log = logging.getLogger("persona-demo-writer")


# ── Credential loading (mirrors seed_persona_demo_db.py) ─────────────────────

def _load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _persona_db_creds() -> tuple[str, str, str] | None:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    _load_env_file(os.path.join(repo_root, "persona_demo", ".env.persona-demo"))
    uri = os.environ.get("NEO4J_PERSONA_URI", "")
    user = os.environ.get("NEO4J_PERSONA_USER", "")
    pw   = os.environ.get("NEO4J_PERSONA_PASSWORD", "")
    if not (uri and user and pw):
        return None
    return uri, user, pw


# ── Driver cached at module level ────────────────────────────────────────────

_driver = None


def _get_driver():
    global _driver
    if _driver is not None:
        return _driver
    creds = _persona_db_creds()
    if not creds:
        return None
    try:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(creds[0], auth=(creds[1], creds[2]))
        _driver.verify_connectivity()
        log.info("[PERSONA-DEMO] connected to %s", creds[0])
        return _driver
    except Exception as e:
        log.warning("[PERSONA-DEMO] connection failed: %s", e)
        return None


# ── Ideal-persona baseline ───────────────────────────────────────────────────

IDEAL_LIFESTYLE = {
    "bmi":                "18.5-24.9",
    "smoking_status":     "Never",
    "alcohol_use":        "None / Occasional",
    "exercise_frequency": "5+ times/week",
    "diet_type":          "Balanced / Mediterranean",
    "sleep_hours_avg":    "7-9",
    "stress_level":       "Low",
}


def _gap_to_dict(g: dict) -> dict:
    return {
        "measure_id":   g.get("measure_id") or g.get("id") or "",
        "measure_name": g.get("measure_name") or g.get("name") or "",
        "primary_cpt":  g.get("primary_cpt_code") or g.get("primary_cpt") or "",
        "primary_icd":  g.get("primary_icd10") or g.get("primary_icd") or "",
    }


def build_persona_comparison(
    member_profile: dict,
    open_gaps:      list[dict],
    completed:      list[dict] | None = None,
    family_history: list[dict] | None = None,
    medical_history: dict | None = None,
    lifestyle:      dict | None = None,
) -> dict:
    """Pure function — no DB calls. Returns a comparison summary the UI animates."""
    completed = completed or []
    family_history = family_history or []
    medical_history = medical_history or {}
    lifestyle = lifestyle or {}
    pending  = [_gap_to_dict(g) for g in open_gaps]
    done     = [_gap_to_dict(g) for g in completed]
    mid      = member_profile.get("member_id", "")
    family_summary = [
        {
            "relation":   (fm.get("relation") or "").strip().title(),
            "conditions": (fm.get("conditions") or [])[:3],
            "alive":      bool(fm.get("alive", True)),
        }
        for fm in family_history if fm.get("relation")
    ][:6]
    medical_summary = {
        "current_conditions": [
            (e.get("name") or e.get("label") or "").strip()
            for e in (medical_history.get("current_conditions") or [])
        ][:5],
        "past_conditions": [
            (e.get("name") or e.get("label") or "").strip()
            for e in (medical_history.get("past_conditions") or [])
        ][:5],
        "medications": [
            (e.get("name") or e.get("label") or "").strip()
            for e in (medical_history.get("medications") or [])
        ][:5],
        "allergies": [
            (e.get("substance") or e.get("name") or e.get("label") or "").strip()
            for e in (medical_history.get("allergies") or [])
        ][:5],
    }
    return {
        "member_id":   mid,
        "member_name": member_profile.get("name", ""),
        "age":         member_profile.get("age_str") or member_profile.get("age", ""),
        "gender":      member_profile.get("gender", ""),
        "dob":         member_profile.get("dob", ""),
        "email":       member_profile.get("email", ""),
        "pcp_name":    member_profile.get("pcp_name", ""),
        "insurance_type": member_profile.get("insurance_type", ""),
        "chronic":     member_profile.get("chronic_conditions") or [],
        # Persona ID is a random number under 100 (e.g. P12, P45) — jumbled,
        # not derived from the member ID. Stable per member_id within the
        # process via _allocate_persona_id().
        "persona_id":  _allocate_persona_id(mid or ""),
        "persona_summary": (
            f"Closest-fit ideal twin for {mid}: same demographics, "
            "lifestyle in healthy ranges, every applicable HEDIS screening completed."
        ),
        "ideal_lifestyle": dict(IDEAL_LIFESTYLE),
        "completed_screenings": done,
        "pending_screenings":   pending,
        "missing_link_count":   len(pending),
        "family_history":       family_summary,
        "medical_history":      medical_summary,
        "lifestyle": {
            "bmi":                lifestyle.get("bmi", ""),
            "smoking_status":     lifestyle.get("smoking_status", ""),
            "alcohol_use":        lifestyle.get("alcohol_use", ""),
            "exercise_frequency": lifestyle.get("exercise_frequency", ""),
            "diet_type":          lifestyle.get("diet_type", ""),
            "sleep_hours_avg":    lifestyle.get("sleep_hours_avg", ""),
            "stress_level":       lifestyle.get("stress_level", ""),
        },
        "_family_history_raw":  family_history,
        "_medical_history_raw": medical_history,
    }


# ── DB write — mirror Member + IdealPersona + Screening nodes ────────────────

def push_member_persona(member_profile: dict, comparison: dict) -> bool:
    """Write Member + IdealPersona + Screening nodes/edges. Returns True on success."""
    driver = _get_driver()
    if driver is None:
        return False
    mid = comparison["member_id"]
    persona_id = comparison["persona_id"]
    pending = comparison["pending_screenings"]
    completed = comparison["completed_screenings"]
    applicable = pending + completed
    now = datetime.now().date().isoformat()

    try:
        with driver.session() as s:
            s.run(
                """
                MERGE (m:Member {member_id: $mid})
                SET m.name              = $name,
                    m.age_str           = $age,
                    m.gender            = $gender,
                    m.chronic_conditions = $chronic,
                    m.bulk_uploaded_at  = $now,
                    m.pending_count     = $pending_count,
                    m.completed_count   = $completed_count
                """,
                {
                    "mid": mid,
                    "name": comparison.get("member_name", ""),
                    "age":  comparison.get("age", ""),
                    "gender": comparison.get("gender", ""),
                    "chronic": comparison.get("chronic", []),
                    "now": now,
                    "pending_count":   len(pending),
                    "completed_count": len(completed),
                },
            ).consume()
            s.run(
                """
                MERGE (p:IdealPersona {persona_id: $pid})
                SET p.name              = $pid,
                    p.age_str           = $age,
                    p.gender            = $gender,
                    p.model             = 'closest-fit-ideal-twin',
                    p.compliance_score  = 100.0,
                    p.applicable_count  = $applicable_count,
                    p.completed_count   = $applicable_count,
                    p.pending_count     = 0,
                    p.summary           = $summary,
                    p.ideal_bmi         = $bmi,
                    p.ideal_smoking     = $smoking,
                    p.ideal_alcohol     = $alcohol,
                    p.ideal_exercise    = $exercise,
                    p.ideal_diet        = $diet,
                    p.ideal_sleep_hours = $sleep,
                    p.ideal_stress      = $stress
                WITH p
                MATCH (m:Member {member_id: $mid})
                MERGE (m)-[r:COMPARED_TO]->(p)
                SET r.gap_count    = $pending_count,
                    r.gap_measures = $pending_measure_ids,
                    r.compared_at  = $now
                """,
                {
                    "pid": persona_id,
                    "mid": mid,
                    "age":     comparison.get("age", ""),
                    "gender":  comparison.get("gender", ""),
                    "applicable_count": len(applicable),
                    "summary": comparison.get("persona_summary", ""),
                    "bmi":      IDEAL_LIFESTYLE["bmi"],
                    "smoking":  IDEAL_LIFESTYLE["smoking_status"],
                    "alcohol":  IDEAL_LIFESTYLE["alcohol_use"],
                    "exercise": IDEAL_LIFESTYLE["exercise_frequency"],
                    "diet":     IDEAL_LIFESTYLE["diet_type"],
                    "sleep":    IDEAL_LIFESTYLE["sleep_hours_avg"],
                    "stress":   IDEAL_LIFESTYLE["stress_level"],
                    "pending_count": len(pending),
                    "pending_measure_ids": [g["measure_id"] for g in pending],
                    "now": now,
                },
            ).consume()

            for g in applicable:
                s.run(
                    """
                    MERGE (sc:Screening {measure_id: $mea})
                    SET sc.name = $name,
                        sc.primary_cpt = $cpt,
                        sc.primary_icd = $icd
                    WITH sc
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MERGE (p)-[:WOULD_HAVE_COMPLETED]->(sc)
                    """,
                    {
                        "mea": g["measure_id"],
                        "name": g["measure_name"],
                        "cpt": g["primary_cpt"],
                        "icd": g["primary_icd"],
                        "pid": persona_id,
                    },
                ).consume()

            for g in completed:
                s.run(
                    """
                    MATCH (m:Member {member_id: $mid})
                    MATCH (sc:Screening {measure_id: $mea})
                    MERGE (m)-[r:HAS_COMPLETED]->(sc)
                    SET r.recorded_at = $now
                    """,
                    {"mid": mid, "mea": g["measure_id"], "now": now},
                ).consume()

            for g in pending:
                s.run(
                    """
                    MATCH (m:Member {member_id: $mid})
                    MATCH (sc:Screening {measure_id: $mea})
                    MERGE (m)-[r:HAS_PENDING]->(sc)
                    SET r.identified_on = $now
                    """,
                    {"mid": mid, "mea": g["measure_id"], "now": now},
                ).consume()

            # Member lifestyle node (member's actual values).
            ls = comparison.get("lifestyle") or {}
            if any(ls.values()):
                s.run(
                    """
                    MATCH (m:Member {member_id: $mid})
                    MERGE (l:Lifestyle {member_id: $mid})
                    SET l.bmi                = $bmi,
                        l.smoking_status     = $smoking,
                        l.alcohol_use        = $alcohol,
                        l.exercise_frequency = $exercise,
                        l.diet_type          = $diet,
                        l.sleep_hours_avg    = $sleep,
                        l.stress_level       = $stress
                    MERGE (m)-[:HAS_LIFESTYLE]->(l)
                    """,
                    {
                        "mid": mid,
                        "bmi":      ls.get("bmi", ""),
                        "smoking":  ls.get("smoking_status", ""),
                        "alcohol":  ls.get("alcohol_use", ""),
                        "exercise": ls.get("exercise_frequency", ""),
                        "diet":     ls.get("diet_type", ""),
                        "sleep":    ls.get("sleep_hours_avg", ""),
                        "stress":   ls.get("stress_level", ""),
                    },
                ).consume()

            # Family ancestral history.
            for fm in (comparison.get("_family_history_raw") or []):
                relation = (fm.get("relation") or "").strip()
                if not relation:
                    continue
                fmid = fm.get("family_member_id") or f"{mid}-{relation.lower().replace(' ', '_')}"
                s.run(
                    """
                    MATCH (m:Member {member_id: $mid})
                    MERGE (fm:FamilyMember {family_member_id: $fmid})
                    SET fm.relation = $relation,
                        fm.name     = $name,
                        fm.alive    = $alive,
                        fm.age_or_age_at_death = $age,
                        fm.cause_of_death = $cod,
                        fm.notes    = $notes
                    MERGE (m)-[:HAS_RELATIVE]->(fm)
                    WITH fm
                    UNWIND $conds AS cn
                    WITH fm, cn WHERE cn IS NOT NULL AND cn <> ''
                    MERGE (c:Condition {name: cn})
                    MERGE (fm)-[:HAS_CONDITION]->(c)
                    """,
                    {
                        "mid":   mid,
                        "fmid":  fmid,
                        "relation": relation,
                        "name":  fm.get("name", ""),
                        "alive": bool(fm.get("alive", True)),
                        "age":   fm.get("age_or_age_at_death") or "",
                        "cod":   fm.get("cause_of_death") or "",
                        "notes": fm.get("notes") or "",
                        "conds": fm.get("conditions") or [],
                    },
                ).consume()

            # Medical history (current/past conditions, medications, allergies, etc.).
            mh = comparison.get("_medical_history_raw") or {}
            type_map = [
                ("current_conditions", "current_condition"),
                ("past_conditions",    "past_condition"),
                ("surgeries",          "surgery"),
                ("medications",        "medication"),
                ("allergies",          "allergy"),
                ("immunizations",      "immunization"),
            ]
            entry_idx = 0
            for bucket, etype in type_map:
                for entry in (mh.get(bucket) or []):
                    label = (
                        entry.get("label")
                        or entry.get("name")
                        or entry.get("substance")
                        or ""
                    ).strip()
                    if not label:
                        continue
                    entry_idx += 1
                    eid = f"{mid}-MH-{entry_idx}"
                    s.run(
                        """
                        MATCH (m:Member {member_id: $mid})
                        MERGE (e:MedicalHistoryEntry {entry_id: $eid})
                        SET e.type     = $etype,
                            e.label    = $label,
                            e.year     = $year,
                            e.status   = $status,
                            e.severity = $severity,
                            e.reaction = $reaction,
                            e.dose     = $dose,
                            e.started  = $started,
                            e.purpose  = $purpose,
                            e.notes    = $notes
                        MERGE (m)-[:HAS_MEDICAL_HISTORY]->(e)
                        """,
                        {
                            "mid":   mid,
                            "eid":   eid,
                            "etype": etype,
                            "label": label,
                            "year":     entry.get("year") or "",
                            "status":   entry.get("status") or "",
                            "severity": entry.get("severity") or "",
                            "reaction": entry.get("reaction") or "",
                            "dose":     entry.get("dose") or "",
                            "started":  entry.get("started") or "",
                            "purpose":  entry.get("purpose") or "",
                            "notes":    entry.get("notes") or "",
                        },
                    ).consume()
        return True
    except Exception as e:
        log.warning("[PERSONA-DEMO] write failed for %s: %s", mid, e)
        return False
