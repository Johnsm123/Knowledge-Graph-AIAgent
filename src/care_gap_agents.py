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
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from config.settings import settings
from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_applicable_measures,
    get_member_claims_cpt_codes,
    get_member_profile,
    merge_care_gap,
    check_member_exclusions,
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
CHRONIC_CONDITION_ICD_MAP = {
    "Diabetes (Type 1)":              ["E10.9", "E10.65", "E10.8", "E10.40"],
    "Diabetes (Type 2)":              ["E11.9", "E11.65", "E11.8", "E11.40"],
    "Hypertension":                   ["I10"],
    "Coronary Artery Disease (CAD)":  ["I25.10", "I25.9"],
    "Congestive Heart Failure (CHF)": ["I50.9", "I50.32"],
    "COPD":                           ["J44.9", "J44.1"],
    "Asthma":                         ["J45.909", "J45.20"],
    "Chronic Kidney Disease (CKD)":   ["N18.9", "N18.3", "N18.4", "N18.5"],
    "End-Stage Renal Disease (ESRD)": ["N18.6", "Z99.2"],
    "Depression / Anxiety":           ["F32.9", "F41.9", "F33.0"],
    "Cancer (Active)":                ["C80.1", "C78.9"],
    "Hospice / Palliative Care":      ["Z51.5", "Z51.89"],
    "Pregnancy":                      ["Z34.90", "Z34.00"],
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

    # Diabetes measures require Type 1 (E10.x), Type 2 (E11.x) or Other (E13.x)
    # Covers GSD, EED, KED, BPD — golden reference states "E10.x, E11.x, E13.x"
    diag_req = str(measure.get("diagnosis_requirement", "")).lower()
    if "diabetes" in diag_req or "e10" in diag_req or "e11" in diag_req or "e13" in diag_req:
        has_diabetes_icd = any(
            str(icd).upper().startswith(("E10", "E11", "E13"))
            for icd in icd_codes
        )
        if not has_diabetes_icd:
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


# ── Standalone Python-only gap detection (no LLM) ────────────────────────────

def detect_care_gaps(member_id: str) -> Dict[str, Any]:
    """
    Run pure-Python HEDIS gap detection for a member and write CareGap nodes
    to Neo4j.  No LLM involved — safe to call on every member add/update.

    Returns a summary dict:
      {
        "member_id": str,
        "gaps_created": [measure_id, ...],   # newly written this call
        "compliant":    [measure_id, ...],
        "excluded":     [measure_id, ...],
        "not_applicable": int,               # measures filtered by age/gender/dx
      }
    """
    profile = get_member_profile(member_id)
    if not profile:
        return {"error": f"Member {member_id} not found"}

    age    = _parse_age(profile.get("age_str", "0"))
    gender = str(profile.get("gender", ""))

    claims          = get_member_claims_cpt_codes(member_id)
    claim_icd_codes = [c.get("icd_code", "") for c in claims if c.get("icd_code")]
    condition_icd_codes = _icd_codes_from_conditions(
        profile.get("chronic_conditions") or []
    )
    icd_codes = list(set(claim_icd_codes + condition_icd_codes))

    all_measures = get_applicable_measures(age, gender)
    applicable   = [m for m in all_measures if _measure_applies(m, age, gender, icd_codes)]

    gaps_created: List[str] = []
    compliant:    List[str] = []
    excluded:     List[str] = []

    for measure in applicable:
        exclusions = check_member_exclusions(
            member_id, measure["measure_id"],
            extra_icd_codes=condition_icd_codes,
        )
        if exclusions:
            excluded.append(measure["measure_id"])
            continue

        options   = measure.get("screening_options", [])
        satisfied = (
            _gap_satisfied_multi_option(claims, options) if options
            else _gap_already_satisfied(
                claims,
                measure.get("cpt_codes", ""),
                int(measure.get("lookback_months") or 12),
            )
        )

        if not satisfied:
            gap_id = f"AUTO-{member_id}-{measure['measure_id']}"
            merge_care_gap(
                care_gap_id=gap_id,
                member_id=member_id,
                measure_id=measure["measure_id"],
                gap_status="Open",
                is_open=True,
                created_on=datetime.now().strftime("%Y-%m-%d"),
                closed_on="",
            )
            gaps_created.append(measure["measure_id"])
        else:
            compliant.append(measure["measure_id"])

    return {
        "member_id":      member_id,
        "gaps_created":   gaps_created,
        "compliant":      compliant,
        "excluded":       excluded,
        "not_applicable": len(all_measures) - len(applicable),
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
        from autogen_core.models import ModelInfo
        self.model_client = AzureOpenAIChatCompletionClient(
            azure_deployment=settings.openai_model,          # Azure deployment name
            azure_endpoint=settings.endpoint,
            api_key=settings.openai_api_key,
            api_version=settings.azure_openai_api_version,
            model="gpt-5-chat-2025-10-03",                   # resolved model for token estimation
            model_info=ModelInfo(
                vision=True,
                function_calling=True,
                json_output=True,
                family="gpt-5",
                structured_output=True,
                multiple_system_messages=True,
            ),
        )
        self._build_agents()

    def _build_agents(self):
        # ── Agent 1: Patient Analyst ───────────────────────────────────────────
        self.patient_analyst = AssistantAgent(
            name="patient_analyst",
            system_message="""You are the Patient Analyst for a HEDIS care gap system.

You receive pre-fetched member profile and claims data from Neo4j.

Your job (respond in ≤8 lines):
- Confirm member age, gender, and insurance plan
- Note the PCP name and specialty
- Identify chronic conditions from ICD codes (E11.x = Type 2 Diabetes)
- Flag if member's age/gender makes them eligible for female-only or diabetes measures

Format:
PATIENT SUMMARY
  Name/ID  : ...
  Age/Gender: ...  (eligible for diabetes measures: YES/NO)
  Plan     : ... | $0 copay preventive
  PCP      : ... (specialty, network status)
  Conditions: ... (from ICD codes in claims)""",
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

You receive the complete care gap analysis from the team above.

Your job:
1. Provide a FINAL CARE GAP SUMMARY TABLE (one line per measure: status + action)
2. For each OPEN GAP:
   - Exact CPT code + procedure name to close the gap
   - In-network provider type (Radiology→BCS, OB/GYN→CCS, GI→COL, Lab/Endo→GSD/EED/KED/BPD)
   - Member cost: $0 copay (all preventive services under plan PL-001)
   - Best outreach channel: Phone (urgent/chronic), SMS (screening reminders)
3. Write a 4-6 line care manager script for the #1 priority gap

End your response with:
TOTAL OPEN GAPS: N
RECOMMENDED NEXT ACTION: [specific action for top gap]""",
            model_client=self.model_client,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _validate_member(self, member_id: str) -> Dict[str, Any]:
        """
        Pure-Python validation (no LLM): exclusions + CPT lookback checks.
        Writes CareGap nodes to Neo4j for newly detected gaps.
        Returns a structured dict; sets 'error' key if member not found.
        """
        profile = get_member_profile(member_id)
        if not profile:
            return {"error": f"Member {member_id} not found in knowledge graph"}

        age = _parse_age(profile.get("age_str", "0"))
        gender = str(profile.get("gender", ""))

        claims = get_member_claims_cpt_codes(member_id)
        # ICD codes from actual claims
        claim_icd_codes = [c.get("icd_code", "") for c in claims if c.get("icd_code")]

        # Supplement with ICD codes derived from stored chronic_conditions.
        # This ensures newly added members (zero claims) still have diabetes /
        # chronic disease measures evaluated correctly.
        condition_icd_codes = _icd_codes_from_conditions(
            profile.get("chronic_conditions") or []
        )
        icd_codes = list(set(claim_icd_codes + condition_icd_codes))

        all_measures = get_applicable_measures(age, gender)
        applicable = [m for m in all_measures if _measure_applies(m, age, gender, icd_codes)]

        detected_gaps: List[Dict] = []
        satisfied_measures: List[str] = []
        excluded_measures: List[str] = []

        for measure in applicable:
            # Pass condition-derived ICD codes so exclusion checks also work
            # for members who have conditions recorded but no claims yet.
            exclusions = check_member_exclusions(
                member_id, measure["measure_id"],
                extra_icd_codes=condition_icd_codes,
            )
            if exclusions:
                reason = exclusions[0].get("type", "excluded")
                excluded_measures.append(f"{measure['measure_id']} ({reason})")
                continue

            options = measure.get("screening_options", [])
            if options:
                satisfied = _gap_satisfied_multi_option(claims, options)
            else:
                satisfied = _gap_already_satisfied(
                    claims,
                    measure.get("cpt_codes", ""),
                    int(measure.get("lookback_months") or 12),
                )

            if not satisfied:
                detected_gaps.append(measure)
                gap_id = f"AUTO-{member_id}-{measure['measure_id']}"
                merge_care_gap(
                    care_gap_id=gap_id,
                    member_id=member_id,
                    measure_id=measure["measure_id"],
                    gap_status="Open",
                    is_open=True,
                    created_on=datetime.now().strftime("%Y-%m-%d"),
                    closed_on="",
                )
            else:
                satisfied_measures.append(measure["measure_id"])

        existing_gaps = get_member_open_gaps(member_id)

        return {
            "profile": profile,
            "age": age,
            "gender": gender,
            "claims": claims,
            "icd_codes": icd_codes,
            "applicable": applicable,
            "detected_gaps": detected_gaps,
            "satisfied_measures": satisfied_measures,
            "excluded_measures": excluded_measures,
            "existing_gaps": existing_gaps,
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
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _run()).result()
            return loop.run_until_complete(_run())
        except RuntimeError:
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
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _run()).result()
            return loop.run_until_complete(_run())
        except RuntimeError:
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
