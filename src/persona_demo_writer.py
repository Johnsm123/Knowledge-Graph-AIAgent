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
    # Load from main .env first (preferred), then persona_demo/.env.persona-demo
    # as a fallback. setdefault means whichever loads first wins.
    _load_env_file(os.path.join(repo_root, ".env"))
    _load_env_file(os.path.join(repo_root, "persona_demo", ".env.persona-demo"))
    uri = os.environ.get("NEO4J_PERSONA_URI", "")
    user = os.environ.get("NEO4J_PERSONA_USER", "")
    pw   = os.environ.get("NEO4J_PERSONA_PASSWORD", "")
    if not (uri and user and pw):
        log.warning(
            "[PERSONA-DEMO] missing creds — uri=%s user=%s pw_set=%s",
            bool(uri), bool(user), bool(pw),
        )
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

# Healthy clinical bands per lifestyle metric. The IdealPersona presents
# these as the "perfect range" — wide enough that a typical healthy member
# value falls inside, narrow enough that the contrast with an at-risk
# member is visible. Used by build_persona_comparison and rendered on the
# persona node + IdealLifestyle node in the persona-demo DB.
IDEAL_LIFESTYLE = {
    "bmi":                "18.5 – 24.9 (healthy)",
    "smoking_status":     "Never / former-quit",
    "alcohol_use":        "None to occasional (≤1/day F, ≤2/day M)",
    "exercise_frequency": "≥150 min moderate or 75 min vigorous /week",
    "diet_type":          "Balanced / Mediterranean / DASH",
    "sleep_hours_avg":    "7 – 9 hours/night",
    "stress_level":       "Low to moderate, well-managed",
}


# Numeric guard rails so we can flag whether the member's value sits inside
# the healthy band. Used by _annotate_member_lifestyle below to enrich the
# persona-comparison payload with `is_healthy` flags per metric.
_LIFESTYLE_BANDS = {
    "bmi":              {"min": 18.5, "max": 24.9},
    "sleep_hours_avg":  {"min": 7,    "max": 9},
}


def _to_float(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _annotate_member_lifestyle(member_lifestyle: dict) -> dict:
    """Return per-metric annotations: actual value + persona band + healthy-flag.

    Used by the bulk-upload preview and member-panel persona graph so the
    UI can show, per parameter, '<member value> vs <persona band>' with a
    green/red dot indicating whether the member already sits inside the
    healthy band.
    """
    ml = member_lifestyle or {}
    out = {}
    for key, ideal in IDEAL_LIFESTYLE.items():
        actual = ml.get(key, "")
        is_healthy = None
        band = _LIFESTYLE_BANDS.get(key)
        if band:
            n = _to_float(actual)
            if n is not None:
                is_healthy = (band["min"] <= n <= band["max"])
        elif key == "smoking_status":
            s = str(actual).strip().lower()
            if s:
                is_healthy = s in ("never", "former", "quit", "former-quit", "non-smoker", "none")
        elif key == "alcohol_use":
            s = str(actual).strip().lower()
            if s:
                is_healthy = s in ("none", "occasional", "rarely", "social", "none / occasional")
        out[key] = {
            "actual": actual,
            "ideal_range": ideal,
            "is_healthy": is_healthy,  # None = unknown, True/False otherwise
        }
    return out


# ── Persona-comparison computation helpers ──────────────────────────────────
# Mirrors persona_demo/seed_persona_demo_db.py so the bulk-upload writer
# produces the exact same shape on the IdealPersona node + COMPARED_TO
# relationship that the demo Cypher queries (lifestyle_comparison,
# missing_links, gap_categories, total_missing_links) expect.

RECOMMENDED_IMMUNIZATIONS = {"Influenza", "Tdap", "COVID-19"}
HIGH_RISK_FAMILY_CONDITIONS = {
    "Diabetes Type 2", "Hypertension", "Coronary Artery Disease",
    "Breast Cancer", "Colorectal Cancer", "Stroke",
}


def _compute_lifestyle_gaps(lifestyle: dict) -> list:
    if not lifestyle:
        return ["No lifestyle data on file"]
    gaps: list = []
    bmi = lifestyle.get("bmi")
    n = _to_float(bmi) if bmi is not None else None
    if n is not None and (n < 18.5 or n > 24.9):
        gaps.append(f"BMI {n} outside ideal 18.5–24.9")
    smoking = (lifestyle.get("smoking_status") or "").strip()
    if smoking and smoking.lower() not in {"never", "non-smoker", "none", "former", "quit", "former-quit"}:
        gaps.append(f"Smoking status: {smoking} (ideal: Never)")
    alcohol = (lifestyle.get("alcohol_use") or "").strip().lower()
    if alcohol in {"heavy", "frequent", "daily"}:
        gaps.append(f"Alcohol use: {lifestyle.get('alcohol_use')} (ideal: None/Occasional)")
    exercise = (lifestyle.get("exercise_frequency") or "").strip().lower()
    if exercise in {"never", "rarely", "none", "sedentary", "1-2 times/week", "2x/week"}:
        gaps.append(f"Exercise: {lifestyle.get('exercise_frequency')} (ideal: 5+ times/week)")
    sleep = lifestyle.get("sleep_hours_avg")
    s = _to_float(sleep) if sleep is not None else None
    if s is not None and (s < 7 or s > 9):
        gaps.append(f"Sleep avg {s}h outside ideal 7–9h")
    stress = (lifestyle.get("stress_level") or "").strip().lower()
    if stress in {"high", "severe"}:
        gaps.append(f"Stress level: {lifestyle.get('stress_level')} (ideal: Low)")
    return gaps


def _compute_family_risk_flags(family_history: list) -> list:
    flags = []
    for fm in (family_history or []):
        for cond in (fm.get("conditions") or []):
            if cond in HIGH_RISK_FAMILY_CONDITIONS:
                flags.append(f"{fm.get('relation', 'relative')} → {cond}")
    return flags


def _compute_history_gaps(medical_history: dict) -> dict:
    mh = medical_history or {}
    immunized = {(e.get("name") or e.get("label") or "").strip()
                 for e in (mh.get("immunizations") or [])}
    missing_imm = sorted(RECOMMENDED_IMMUNIZATIONS - immunized)
    unmanaged = []
    for e in (mh.get("current_conditions") or []):
        label = (e.get("name") or e.get("label") or "").strip()
        status = (e.get("status") or "").strip().lower()
        if label and status in {"uncontrolled", "active", "unmanaged", ""}:
            unmanaged.append(label)
    severe_allg = []
    for e in (mh.get("allergies") or []):
        sev = (e.get("severity") or "").strip().lower()
        label = (e.get("substance") or e.get("name") or e.get("label") or "").strip()
        if label and sev in {"severe", "anaphylaxis"}:
            severe_allg.append(label)
    return {
        "missing_immunizations": missing_imm,
        "unmanaged_conditions":  unmanaged,
        "severe_allergies":      severe_allg,
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
    lifestyle_annotated = _annotate_member_lifestyle(lifestyle)
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
        # Member's actual value alongside the persona's healthy band per
        # lifestyle metric, so the UI can render "member 19.5 vs persona
        # 18.5–24.9 ✓" with a green/red indicator.
        "lifestyle_compare": lifestyle_annotated,
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
        log.warning(
            "[PERSONA-DEMO] no driver — skipping write for member_id=%s",
            comparison.get("member_id", "?"),
        )
        return False
    mid = comparison["member_id"]
    persona_id = comparison["persona_id"]
    pending = comparison["pending_screenings"]
    completed = comparison["completed_screenings"]
    applicable = pending + completed
    now = datetime.now().date().isoformat()

    try:
        with driver.session() as s:
            # Idempotency reset: drop every member-scoped relationship that the
            # rest of this function will re-create from current data. Without
            # this, a re-upload of the same member would leave behind stale
            # HAS_PENDING / HAS_COMPLETED / IS_CARE_GAP_FOR / HIGHLIGHTS_CARE_GAP
            # edges from previous runs and the persona-demo DB would no longer
            # mirror exactly the gaps detected in the main DB.
            s.run(
                """
                MATCH (m:Member {member_id: $mid})
                OPTIONAL MATCH (m)-[r1:HAS_PENDING]->()
                DELETE r1
                """,
                {"mid": mid},
            ).consume()
            s.run(
                """
                MATCH (m:Member {member_id: $mid})
                OPTIONAL MATCH (m)-[r2:HAS_COMPLETED]->()
                DELETE r2
                """,
                {"mid": mid},
            ).consume()
            s.run(
                """
                MATCH (m:Member {member_id: $mid})
                OPTIONAL MATCH (m)<-[r3:IS_CARE_GAP_FOR]-(:Screening)
                DELETE r3
                """,
                {"mid": mid},
            ).consume()
            s.run(
                """
                MATCH (:IdealPersona)-[r4:HIGHLIGHTS_CARE_GAP {member_id: $mid}]->(:Screening)
                DELETE r4
                """,
                {"mid": mid},
            ).consume()
            # Drop every existing COMPARED_TO from this member so the freshly
            # rewritten one is the only relationship returned by the demo
            # queries (avoids "Expected a single record, found multiple"
            # warnings and stale property names like ideal_bmi from older
            # writer versions).
            s.run(
                """
                MATCH (m:Member {member_id: $mid})-[r:COMPARED_TO]->()
                DELETE r
                """,
                {"mid": mid},
            ).consume()

            # Compute the missing-link breakdown so the COMPARED_TO edge can
            # carry every attribute the demo Cypher queries (lifestyle_comparison,
            # missing_links, gap_categories, total_missing_links) read.
            ls           = comparison.get("lifestyle") or {}
            family_raw   = comparison.get("_family_history_raw") or []
            mh_raw       = comparison.get("_medical_history_raw") or {}
            lifestyle_gaps = _compute_lifestyle_gaps(ls)
            family_flags   = _compute_family_risk_flags(family_raw)
            history_gaps   = _compute_history_gaps(mh_raw)
            missing_imm    = history_gaps["missing_immunizations"]
            unmanaged      = history_gaps["unmanaged_conditions"]
            severe_allg    = history_gaps["severe_allergies"]
            pending_ids    = [g["measure_id"] for g in pending if g.get("measure_id")]
            total_links    = (
                len(pending_ids) + len(lifestyle_gaps) + len(missing_imm)
                + len(unmanaged) + len(family_flags)
            )
            gap_categories = [
                cat for cat, items in [
                    ("screenings",       pending_ids),
                    ("lifestyle",        lifestyle_gaps),
                    ("immunizations",    missing_imm),
                    ("unmanaged_chronic", unmanaged),
                    ("family_risk",      family_flags),
                ] if items
            ]

            # Roll the member's actual ancestral + medical history into flat
            # arrays on the Member node so a single Cypher MATCH returns the
            # whole side-by-side comparison without traversing FamilyMember /
            # MedicalHistoryEntry sub-graphs.
            family_summary = [
                f"{(fm.get('relation') or 'relative').strip()}: "
                + (", ".join(fm.get("conditions") or []) or "no conditions")
                for fm in (family_raw or [])
            ]
            current_conditions_list = [
                (e.get("name") or e.get("label") or "").strip()
                for e in (mh_raw.get("current_conditions") or [])
                if (e.get("name") or e.get("label"))
            ]
            past_conditions_list = [
                (e.get("name") or e.get("label") or "").strip()
                for e in (mh_raw.get("past_conditions") or [])
                if (e.get("name") or e.get("label"))
            ]
            medications_list = [
                (e.get("name") or e.get("label") or "").strip()
                for e in (mh_raw.get("medications") or [])
                if (e.get("name") or e.get("label"))
            ]
            allergies_list = [
                (e.get("substance") or e.get("name") or e.get("label") or "").strip()
                for e in (mh_raw.get("allergies") or [])
                if (e.get("substance") or e.get("name") or e.get("label"))
            ]
            immunizations_list = sorted({
                (e.get("name") or e.get("label") or "").strip()
                for e in (mh_raw.get("immunizations") or [])
                if (e.get("name") or e.get("label"))
            })
            surgeries_list = [
                (e.get("name") or e.get("label") or "").strip()
                for e in (mh_raw.get("surgeries") or [])
                if (e.get("name") or e.get("label"))
            ]

            # Member node — full lifestyle + ancestral + medical attributes.
            # The demo's side-by-side query reads every property here directly.
            s.run(
                """
                MERGE (m:Member {member_id: $mid})
                SET m.name                = $name,
                    m.age_str             = $age,
                    m.gender              = $gender,
                    m.chronic_conditions  = $chronic,
                    m.bulk_uploaded_at    = $now,
                    m.pending_count       = $pending_count,
                    m.completed_count     = $completed_count,
                    m.bmi                  = $bmi,
                    m.smoking_status       = $smoking,
                    m.alcohol_use          = $alcohol,
                    m.exercise_frequency   = $exercise,
                    m.diet_type            = $diet,
                    m.sleep_hours_avg      = $sleep,
                    m.stress_level         = $stress,
                    m.family_risk_flags     = $family_flags,
                    m.family_history        = $family_summary,
                    m.unmanaged_conditions  = $unmanaged,
                    m.severe_allergies      = $severe_allg,
                    m.immunizations_on_file = $immunizations,
                    m.current_conditions    = $current_conditions,
                    m.past_conditions       = $past_conditions,
                    m.medications           = $medications,
                    m.allergies             = $allergies,
                    m.surgeries             = $surgeries
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
                    "bmi":      ls.get("bmi", ""),
                    "smoking":  ls.get("smoking_status", ""),
                    "alcohol":  ls.get("alcohol_use", ""),
                    "exercise": ls.get("exercise_frequency", ""),
                    "diet":     ls.get("diet_type", ""),
                    "sleep":    ls.get("sleep_hours_avg", ""),
                    "stress":   ls.get("stress_level", ""),
                    "family_flags":   family_flags,
                    "family_summary": family_summary,
                    "unmanaged":      unmanaged,
                    "severe_allg":    severe_allg,
                    "immunizations":      immunizations_list,
                    "current_conditions": current_conditions_list,
                    "past_conditions":    past_conditions_list,
                    "medications":        medications_list,
                    "allergies":          allergies_list,
                    "surgeries":          surgeries_list,
                },
            ).consume()

            # IdealPersona — full "perfect twin" attributes covering lifestyle,
            # ancestral history (clean lineage), and medical history (every
            # immunization on file, every condition managed/resolved). The
            # property names match what persona_demo_queries.cypher reads so
            # a single side-by-side Cypher MATCH renders the whole story.
            ideal_immunizations = sorted(
                set(immunizations_list) | RECOMMENDED_IMMUNIZATIONS
            )
            # Mirror the member's family relations but with no high-risk
            # inherited conditions — i.e. an ideal lineage of the same shape.
            ideal_family_history = [
                f"{(fm.get('relation') or 'relative').strip()}: "
                "no high-risk inherited conditions"
                for fm in (family_raw or [])
            ] or ["No high-risk family history on file"]
            # Past conditions persona = same set, all resolved.
            ideal_past_conditions = (
                [f"{c} (resolved)" for c in past_conditions_list]
                or ["No past conditions"]
            )
            # Current conditions persona = same set, all controlled / managed.
            ideal_current_conditions = (
                [f"{c} (controlled / managed)" for c in current_conditions_list]
                or ["No active conditions"]
            )
            # Medications persona = same medications, taken on schedule, no
            # unmanaged side effects.
            ideal_medications = (
                [f"{m} (adherent / on schedule)" for m in medications_list]
                or ["No medications required"]
            )
            # Allergies persona = same allergies but managed without incident.
            ideal_allergies = (
                [f"{a} (managed without incident)" for a in allergies_list]
                or ["No known allergies"]
            )

            s.run(
                """
                MERGE (p:IdealPersona {persona_id: $pid})
                SET p.name                       = $pid,
                    p.age_str                    = $age,
                    p.gender                     = $gender,
                    p.model                      = 'closest-fit-ideal-twin',
                    p.compliance_score           = 100.0,
                    p.applicable_count           = $applicable_count,
                    p.completed_count            = $applicable_count,
                    p.pending_count              = 0,
                    p.summary                    = $summary,
                    p.ideal_bmi_range            = $bmi,
                    p.ideal_smoking_status       = $smoking,
                    p.ideal_alcohol_use          = $alcohol,
                    p.ideal_exercise_frequency   = $exercise,
                    p.ideal_diet_type            = $diet,
                    p.ideal_sleep_hours          = $sleep,
                    p.ideal_stress_level         = $stress,
                    p.recommended_immunizations  = $reco_imm,
                    p.ideal_immunizations        = $ideal_imm_full,
                    p.ideal_family_history       = $ideal_family,
                    p.family_risk_followup       = $family_followup,
                    p.chronic_management_status  = 'All chronic conditions controlled / managed',
                    p.ideal_current_conditions   = $ideal_current,
                    p.ideal_past_conditions      = $ideal_past,
                    p.ideal_medications          = $ideal_meds,
                    p.ideal_allergies            = $ideal_allergies,
                    p.severe_allergies           = []
                WITH p
                MATCH (m:Member {member_id: $mid})
                MERGE (m)-[r:COMPARED_TO]->(p)
                SET r.gap_count             = $pending_count,
                    r.gap_measures          = $pending_measure_ids,
                    r.lifestyle_gaps        = $lifestyle_gaps,
                    r.lifestyle_gap_count   = $lifestyle_gap_count,
                    r.missing_immunizations = $missing_imm,
                    r.unmanaged_conditions  = $unmanaged,
                    r.family_risk_flags     = $family_flags,
                    r.severe_allergies      = $severe_allg,
                    r.total_missing_links   = $total_links,
                    r.gap_categories        = $gap_categories,
                    r.compared_at           = $now
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
                    "reco_imm":   sorted(RECOMMENDED_IMMUNIZATIONS),
                    "family_followup": (
                        "All hereditary high-risk conditions reviewed with PCP and screening cadence adjusted"
                        if family_flags else "No family-history follow-up required"
                    ),
                    "pending_count": len(pending),
                    "pending_measure_ids": pending_ids,
                    "lifestyle_gaps":      lifestyle_gaps,
                    "lifestyle_gap_count": len(lifestyle_gaps),
                    "missing_imm":  missing_imm,
                    "unmanaged":    unmanaged,
                    "family_flags": family_flags,
                    "severe_allg":  severe_allg,
                    "total_links":  total_links,
                    "gap_categories": gap_categories,
                    "now": now,
                    "ideal_imm_full": ideal_immunizations,
                    "ideal_family":   ideal_family_history,
                    "ideal_current":  ideal_current_conditions,
                    "ideal_past":     ideal_past_conditions,
                    "ideal_meds":     ideal_medications,
                    "ideal_allergies": ideal_allergies,
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

            # ── Ideal-persona mirror nodes ───────────────────────────────
            # Mirror the member's parameter structure (lifestyle / ancestral
            # history / medical history) onto the IdealPersona — but with
            # perfected values. This gives the persona-demo visualization a
            # complete "perfect twin" graph that contrasts the member's
            # actual records and clearly shows where the care gaps are.
            s.run(
                """
                MERGE (il:IdealLifestyle {persona_id: $pid})
                SET il.bmi                = $bmi,
                    il.smoking_status     = $smoking,
                    il.alcohol_use        = $alcohol,
                    il.exercise_frequency = $exercise,
                    il.diet_type          = $diet,
                    il.sleep_hours_avg    = $sleep,
                    il.stress_level       = $stress
                WITH il
                MATCH (p:IdealPersona {persona_id: $pid})
                MERGE (p)-[:HAS_IDEAL_LIFESTYLE]->(il)
                """,
                {
                    "pid":      persona_id,
                    "bmi":      IDEAL_LIFESTYLE["bmi"],
                    "smoking":  IDEAL_LIFESTYLE["smoking_status"],
                    "alcohol":  IDEAL_LIFESTYLE["alcohol_use"],
                    "exercise": IDEAL_LIFESTYLE["exercise_frequency"],
                    "diet":     IDEAL_LIFESTYLE["diet_type"],
                    "sleep":    IDEAL_LIFESTYLE["sleep_hours_avg"],
                    "stress":   IDEAL_LIFESTYLE["stress_level"],
                },
            ).consume()

            # Ideal ancestral history — same relations as the member, but
            # all alive and free of inherited conditions (the "clean" lineage
            # the member would have in an ideal world).
            for fm in (comparison.get("_family_history_raw") or []):
                relation = (fm.get("relation") or "").strip()
                if not relation:
                    continue
                ifmid = f"{persona_id}-{relation.lower().replace(' ', '_')}-ideal"
                s.run(
                    """
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MERGE (ifm:IdealFamilyMember {family_member_id: $ifmid})
                    SET ifm.relation              = $relation,
                        ifm.alive                 = true,
                        ifm.age_or_age_at_death   = $age,
                        ifm.conditions            = [],
                        ifm.notes                 = 'Ideal lineage — no inherited conditions'
                    MERGE (p)-[:HAS_IDEAL_RELATIVE]->(ifm)
                    """,
                    {
                        "pid":      persona_id,
                        "ifmid":    ifmid,
                        "relation": relation,
                        "age":      fm.get("age_or_age_at_death") or "",
                    },
                ).consume()

            # Ideal medical history — every applicable screening completed,
            # no active conditions, allergies / immunizations preserved as
            # neutral facts. Each entry mirrors the member's structure but
            # is marked "ideal".
            ideal_entry_idx = 0
            for g in applicable:
                ideal_entry_idx += 1
                ieid = f"{persona_id}-IMH-{ideal_entry_idx}"
                s.run(
                    """
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MERGE (e:IdealMedicalHistoryEntry {entry_id: $ieid})
                    SET e.type       = 'completed_screening',
                        e.label      = $label,
                        e.measure_id = $mea,
                        e.status     = 'Completed',
                        e.notes      = 'Ideal twin completed this HEDIS screening'
                    MERGE (p)-[:HAS_IDEAL_MEDICAL_HISTORY]->(e)
                    """,
                    {
                        "pid":   persona_id,
                        "ieid":  ieid,
                        "label": g["measure_name"] or g["measure_id"],
                        "mea":   g["measure_id"],
                    },
                ).consume()

            mh = comparison.get("_medical_history_raw") or {}
            for entry in (mh.get("past_conditions") or []) + (mh.get("current_conditions") or []):
                label = (entry.get("name") or entry.get("label") or "").strip()
                if not label:
                    continue
                ideal_entry_idx += 1
                ieid = f"{persona_id}-IMH-{ideal_entry_idx}"
                s.run(
                    """
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MERGE (e:IdealMedicalHistoryEntry {entry_id: $ieid})
                    SET e.type     = 'resolved_condition',
                        e.label    = $label,
                        e.status   = 'Resolved',
                        e.notes    = 'Ideal twin resolved/avoided this condition'
                    MERGE (p)-[:HAS_IDEAL_MEDICAL_HISTORY]->(e)
                    """,
                    {"pid": persona_id, "ieid": ieid, "label": label},
                ).consume()

            for entry in (mh.get("allergies") or []):
                label = (entry.get("substance") or entry.get("name") or entry.get("label") or "").strip()
                if not label:
                    continue
                ideal_entry_idx += 1
                ieid = f"{persona_id}-IMH-{ideal_entry_idx}"
                s.run(
                    """
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MERGE (e:IdealMedicalHistoryEntry {entry_id: $ieid})
                    SET e.type     = 'allergy',
                        e.label    = $label,
                        e.severity = 'Managed',
                        e.notes    = 'Allergy carried to ideal twin — managed without incident'
                    MERGE (p)-[:HAS_IDEAL_MEDICAL_HISTORY]->(e)
                    """,
                    {"pid": persona_id, "ieid": ieid, "label": label},
                ).consume()

            for entry in (mh.get("immunizations") or []):
                label = (entry.get("name") or entry.get("label") or "").strip()
                if not label:
                    continue
                ideal_entry_idx += 1
                ieid = f"{persona_id}-IMH-{ideal_entry_idx}"
                s.run(
                    """
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MERGE (e:IdealMedicalHistoryEntry {entry_id: $ieid})
                    SET e.type   = 'immunization',
                        e.label  = $label,
                        e.year   = $year,
                        e.status = 'Up-to-date'
                    MERGE (p)-[:HAS_IDEAL_MEDICAL_HISTORY]->(e)
                    """,
                    {
                        "pid":   persona_id,
                        "ieid":  ieid,
                        "label": label,
                        "year":  entry.get("year") or "",
                    },
                ).consume()

            # Explicit care-gap marker: connect each pending Screening to the
            # Member with a HIGHLIGHTS_CARE_GAP edge from the IdealPersona, so
            # the visualization can light up exactly which screenings the
            # member is missing relative to the perfect twin.
            for g in pending:
                s.run(
                    """
                    MATCH (p:IdealPersona {persona_id: $pid})
                    MATCH (m:Member {member_id: $mid})
                    MATCH (sc:Screening {measure_id: $mea})
                    MERGE (p)-[r:HIGHLIGHTS_CARE_GAP {member_id: $mid, measure_id: $mea}]->(sc)
                    SET r.identified_on = $now,
                        r.measure_name  = $name
                    MERGE (sc)-[g:IS_CARE_GAP_FOR]->(m)
                    SET g.identified_on = $now
                    """,
                    {
                        "pid":  persona_id,
                        "mid":  mid,
                        "mea":  g["measure_id"],
                        "name": g["measure_name"] or g["measure_id"],
                        "now":  now,
                    },
                ).consume()

        log.info(
            "[PERSONA-DEMO] wrote member_id=%s persona_id=%s pending=%d completed=%d",
            mid, persona_id, len(pending), len(completed),
        )
        return True
    except Exception as e:
        log.warning("[PERSONA-DEMO] write failed for %s: %s", mid, e)
        return False
