"""
Care Gap Validation Agent System — 6-Agent Architecture.

Flow per member:
  1. Fetch member profile + claims from Neo4j (Python — no LLM)
  2. Filter applicable QualityMeasure golden reference nodes (Python)
  3. Check exclusion criteria from Neo4j rulebook (Python)
  4. Cross-check CPT codes vs lookback windows (Python — OR logic for COL/CCS)
  5. Auto-create CareGap nodes for newly detected gaps (Python)
  6. Run 6-agent pipeline for analysis + recommendations (LLM)

Agents (order):
  1. patient_analyst      → confirms member profile and eligibility
  2. hedis_measure_agent  → reviews applicable HEDIS rules and code requirements
  3. exclusion_agent      → confirms exclusion decisions with clinical codes
  4. code_validator       → audits CPT code compliance per lookback window
  5. care_gap_agent       → finalises gap status, confirms Neo4j writes
  6. recommendation_agent → generates prioritised outreach and care manager scripts

Two execution modes:
  - validate_and_suggest()        → blocking, returns all responses at once
  - validate_and_suggest_stream() → generator, yields SSE events per-agent
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Tuple
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from src.bedrock_client import BedrockChatCompletionClient
from config.settings import settings
from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_applicable_measures,
    get_member_claims_cpt_codes,
    get_member_profile,
    merge_care_gap,
    check_member_exclusions,
    get_member_extended_profile,
)

logger = logging.getLogger(__name__)

# Canonical agent order (used by frontend to render panels in the right sequence)
AGENT_ORDER = [
    "patient_analyst",
    "hedis_measure_agent",
    "exclusion_agent",
    "code_validator",
    "care_gap_agent",
    "recommendation_agent",
]


# ── Chronic condition → ICD-10 code mapping ───────────────────────────────────
# Used to synthesise ICD evidence for newly added members who have no claims yet.
# This ensures diabetes/chronic disease measures are evaluated even before any
# claim history exists.
# NOTE: CKD maps to stages 1-4 only (N18.1-N18.4, N18.9). Stage 5 (N18.5) is
# pre-dialysis ESRD and belongs to the ESRD bucket — do NOT include N18.5 in
# the generic CKD mapping or KED ESRD exclusion will incorrectly fire for
# non-terminal CKD patients.
CHRONIC_CONDITION_ICD_MAP = {
    "Diabetes (Type 1)":              ["E10.9", "E10.65", "E10.8", "E10.40"],
    "Diabetes (Type 2)":              ["E11.9", "E11.65", "E11.8", "E11.40"],
    "Hypertension":                   ["I10"],
    "Coronary Artery Disease (CAD)":  ["I25.10", "I25.9"],
    "Congestive Heart Failure (CHF)": ["I50.9", "I50.32"],
    "COPD":                           ["J44.9", "J44.1"],
    "Asthma":                         ["J45.909", "J45.20"],
    # CKD stages 1-4 only — N18.5 (stage 5 / pre-dialysis ESRD) is in the ESRD bucket
    "Chronic Kidney Disease (CKD)":   ["N18.9", "N18.1", "N18.2", "N18.3", "N18.4"],
    # ESRD includes stage 5 (N18.5), dialysis-dependent (N18.6), and dialysis status (Z99.2)
    "End-Stage Renal Disease (ESRD)": ["N18.5", "N18.6", "Z99.2"],
    "Depression / Anxiety":           ["F32.9", "F41.9", "F33.0"],
    "Cancer (Active)":                ["C80.1", "C78.9"],
    "Hospice / Palliative Care":      ["Z51.5", "Z51.89"],
    "Pregnancy":                      ["Z34.90", "Z34.00"],
    # Added for CBP trigger (hypertension already present as "Hypertension" above)
    # Schizophrenia / Schizoaffective — triggers SMC, SMD, SSD (future measures)
    "Schizophrenia / Psychosis":      ["F20.9", "F20.0", "F20.1", "F20.2", "F20.3",
                                       "F20.5", "F20.81", "F20.89", "F25.0", "F25.1",
                                       "F25.8", "F25.9"],
    # Acute MI — triggers CRE, PBH (future measures)
    "Acute Myocardial Infarction":    ["I21.9", "I21.01", "I21.09", "I21.11", "I21.19",
                                       "I21.21", "I21.29", "I21.3", "I21.4"],
    # Substance Use Disorder — triggers FUA, FUI, IET (future measures)
    "Substance Use Disorder (SUD)":   ["F10.10", "F11.10", "F12.10", "F13.10",
                                       "F14.10", "F15.10", "F16.10", "F19.10"],
}

# ── Fallback ICD codes for exclusion types that have no explicit codes in
#    some HEDIS measure definitions (e.g. COL/CCS/EED/GSD/KED/BPD
#    palliative_care/hospice entries only have a description, no icd10 list).
# These are used by _is_member_excluded_golden() to close that gap.
_EXCLUSION_TYPE_FALLBACK_ICD: Dict[str, List[str]] = {
    # Global: palliative care / hospice — ICD Z51.5 + Z51.89 + HCPCS G9054/M1017
    # HEDIS rulebook requires checking both ICD and HCPCS for these exclusions.
    # HCPCS stored here as pseudo-ICD strings; _is_member_excluded_golden() also
    # checks member CPT set so include in icd list for fallback matching.
    "palliative_care":   ["Z51.5", "Z51.89", "G9054", "M1017"],
    "hospice":           ["Z51.5", "Z51.89", "G9054", "M1017"],
    "pregnancy":         [
        "Z34.00", "Z34.01", "Z34.02", "Z34.09",
        "Z34.10", "Z34.11", "Z34.12", "Z34.19",
        "Z34.20", "Z34.21", "Z34.22", "Z34.29",
        "Z34.30", "Z34.31", "Z34.32", "Z34.39",
        "Z34.40", "Z34.41", "Z34.42", "Z34.43",
        "Z34.90",
    ],
    # ESRD / dialysis exclusion (KED, BPD) — use N18.5+ only, not stages 1-4
    "esrd":                   ["N18.5", "N18.6", "Z99.2"],
    "esrd_dialysis_nephrectomy": ["N18.5", "N18.6", "Z99.2"],
    "dialysis":               ["N18.6", "Z99.2"],
    # Hysterectomy without cervix (CCS, CHL exclusion)
    "hysterectomy_no_cervix": ["Q51.5", "Z90.710", "Z90.712"],
    # CRC history (COL exclusion)
    "colorectal_cancer":      [
        "C18.0", "C18.1", "C18.2", "C18.3", "C18.4", "C18.5",
        "C18.6", "C18.7", "C18.8", "C18.9", "C19", "C20",
        "C21.2", "C21.8", "Z85.038", "Z85.048",
    ],
}


def _icd_codes_from_conditions(chronic_conditions) -> list:
    """
    Convert a member's chronic_conditions list (stored on the Member node)
    into a flat list of ICD-10 codes for use in measure applicability and
    exclusion checks when no claim history exists.
    """
    if not chronic_conditions:
        return []
    codes = []
    for cond in (chronic_conditions if isinstance(chronic_conditions, list) else []):
        codes.extend(CHRONIC_CONDITION_ICD_MAP.get(cond, []))
    return codes


# ── Pure Python helpers (no LLM) ──────────────────────────────────────────────

def _parse_age(age_str: str) -> int:
    """Extract numeric age from '41 Years, 6 Months' format."""
    try:
        return int(str(age_str).split()[0])
    except Exception:
        return 0


def _parse_service_date(date_str: str):
    """Parse YYYY-MM-DD service date (already normalised by loader)."""
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except Exception:
        return None


def _measure_applies(measure: Dict, age: int, gender: str, icd_codes: List[str]) -> bool:
    """
    Returns True if the golden reference measure applies to this member.

    Rules:
      - Age must fall within measure's age range
      - Gender must match if measure specifies Female/Male (checked via age_range string
        and gender_requirement field)
      - Diabetes measures (GSD, EED, KED, BPD) require E11.x ICD code in claims
    """
    age_range = str(measure.get("age_range", ""))
    gender_required = None

    # Gender can be embedded in the age_range string (e.g. "42-74 Female")
    # or stored in gender_requirement field
    if "Female" in age_range:
        gender_required = "F"
        age_range = age_range.replace("Female", "").strip()
    elif "Male" in age_range:
        gender_required = "M"
        age_range = age_range.replace("Male", "").strip()

    # Also check the dedicated gender_requirement field
    gender_req_field = str(measure.get("gender_requirement", "Any")).strip()
    if gender_required is None and gender_req_field == "Female":
        gender_required = "F"
    elif gender_required is None and gender_req_field == "Male":
        gender_required = "M"

    if gender_required and gender.upper()[:1] != gender_required:
        return False

    try:
        parts = age_range.split("-")
        min_age, max_age = int(parts[0].strip()), int(parts[1].strip())
        if not (min_age <= age <= max_age):
            return False
    except Exception:
        pass

    diag_req = str(measure.get("diagnosis_requirement", "")).lower()

    # ── Diabetes measures: GSD, EED, KED, BPD ────────────────────────────────
    # HEDIS MY2025 rulebook specifies E08–E13 (covers secondary diabetes E08,
    # drug-induced E09, type 1 E10, type 2 E11, other unspecified E12, other
    # specified E13). All require an active diabetes diagnosis.
    if "diabetes" in diag_req or any(f"e{n:02d}" in diag_req for n in range(8, 14)):
        has_diabetes_icd = any(
            str(icd).upper().startswith(("E08", "E09", "E10", "E11", "E12", "E13"))
            for icd in icd_codes
        )
        if not has_diabetes_icd:
            return False

    # ── Hypertension measure: CBP ─────────────────────────────────────────────
    # Requires active hypertension (ICD I10).
    if "hypertension" in diag_req or "i10" in diag_req:
        has_htn_icd = any(
            str(icd).upper().startswith("I10")
            for icd in icd_codes
        )
        if not has_htn_icd:
            return False

    return True


def _build_required_cpt_set(cpt_codes_str: str) -> set:
    """Parse comma-separated CPT codes into a plain string set."""
    return {
        c.strip()
        for c in str(cpt_codes_str).split(",")
        if c.strip() and c.strip().lower() not in ("nan", "none", "")
    }


def _gap_already_satisfied(claims: List[Dict], required_cpt_codes: str,
                            lookback_months: int) -> bool:
    """
    Returns True if the member has at least one claim within the lookback window
    whose CPT code is in the measure's required CPT set.
    """
    required = _build_required_cpt_set(required_cpt_codes)
    if not required:
        return False

    cutoff = datetime.now() - timedelta(days=lookback_months * 30)
    for claim in claims:
        svc_date = _parse_service_date(claim.get("service_date", ""))
        if svc_date and svc_date >= cutoff:
            if str(claim.get("cpt_code", "")).strip() in required:
                return True
    return False


def _gap_satisfied_multi_option(claims: List[Dict], screening_options: List[Dict]) -> bool:
    """
    For measures with multiple screening paths (COL has 5, CCS has 3),
    gap is satisfied if ANY single option's CPT codes appear within that
    option's specific lookback window (OR logic).
    """
    for option in screening_options:
        if _gap_already_satisfied(
            claims,
            option.get("cpt_codes", ""),
            int(option.get("lookback_months") or 12),
        ):
            return True
    return False


def _format_claims_for_prompt(claims: List[Dict]) -> str:
    if not claims:
        return "  No claims found."
    lines = []
    for c in claims:
        lines.append(
            f"  CPT: {c.get('cpt_code','?')} | "
            f"Date: {c.get('service_date','?')} | "
            f"ICD: {c.get('icd_code','?')}"
        )
    return "\n".join(lines)


def _format_measures_for_prompt(measures: List[Dict]) -> str:
    if not measures:
        return "  None applicable."
    lines = []
    for m in measures:
        opts = m.get("screening_options", [])
        if opts:
            opt_lines = " | ".join(
                f"{o['type']} ({o['lookback_months']}mo)"
                for o in opts
            )
            cpt_info = f"Screening paths: {opt_lines}"
        else:
            cpt_info = f"Required CPT: {m['cpt_codes']}"
        lines.append(
            f"  [{m['measure_id']}] {m['name']} | "
            f"Age: {m['age_range']} | "
            f"Lookback: {m.get('lookback_months')} mo | "
            f"{cpt_info}"
        )
    return "\n".join(lines)


def _format_gaps_for_prompt(gaps: List[Dict]) -> str:
    if not gaps:
        return "  None."
    lines = []
    for g in gaps:
        lines.append(
            f"  {g.get('care_gap_id')} | "
            f"Measure: {g.get('measure_id')} ({g.get('measure_name')}) | "
            f"Created: {g.get('created_on')} | "
            f"Status: {g.get('gap_status')} | "
            f"Required CPT: {g.get('required_cpt_codes', 'N/A')}"
        )
    return "\n".join(lines)


def _format_lifestyle_for_prompt(ls: Dict) -> str:
    if not ls:
        return "  Not recorded."
    parts = [
        f"BMI: {ls.get('bmi') or '—'}",
        f"Smoking: {ls.get('smoking_status') or '—'}",
        f"Alcohol: {ls.get('alcohol_use') or '—'}",
        f"Exercise: {ls.get('exercise_frequency') or '—'}",
        f"Diet: {ls.get('diet_type') or '—'}",
        f"Sleep(hrs): {ls.get('sleep_hours_avg') or '—'}",
        f"Stress: {ls.get('stress_level') or '—'}",
    ]
    return "  " + " | ".join(parts)


def _format_family_history_for_prompt(fh: List[Dict]) -> str:
    if not fh:
        return "  None recorded."
    lines = []
    for f in fh:
        conds = ", ".join(f.get("conditions") or []) or "no conditions recorded"
        alive = "alive" if f.get("alive") else "deceased"
        age = f.get("age_or_age_at_death") or "—"
        lines.append(f"  {f.get('relation')}: {alive}, age {age} — {conds}")
    return "\n".join(lines)


def _format_hereditary_risks_for_prompt(risks: List[Dict]) -> str:
    if not risks:
        return "  None."
    return "\n".join(
        f"  ⚠ {r.get('condition')} — from {', '.join(r.get('relatives') or [])}"
        for r in risks
    )


def _format_medical_history_for_prompt(mh: Dict) -> str:
    if not mh:
        return "  Not recorded."
    lines = []
    def _bullet(title, items, fmt):
        if items:
            lines.append(f"  {title}:")
            for it in items:
                lines.append("    - " + fmt(it))
    _bullet("Current Conditions", mh.get("current_conditions") or [],
            lambda x: f"{x.get('label') or x.get('name')} ({x.get('year') or '—'})")
    _bullet("Past Conditions", mh.get("past_conditions") or [],
            lambda x: f"{x.get('label') or x.get('name')} ({x.get('year') or '—'})")
    _bullet("Surgeries", mh.get("surgeries") or [],
            lambda x: f"{x.get('label') or x.get('name')} ({x.get('year') or '—'})")
    _bullet("Allergies", mh.get("allergies") or [],
            lambda x: f"{x.get('label')} (severity: {x.get('severity') or '—'})")
    _bullet("Medications", mh.get("medications") or [],
            lambda x: f"{x.get('label')} {x.get('dose') or ''} — {x.get('purpose') or ''}")
    return "\n".join(lines) if lines else "  Not recorded."


# ── Golden-reference helpers (bypass Neo4j for eligibility / exclusion) ────────

def _is_member_excluded_golden(
    measure: Dict, member_icd_codes: List[str], member_cpt_codes: List[str]
) -> bool:
    """
    Check if a member is excluded from a HEDIS measure using the Python
    HEDIS_MEASURES golden reference (not Neo4j ExclusionCriteria nodes).

    Handles two cases:
      1. Exclusion has explicit icd10 / cpt / hcpcs lists → match directly.
      2. Exclusion only has a description (no codes) → look up canonical codes
         from _EXCLUSION_TYPE_FALLBACK_ICD by exclusion type name.

    Only "required" exclusions are evaluated (optional ones do not disqualify).
    """
    required_exclusions = measure.get("exclusions", {}).get("required", [])
    member_icd_set = set(str(icd).strip() for icd in member_icd_codes if icd)
    member_cpt_set = set(str(c).strip() for c in member_cpt_codes if c)

    # Combined lookup set: ICD codes + CPT/HCPCS codes (HCPCS codes like G9054
    # may arrive as either ICD or CPT claims depending on the source system).
    member_all_codes = member_icd_set | member_cpt_set

    for excl in required_exclusions:
        excl_type = excl.get("type", "")

        # Collect explicit code lists from the exclusion definition
        excl_icd = list(excl.get("icd10", []))
        excl_cpt = list(excl.get("cpt", [])) + list(excl.get("hcpcs", []))

        # If no explicit codes defined, fall back to type-based canonical codes.
        # Fallback may include HCPCS codes (G9054/M1017) for palliative/hospice —
        # check them against the combined set so they match regardless of how
        # the claim was stored.
        if not excl_icd and not excl_cpt:
            fallback = list(_EXCLUSION_TYPE_FALLBACK_ICD.get(excl_type, []))
            if fallback and any(code in member_all_codes for code in fallback):
                return True
            continue

        if excl_icd and any(code in member_icd_set for code in excl_icd):
            return True
        if excl_cpt and any(code in member_cpt_set for code in excl_cpt):
            return True
        # Also check HCPCS-style exclusion codes (G9054/M1017) from explicit hcpcs list
        # against the ICD set in case the payer stored them as diagnosis codes
        excl_hcpcs = list(excl.get("hcpcs", []))
        if excl_hcpcs and any(code in member_icd_set for code in excl_hcpcs):
            return True

    return False


def _get_flat_cpt_for_measure(measure: Dict) -> str:
    """
    Extract all CPT / HCPCS codes from a HEDIS_MEASURES measure dict as a
    comma-separated string suitable for _gap_already_satisfied().

    Collects codes from:
      - measure["codes"]  (keys containing 'cpt' or 'hcpcs')
      - measure["screening_options"][*]["cpt"] and ["hcpcs"]
    """
    seen: set = set()
    result: List[str] = []

    for key, codes in measure.get("codes", {}).items():
        if not isinstance(codes, list):
            continue
        kl = key.lower()
        if "cpt" in kl or "hcpcs" in kl:
            for c in codes:
                if c and c not in seen:
                    seen.add(c)
                    result.append(c)

    for opt in measure.get("screening_options", []):
        for c in list(opt.get("cpt", [])) + list(opt.get("hcpcs", [])):
            if c and c not in seen:
                seen.add(c)
                result.append(c)

    return ",".join(result)


def _get_screening_options_for_gap_check(measure: Dict) -> List[Dict]:
    """
    Convert HEDIS_MEASURES screening_options into the flat
    {type, lookback_months, cpt_codes} format expected by
    _gap_satisfied_multi_option().
    """
    options = []
    for opt in measure.get("screening_options", []):
        all_cpt = list(opt.get("cpt", [])) + list(opt.get("hcpcs", []))
        if all_cpt:
            options.append({
                "type": opt.get("type", ""),
                "lookback_months": int(opt.get("lookback_months") or 12),
                "cpt_codes": ",".join(all_cpt),
            })
    return options


def _get_primary_cpt_from_golden(measure_id: str) -> str:
    """Return the canonical primary CPT for a measure straight from the golden reference."""
    try:
        from src.hedis_golden_reference import HEDIS_MEASURES
        return HEDIS_MEASURES.get(measure_id, {}).get("primary_cpt", "") or ""
    except Exception:
        return ""


def _get_primary_icd_for_gap(measure: Dict, member_icd_codes: List[str]) -> str:
    """
    Return the single most relevant ICD-10 code to store on the CareGap node.

    Logic:
      - Condition-triggered measures (diabetes, hypertension): use the member's
        actual matching ICD from their condition list so the gap reflects their
        specific diagnosis code.
      - Preventive / age-gender measures (BCS, COL, CCS, AAP, CHL): use the
        measure's static primary_icd10 (standard screening encounter Z-code).
    """
    diag_req = str(measure.get("diagnosis_requirement", "")).lower()

    # Diabetes measures — pick member's first matching E08–E13 code
    if "diabetes" in diag_req or any(f"e{n:02d}" in diag_req for n in range(8, 14)):
        for icd in member_icd_codes:
            if str(icd).upper().startswith(("E08", "E09", "E10", "E11", "E12", "E13")):
                return icd

    # Hypertension measure — use I10 directly
    if "hypertension" in diag_req or "i10" in diag_req:
        return "I10"

    # Preventive / screening measures — use the measure's static Z-code
    return measure.get("primary_icd10", "")


def _measure_to_flat_dict(measure_id: str, measure: Dict) -> Dict:
    """
    Build the flat dict (measure_id, name, age_range, lookback_months,
    cpt_codes, screening_options, …) used by agent prompt formatters and
    gap detection — sourced entirely from the Python HEDIS_MEASURES dict.
    """
    return {
        "measure_id":           measure_id,
        "name":                 measure.get("name", ""),
        "age_range":            measure.get("age_range", ""),
        "min_age":              measure.get("min_age", 0),
        "max_age":              measure.get("max_age", 999),
        "gender_requirement":   measure.get("gender_requirement", "Any"),
        "lookback_months":      measure.get("lookback_months", 12),
        "description":          measure.get("description", ""),
        "diagnosis_requirement": measure.get("diagnosis_requirement", ""),
        "cpt_codes":            _get_flat_cpt_for_measure(measure),
        "screening_options":    _get_screening_options_for_gap_check(measure),
        "primary_cpt":          measure.get("primary_cpt", ""),
        "primary_icd10":        measure.get("primary_icd10", ""),
    }


# ── Standalone Python-only gap detection (no LLM) ────────────────────────────

def detect_care_gaps(member_id: str) -> Dict[str, Any]:
    """
    Run pure-Python HEDIS gap detection for a member and write CareGap nodes
    to Neo4j.  No LLM involved — safe to call on every member add/update.

    Uses HEDIS_MEASURES Python dict (golden reference) directly for eligibility
    and exclusion logic — bypasses Neo4j QualityMeasure / ExclusionCriteria
    nodes entirely, avoiding stale-data problems (e.g. missing
    diagnosis_requirement, empty exclusion ICD lists).

    Returns a summary dict:
      {
        "member_id": str,
        "gaps_created": [measure_id, ...],   # newly written this call
        "compliant":    [measure_id, ...],
        "excluded":     [measure_id, ...],
        "not_applicable": int,               # measures filtered by age/gender/dx
      }
    """
    from src.hedis_golden_reference import HEDIS_MEASURES

    profile = get_member_profile(member_id)
    if not profile:
        return {"error": f"Member {member_id} not found"}

    age    = _parse_age(profile.get("age_str", "0"))
    gender = str(profile.get("gender", ""))

    claims              = get_member_claims_cpt_codes(member_id)
    claim_icd_codes     = [c.get("icd_code", "") for c in claims if c.get("icd_code")]
    claim_cpt_codes     = [c.get("cpt_code", "") for c in claims if c.get("cpt_code")]
    condition_icd_codes = _icd_codes_from_conditions(
        profile.get("chronic_conditions") or []
    )
    # Combined ICD evidence: claims + conditions (deduped)
    icd_codes = list(set(claim_icd_codes + condition_icd_codes))

    gaps_created:     List[str] = []
    compliant:        List[str] = []
    excluded:         List[str] = []
    not_applicable_n: int       = 0

    from src.neo4j_connection import get_knowledge_graph as _get_kg
    _kg = _get_kg()
    today = datetime.now().strftime("%Y-%m-%d")

    # Demo scope. Only these HEDIS measures are evaluated against members.
    # Override at runtime by setting CARE_GAP_ENABLED_MEASURES="BCS,CCS,COL,AAP,..."
    # in the environment, or set it to "*" to evaluate all measures.
    import os as _os
    _enabled_raw = _os.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL").strip()
    if _enabled_raw == "*" or _enabled_raw.lower() == "all":
        ENABLED_MEASURES = None  # evaluate everything
    else:
        ENABLED_MEASURES = {m.strip().upper() for m in _enabled_raw.split(",") if m.strip()}

    # Defensive sweep — if the demo scope is restricted, hard-delete any
    # CareGap on this member whose measure is OUTSIDE the enabled set.
    # Catches stale gaps left over from earlier runs that used a wider
    # scope, so the email / PDF / member panel can never surface them.
    if ENABLED_MEASURES is not None:
        try:
            _kg.execute_write("""
                MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
                WHERE NOT coalesce(g.measure_id, '') IN $enabled
                DETACH DELETE g
            """, {"mid": member_id, "enabled": list(ENABLED_MEASURES)})
        except Exception:
            pass  # best-effort; do not block detection

    for measure_id, measure in HEDIS_MEASURES.items():
        # ── 0. Demo-scope filter ──────────────────────────────────────────────
        if ENABLED_MEASURES is not None and measure_id.upper() not in ENABLED_MEASURES:
            continue

        # ── 1. Eligibility: age / gender / diagnosis ──────────────────────────
        if not _measure_applies(measure, age, gender, icd_codes):
            not_applicable_n += 1
            continue

        # ── 2. Exclusions (golden reference + fallback codes) ─────────────────
        if _is_member_excluded_golden(measure, icd_codes, claim_cpt_codes):
            excluded.append(measure_id)
            continue

        # ── 3. Compliance: CPT code within lookback window ────────────────────
        options   = _get_screening_options_for_gap_check(measure)
        satisfied = (
            _gap_satisfied_multi_option(claims, options) if options
            else _gap_already_satisfied(
                claims,
                _get_flat_cpt_for_measure(measure),
                int(measure.get("lookback_months") or 12),
            )
        )

        if not satisfied:
            gap_id = f"AUTO-{member_id}-{measure_id}"
            # If the gap was previously closed by a manual claim
            # (close_member_gap.py stamps g.claim_id), respect that closure
            # and DO NOT re-open it. Otherwise the panel-open → detect_care_gaps
            # cycle would resurrect the gap, and a subsequent script run would
            # create a duplicate claim. This is the gap that made the user see
            # 6 claims when only 3 should exist.
            existing = _kg.run_query("""
                MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap {care_gap_id: $gid})
                RETURN g.is_open AS is_open, g.claim_id AS claim_id
            """, {"mid": member_id, "gid": gap_id}) or []
            already_manually_closed = bool(existing and existing[0].get("claim_id") and existing[0].get("is_open") is False)
            if already_manually_closed:
                # Honor the manual closure — count this measure as compliant.
                compliant.append(measure_id)
                continue

            merge_care_gap(
                care_gap_id=gap_id,
                member_id=member_id,
                measure_id=measure_id,
                gap_status="Open",
                is_open=True,
                created_on=today,
                closed_on="",
                primary_cpt_code=measure.get("primary_cpt", ""),
                primary_icd10=_get_primary_icd_for_gap(measure, icd_codes),
            )
            gaps_created.append(measure_id)
        else:
            # Close any stale open gap for this measure (Excel-loaded or prior run)
            _kg.execute_write("""
                MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
                      -[:RELATES_TO]->(q:QualityMeasure {measure_id: $meas})
                WHERE g.is_open = true
                SET g.is_open = false,
                    g.gap_status = 'Closed',
                    g.closed_on  = $today
            """, {"mid": member_id, "meas": measure_id, "today": today})
            compliant.append(measure_id)

    return {
        "member_id":      member_id,
        "gaps_created":   gaps_created,
        "compliant":      compliant,
        "excluded":       excluded,
        "not_applicable": not_applicable_n,
    }


# ── Agent System ──────────────────────────────────────────────────────────────

class CareGapAgentSystem:
    """
    6-agent system for HEDIS care gap analysis.

    Supports two modes:
      - validate_and_suggest()        — blocking, returns full result dict
      - validate_and_suggest_stream() — SSE generator, streams per-agent events
    """

    def __init__(self):
        self.model_client = BedrockChatCompletionClient(
            model_id=settings.bedrock_model_id,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
            max_tokens=2048,
            temperature=0.7,
        )
        self._build_agents()

    def _build_agents(self):
        # ── Agent 1: Patient Analyst ───────────────────────────────────────────
        self.patient_analyst = AssistantAgent(
            name="patient_analyst",
            system_message="""You are the Patient Analyst for a HEDIS care gap system.

You receive pre-fetched member profile, claims, lifestyle, family history,
and medical history data from Neo4j (sections 1, 1B, 1C, 1D, 1E).

Your job (respond in ≤14 lines):
- Confirm member age, gender, and insurance plan
- Note the PCP name and specialty
- Identify chronic conditions from ICD codes (E11.x = Type 2 Diabetes)
- Summarise lifestyle risk factors (high BMI, smoking, heavy alcohol, sedentary)
- Summarise hereditary / family-history risks present in first-degree relatives
- Flag if any of these signals should prompt earlier screening than standard
  HEDIS age bands (e.g. family colorectal cancer → earlier COL; family diabetes
  + BMI ≥ 25 → prioritize GSD/EED)

Format:
PATIENT SUMMARY
  Name/ID  : ...
  Age/Gender: ... (eligible for diabetes measures: YES/NO)
  Plan     : ... | $0 copay preventive
  PCP      : ... (specialty, network status)
  Conditions: ... (from ICD codes in claims)
  Lifestyle risks: ... (BMI / smoking / alcohol / exercise / diet flags)
  Family / hereditary risks: ... (first-degree relatives → condition list)
  Risk-adjusted screening flags: ... (which measures to prioritize and why)""",
            model_client=self.model_client,
        )

        # ── Agent 2: HEDIS Measure Agent ──────────────────────────────────────
        self.hedis_measure_agent = AssistantAgent(
            name="hedis_measure_agent",
            system_message="""You are the HEDIS Measure Agent for a care gap system.

You receive the list of applicable quality measures from the Neo4j golden reference.

Your job (respond in ≤12 lines):
- List each applicable measure with measure ID, name, age range, lookback window
- For multi-path measures (COL: 5 paths, CCS: 3 paths) list each screening option
- Note diabetes measures (GSD/EED/KED/BPD) require confirmed E11.x ICD code
- Confirm measures NOT applicable (gender/age/diagnosis mismatch) are correctly excluded

Format per measure:
[MeasureID] [Name] — Age: X-Y | Lookback: N mo | CPT/paths: ...""",
            model_client=self.model_client,
        )

        # ── Agent 3: Exclusion Agent ───────────────────────────────────────────
        self.exclusion_agent = AssistantAgent(
            name="exclusion_agent",
            system_message="""You are the Exclusion Agent for a HEDIS care gap system.

You receive the system's exclusion check results from the Neo4j rulebook.

Your job (respond in ≤10 lines):
- For each excluded measure: confirm the exclusion and state the exact clinical reason + code
  (e.g. BCS EXCLUDED — bilateral mastectomy ICD Z90.13)
- For non-excluded measures: confirm the member is NOT excluded
- Reference the specific ICD-10 or CPT code that triggered each exclusion

Format per measure:
[MeasureID] — EXCLUDED (reason | code) | NOT EXCLUDED (exclusion criteria checked: none match)""",
            model_client=self.model_client,
        )

        # ── Agent 4: Code Validator ────────────────────────────────────────────
        self.code_validator = AssistantAgent(
            name="code_validator",
            system_message="""You are the Code Validator for a HEDIS care gap system.

You receive the member's claims history and the system's CPT code compliance check results.

Your job (respond in ≤15 lines):
- For each applicable (non-excluded) measure, confirm the system's COMPLIANT/NON-COMPLIANT verdict
- For NON-COMPLIANT: state exactly why — no claim found, wrong CPT code, or claim outside lookback
- For COL/CCS (multi-path): state which option(s) were checked and whether any path was satisfied
- Flag borderline cases (claim date within 30 days of lookback cutoff)

Format per measure:
[MeasureID] — CPT found: X / not found | Service date: within/outside N-mo lookback
              VERDICT CONFIRMED: COMPLIANT / NON-COMPLIANT""",
            model_client=self.model_client,
        )

        # ── Agent 5: Care Gap Agent ────────────────────────────────────────────
        self.care_gap_agent = AssistantAgent(
            name="care_gap_agent",
            system_message="""You are the Care Gap Agent for a HEDIS care gap system.

You receive the validated gap status from the Code Validator.

Your job (respond in ≤12 lines):
- Produce the definitive care gap report: OPEN GAP / COMPLIANT / EXCLUDED per measure
- For OPEN GAPS: state the exact CPT code(s) needed to close the gap and the deadline
- Confirm that gap nodes have been written to Neo4j for all OPEN gaps
- Priority rank the open gaps (shorter lookback = higher priority)

Format per gap:
[MeasureID] [Name]: OPEN GAP  ← Priority #N
  Close with: CPT XXXXX ([procedure name]) within N months
  Neo4j CareGap node: AUTO-[MemberID]-[MeasureID] ✓""",
            model_client=self.model_client,
        )

        # ── Agent 6: Recommendation Agent ─────────────────────────────────────
        self.recommendation_agent = AssistantAgent(
            name="recommendation_agent",
            system_message="""You are the Recommendation Agent for a HEDIS care gap system.

You receive the complete care gap analysis from the team above, PLUS the
member's lifestyle (Section 1B), family/ancestral history (Section 1C),
hereditary risk signals (Section 1D), and medical history (Section 1E).

Your job:
1. Provide a FINAL CARE GAP SUMMARY TABLE (one line per measure: status + action)
2. For each OPEN GAP:
   - Exact CPT code + procedure name to close the gap
   - In-network provider type (Radiology→BCS, OB/GYN→CCS, GI→COL, Lab/Endo→GSD/EED/KED/BPD)
   - Member cost: $0 copay (all preventive services under plan PL-001)
   - Best outreach channel: Phone (urgent/chronic), SMS (screening reminders)
3. RISK-ADJUSTED PRIORITIZATION: re-order priorities using hereditary risk +
   lifestyle. Examples:
     - Family history of colorectal cancer in a first-degree relative → bump
       COL to Priority #1 even if age-band-standard
     - Family diabetes + BMI ≥ 25 + smoking → escalate GSD/EED/CBP
     - Family breast cancer → emphasise BCS and recommend earlier mammography
   When you escalate a gap, state exactly which hereditary/lifestyle signal
   drove the decision.
4. Write a 4-6 line care manager script for the #1 priority gap that
   references the hereditary/lifestyle context where relevant (e.g.
   "Because your mother was diagnosed with diabetes, earlier screening
   is especially important for you.")
5. Suggest 1–2 non-HEDIS lifestyle interventions if warranted (nutrition,
   smoking cessation referral, etc.) — clearly labelled as "Supplemental".

End your response with:
TOTAL OPEN GAPS: N
RECOMMENDED NEXT ACTION: [specific action for top gap]
HEREDITARY RISK FLAG: [YES/NO — if YES, one-line reason]""",
            model_client=self.model_client,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _validate_member(self, member_id: str) -> Dict[str, Any]:
        """
        Pure-Python validation (no LLM): exclusions + CPT lookback checks.
        Writes CareGap nodes to Neo4j for newly detected gaps.
        Returns a structured dict; sets 'error' key if member not found.

        Uses HEDIS_MEASURES golden reference (Python dict) for all eligibility
        and exclusion logic — no dependency on Neo4j measure/exclusion nodes.
        """
        from src.hedis_golden_reference import HEDIS_MEASURES

        profile = get_member_profile(member_id)
        if not profile:
            return {"error": f"Member {member_id} not found in knowledge graph"}

        age    = _parse_age(profile.get("age_str", "0"))
        gender = str(profile.get("gender", ""))

        claims              = get_member_claims_cpt_codes(member_id)
        claim_icd_codes     = [c.get("icd_code", "") for c in claims if c.get("icd_code")]
        claim_cpt_codes     = [c.get("cpt_code", "") for c in claims if c.get("cpt_code")]
        condition_icd_codes = _icd_codes_from_conditions(
            profile.get("chronic_conditions") or []
        )
        icd_codes = list(set(claim_icd_codes + condition_icd_codes))

        # Demo-scope filter — same env var honoured by detect_care_gaps and
        # the dashboard endpoints. Without this, the 6-agent pipeline (which
        # runs when the operator presses "Proceed with Outreach") would
        # iterate every HEDIS measure and re-create AAP / KED / etc. gaps
        # behind the user's back. Default scope: BCS, CCS, COL only.
        import os as _os_dem
        _enabled_raw_v = _os_dem.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL").strip()
        if _enabled_raw_v in ("*", "all", "ALL"):
            ENABLED_V = None
        else:
            ENABLED_V = {m.strip().upper() for m in _enabled_raw_v.split(",") if m.strip()}

        # Build applicable list using golden reference directly
        applicable: List[Dict] = []
        for mid, m in HEDIS_MEASURES.items():
            if ENABLED_V is not None and mid.upper() not in ENABLED_V:
                continue
            if _measure_applies(m, age, gender, icd_codes):
                applicable.append(_measure_to_flat_dict(mid, m))

        detected_gaps:     List[Dict] = []
        satisfied_measures: List[str] = []
        excluded_measures:  List[str] = []

        for flat in applicable:
            raw_measure = HEDIS_MEASURES[flat["measure_id"]]

            # Exclusion check (golden reference + fallback codes)
            if _is_member_excluded_golden(raw_measure, icd_codes, claim_cpt_codes):
                excl_types = [
                    e.get("type", "excluded")
                    for e in raw_measure.get("exclusions", {}).get("required", [])
                ]
                reason = excl_types[0] if excl_types else "excluded"
                excluded_measures.append(f"{flat['measure_id']} ({reason})")
                continue

            options   = flat.get("screening_options", [])
            satisfied = (
                _gap_satisfied_multi_option(claims, options) if options
                else _gap_already_satisfied(
                    claims,
                    flat.get("cpt_codes", ""),
                    int(flat.get("lookback_months") or 12),
                )
            )

            if not satisfied:
                detected_gaps.append(flat)
                gap_id = f"AUTO-{member_id}-{flat['measure_id']}"
                merge_care_gap(
                    care_gap_id=gap_id,
                    member_id=member_id,
                    measure_id=flat["measure_id"],
                    gap_status="Open",
                    is_open=True,
                    created_on=datetime.now().strftime("%Y-%m-%d"),
                    closed_on="",
                    primary_cpt_code=flat.get("primary_cpt", "") or
                                     _get_primary_cpt_from_golden(flat["measure_id"]),
                    primary_icd10=_get_primary_icd_for_gap(raw_measure, icd_codes),
                )
            else:
                satisfied_measures.append(flat["measure_id"])

        existing_gaps = get_member_open_gaps(member_id)

        # Extended patient record — used to prioritise recommendations and
        # surface hereditary risk signals to the LLM agents. Falls back to
        # empty dicts for members who don't yet have an extended record.
        try:
            extended = get_member_extended_profile(member_id)
        except Exception as _exc:
            logger.warning(f"Extended profile fetch failed for {member_id}: {_exc}")
            extended = {
                "lifestyle": {}, "family_history": [],
                "medical_history": {}, "hereditary_risks": [],
            }

        return {
            "profile":            profile,
            "age":                age,
            "gender":             gender,
            "claims":             claims,
            "icd_codes":          icd_codes,
            "applicable":         applicable,
            "detected_gaps":      detected_gaps,
            "satisfied_measures": satisfied_measures,
            "excluded_measures":  excluded_measures,
            "existing_gaps":      existing_gaps,
            "lifestyle":          extended.get("lifestyle", {}),
            "family_history":     extended.get("family_history", []),
            "medical_history":    extended.get("medical_history", {}),
            "hereditary_risks":   extended.get("hereditary_risks", []),
        }

    def _build_task(self, v: Dict, member_id: str) -> str:
        """Build the structured task string from a _validate_member() result dict."""
        profile = v["profile"]
        age = v["age"]
        gender = v["gender"]
        claims = v["claims"]
        icd_codes = v["icd_codes"]
        applicable = v["applicable"]
        detected_gaps = v["detected_gaps"]
        satisfied_measures = v["satisfied_measures"]
        excluded_measures = v["excluded_measures"]
        existing_gaps = v["existing_gaps"]

        return f"""=== HEDIS CARE GAP ANALYSIS — Member {member_id} ===

[SECTION 1 — MEMBER PROFILE]  ← for patient_analyst
  Member ID : {member_id}
  Name      : {profile.get('name')}
  Age       : {profile.get('age_str')} (numeric: {age})
  Gender    : {gender}
  DOB       : {profile.get('dob')}
  Plan      : {profile.get('plan_id')} | Copay: ${profile.get('copay')} | Preventive: $0
  Covered   : {profile.get('preventive_covered')}
  Eligibility: {profile.get('eligibility_rules')}
  PCP       : {profile.get('pcp_name')} | {profile.get('pcp_specialty')} | {profile.get('pcp_network_status')}
  Chronic Conditions (from member record): {profile.get('chronic_conditions') or 'None recorded'}
  ICD codes (claims + conditions combined): {list(set(icd_codes[:15]))}

[SECTION 1B — LIFESTYLE]  ← for patient_analyst
{_format_lifestyle_for_prompt(v.get('lifestyle') or {})}

[SECTION 1C — FAMILY / ANCESTRAL HISTORY]  ← for patient_analyst + recommendation_agent
{_format_family_history_for_prompt(v.get('family_history') or [])}

[SECTION 1D — HEREDITARY RISK SIGNALS (first-degree relatives)]  ← for recommendation_agent
{_format_hereditary_risks_for_prompt(v.get('hereditary_risks') or [])}

[SECTION 1E — MEDICAL HISTORY]  ← for patient_analyst
{_format_medical_history_for_prompt(v.get('medical_history') or {})}

[SECTION 2 — APPLICABLE HEDIS MEASURES]  ← for hedis_measure_agent
  Total applicable: {len(applicable)}
{_format_measures_for_prompt(applicable)}

[SECTION 3 — EXCLUSION CHECK RESULTS]  ← for exclusion_agent
  Excluded by Neo4j rulebook : {excluded_measures or 'None'}
  Not excluded (all {len(applicable) - len(excluded_measures)} remaining measures passed exclusion check)

[SECTION 4 — CLAIMS HISTORY + CPT VALIDATION]  ← for code_validator
  Total claims: {len(claims)}
{_format_claims_for_prompt(claims)}
  System CPT check results:
    COMPLIANT (gap satisfied)     : {satisfied_measures or 'None'}
    NON-COMPLIANT (gap detected)  : {[m['measure_id'] for m in detected_gaps] or 'None'}

[SECTION 5 — OPEN GAPS WRITTEN TO NEO4J]  ← for care_gap_agent
  Auto-created CareGap nodes this session: {[f"AUTO-{member_id}-{m['measure_id']}" for m in detected_gaps] or 'None'}
  Existing open gaps in graph (including Excel-loaded):
{_format_gaps_for_prompt(existing_gaps)}

[SECTION 6 — OUTREACH CONTEXT]  ← for recommendation_agent
  Plan ID   : {profile.get('plan_id')}
  Coverage  : All preventive services $0 copay, $500 deductible (waived for preventive)
  Open gaps for outreach: {[m['measure_id'] for m in detected_gaps]}
  Priority order: shorter lookback = more urgent
    (GSD/EED/KED/BPD = 12 mo, BCS = 24 mo, CCS = 36 mo, COL up to 120 mo)

=== EACH AGENT: RESPOND TO YOUR DESIGNATED SECTION ONLY ==="""

    def _run_team(self, task: str) -> Dict[str, str]:
        """Run all 6 agents as a RoundRobin team (blocking). Returns all responses at once."""
        import asyncio

        async def _run():
            team = RoundRobinGroupChat(
                participants=[
                    self.patient_analyst,
                    self.hedis_measure_agent,
                    self.exclusion_agent,
                    self.code_validator,
                    self.care_gap_agent,
                    self.recommendation_agent,
                ],
                # 6 agents + 1 task message + 1 buffer = 8
                termination_condition=MaxMessageTermination(max_messages=8),
            )
            result = await team.run(task=task)
            return {
                msg.source: msg.content
                for msg in result.messages
                if hasattr(msg, "source") and msg.source != "user"
            }

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _run()).result()
        return asyncio.run(_run())

    def _run_agent_single(self, agent, task: str) -> str:
        """
        Run a single AssistantAgent synchronously and return its text response.
        Resets agent state before each call to prevent history bleed between runs.
        """
        import asyncio
        from autogen_agentchat.messages import TextMessage
        from autogen_core import CancellationToken

        async def _run():
            await agent.on_reset(CancellationToken())
            result = await agent.on_messages(
                [TextMessage(content=task, source="user")],
                CancellationToken(),
            )
            return result.chat_message.content if result and result.chat_message else ""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _run()).result()
        return asyncio.run(_run())

    # ── Public API ─────────────────────────────────────────────────────────────

    def validate_and_suggest(self, member_id: str) -> Dict[str, Any]:
        """
        Blocking mode — runs full validation + all 6 agents, returns when done.
        Used by the original POST /api/v1/care-gaps/validate/<member_id> endpoint.
        """
        v = self._validate_member(member_id)
        if "error" in v:
            return v

        task = self._build_task(v, member_id)
        responses = self._run_team(task)

        return {
            "member_id": member_id,
            "member_name": v["profile"].get("name"),
            "age": v["profile"].get("age_str"),
            "gender": v["gender"],
            "applicable_measures": [m["measure_id"] for m in v["applicable"]],
            "compliant_measures": v["satisfied_measures"],
            "excluded_measures": v["excluded_measures"],
            "open_gaps_detected": [m["measure_id"] for m in v["detected_gaps"]],
            "existing_graph_gaps": v["existing_gaps"],
            "agent_responses": responses,
        }

    def validate_and_suggest_stream(self, member_id: str) -> Generator[Tuple[str, Any], None, None]:
        """
        Streaming mode — generator that yields (event_type, data) tuples for SSE.

        Event sequence:
          ('metadata', dict)      — immediately after Python validation (no LLM yet)
          ('agent_start', dict)   — {'agent': name} just before each LLM call
          ('agent_done',  dict)   — {'agent': name, 'content': text} when agent finishes
          ('complete',    dict)   — final summary after all 6 agents finish
          ('error',       dict)   — if member not found or exception

        Each agent receives cumulative context — it sees all previous agents' outputs.
        This mirrors RoundRobinGroupChat behaviour while enabling per-agent streaming.
        """
        try:
            v = self._validate_member(member_id)
        except Exception as exc:
            yield ("error", {"message": str(exc)})
            return

        if "error" in v:
            yield ("error", v)
            return

        profile = v["profile"]

        # ── Metadata event — instant, no LLM ─────────────────────────────────
        yield ("metadata", {
            "member_id": member_id,
            "member_name": profile.get("name"),
            "age": profile.get("age_str"),
            "gender": v["gender"],
            "applicable_measures": [m["measure_id"] for m in v["applicable"]],
            "compliant_measures": v["satisfied_measures"],
            "excluded_measures": v["excluded_measures"],
            "open_gaps_detected": [m["measure_id"] for m in v["detected_gaps"]],
            "existing_graph_gaps": v["existing_gaps"],
        })

        base_task = self._build_task(v, member_id)
        # Cumulative task: each agent sees all previous agents' outputs
        cumulative_task = base_task

        agents_in_order = [
            self.patient_analyst,
            self.hedis_measure_agent,
            self.exclusion_agent,
            self.code_validator,
            self.care_gap_agent,
            self.recommendation_agent,
        ]

        agent_responses: Dict[str, str] = {}

        for agent in agents_in_order:
            yield ("agent_start", {"agent": agent.name})
            try:
                content = self._run_agent_single(agent, cumulative_task)
            except Exception as exc:
                content = f"[Agent error: {exc}]"
            agent_responses[agent.name] = content
            yield ("agent_done", {"agent": agent.name, "content": content})
            # Build context for next agent
            cumulative_task += f"\n\n[{agent.name.upper()} ANALYSIS]\n{content}"

        yield ("complete", {
            "member_id": member_id,
            "open_gaps_detected": [m["measure_id"] for m in v["detected_gaps"]],
            "agent_responses": agent_responses,
        })
