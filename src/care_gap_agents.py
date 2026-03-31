"""
Care Gap Validation Agent System.

Workflow per member:
  1. Fetch member profile + claims from Neo4j
  2. Query QualityMeasure golden reference nodes to find applicable measures
  3. Cross-check member's CPT codes against measure's required codes + lookback window
  4. CDC-HbA1c additionally checks for Diabetes ICD code (E11.x) in claims
  5. If gap detected → create/update CareGap node in Neo4j
  6. Pull resolution text from QualityMeasure node → LLM generates actionable suggestion

Agents:
  - care_gap_validator  : validates compliance per measure, explains why gap is open
  - outreach_advisor    : generates prioritised outreach script for care manager
  - benefit_checker     : confirms plan coverage and member cost per gap
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from config.settings import settings
from src.care_gap_neo4j import (
    get_member_open_gaps,
    get_applicable_measures,
    get_member_claims_cpt_codes,
    get_member_profile,
    merge_care_gap,
)

logger = logging.getLogger(__name__)


# ── Pure Python helpers (no LLM) ─────────────────────────────────────────────

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
      - Age must fall within measure's AgeRange
      - Gender must match if measure specifies Female/Male
      - CDC-HbA1c additionally requires at least one E11.x ICD code in claims
    """
    age_range = str(measure.get("age_range", ""))
    gender_required = None

    if "Female" in age_range:
        gender_required = "F"
        age_range = age_range.replace("Female", "").strip()
    elif "Male" in age_range:
        gender_required = "M"
        age_range = age_range.replace("Male", "").strip()

    if gender_required and gender.upper()[0] != gender_required:
        return False

    try:
        parts = age_range.split("-")
        min_age, max_age = int(parts[0].strip()), int(parts[1].strip())
        if not (min_age <= age <= max_age):
            return False
    except Exception:
        pass

    # CDC-HbA1c only applies to members with a confirmed Diabetes diagnosis
    if measure.get("measure_id") == "CDC-HbA1c":
        if not any(str(icd).startswith("E11") for icd in icd_codes):
            return False

    return True


def _build_required_cpt_set(cpt_codes_str: str) -> set:
    """
    Parse comma-separated CPT codes from golden reference into a set of plain strings.
    e.g. '83036,83037' → {'83036', '83037'}
    """
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


def _format_claims_for_prompt(claims: List[Dict]) -> str:
    """Format claims list cleanly for the LLM prompt."""
    if not claims:
        return "  No claims found."
    lines = []
    for c in claims:
        lines.append(f"  CPT: {c.get('cpt_code','?')} | Date: {c.get('service_date','?')} | ICD: {c.get('icd_code','?')}")
    return "\n".join(lines)


def _format_measures_for_prompt(measures: List[Dict]) -> str:
    """Format applicable measures cleanly for the LLM prompt."""
    if not measures:
        return "  None applicable."
    lines = []
    for m in measures:
        lines.append(
            f"  [{m['measure_id']}] {m['name']}\n"
            f"    Age Range: {m['age_range']} | Lookback: {m['lookback_months']} months\n"
            f"    Required CPT Codes: {m['cpt_codes']}\n"
            f"    Resolution Guide: {m['description']}"
        )
    return "\n".join(lines)


def _format_gaps_for_prompt(gaps: List[Dict]) -> str:
    """Format existing graph gaps cleanly for the LLM prompt."""
    if not gaps:
        return "  None."
    lines = []
    for g in gaps:
        lines.append(
            f"  Gap ID: {g.get('care_gap_id')} | Measure: {g.get('measure_id')} "
            f"({g.get('measure_name')}) | Created: {g.get('created_on')} | Status: {g.get('gap_status')}"
        )
    return "\n".join(lines)


# ── Agent System ──────────────────────────────────────────────────────────────

class CareGapAgentSystem:
    def __init__(self):
        from autogen_core.models import ModelInfo
        self.model_client = AzureOpenAIChatCompletionClient(
            azure_deployment=settings.openai_model,
            azure_endpoint=settings.endpoint,
            api_key=settings.openai_api_key,
            api_version=settings.azure_openai_api_version,
            model=settings.openai_model,
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
        self.validation_agent = AssistantAgent(
            name="care_gap_validator",
            system_message="""You are a Care Gap Validation Agent for a health insurance company.

You receive:
- A member's demographic profile
- Their full claims history (CPT code, service date, ICD diagnosis code)
- The applicable Quality Measures (golden reference) with required CPT codes and lookback periods
- A system-computed list of open and compliant measures

Your job:
1. For each applicable measure, confirm whether the member is COMPLIANT or NON-COMPLIANT
2. For NON-COMPLIANT measures, explain exactly WHY the gap is open:
   - Was there no claim at all?
   - Was there a claim but with the wrong CPT code?
   - Was there a claim but it fell outside the lookback window?
3. State which specific CPT codes would close each open gap
4. Note the last relevant claim date if one exists (even if outside lookback)

Output format per measure:
---
Measure: [MeasureID] — [Name]
Status: COMPLIANT / NON-COMPLIANT
Reason: [specific explanation]
CPT Codes That Would Close This Gap: [list]
Last Relevant Claim: [date or 'No qualifying claim found']
---""",
            model_client=self.model_client,
        )

        self.outreach_advisor = AssistantAgent(
            name="outreach_advisor",
            system_message="""You are a Care Management Outreach Advisor for a health insurance company.

You receive a member's open care gaps with their golden reference resolution guides.

Your job:
1. Prioritise the open gaps by urgency (shorter lookback = more urgent; e.g. HbA1c at 12 months > BCS at 24 months)
2. For each open gap, provide:
   - The exact procedure the member needs (procedure name + CPT code from the resolution guide)
   - The type of In-Network provider to refer to (e.g. Radiology for BCS, OB/GYN for CCS, Lab/Endocrinology for HbA1c, Gastroenterology for COL)
   - Recommended outreach channel: Phone for urgent gaps (HbA1c, BCS), SMS for scheduling reminders (COL, CCS)
3. Write a short care manager talking points script for the top priority gap

Always reference the resolution guide text directly in your recommendations.
Be specific — name the CPT code, the provider type, and the exact action needed.""",
            model_client=self.model_client,
        )

        self.benefit_checker = AssistantAgent(
            name="benefit_checker",
            system_message="""You are a Benefits Coverage Checker for a health insurance company.

You receive a member's benefit plan details and their open care gaps.

Your job — for each open gap:
1. Confirm whether the required service is covered under the member's plan (check PreventiveServicesCovered field)
2. State the member's out-of-pocket cost: Copay and whether Deductible applies
3. Check EligibilityRules for any restrictions (age, gender, diagnosis requirements)
4. If a service is NOT covered, flag it clearly — this changes the outreach approach

Known plan PL-001 coverage:
  Covered services: Mammography, Colonoscopy, Cervical Cytology, HPV testing, HbA1c, Adult Immunizations
  Copay: $0 for all preventive services
  Deductible: $500 (does NOT apply to preventive services)
  Eligibility: Active enrollment + Age/Gender/Diagnosis per measure

Be direct and concise. State covered/not covered, cost to member, and any restrictions.""",
            model_client=self.model_client,
        )

    def _run_team(self, task: str) -> Dict[str, str]:
        import asyncio

        async def _run():
            team = SelectorGroupChat(
                participants=[
                    self.validation_agent,
                    self.outreach_advisor,
                    self.benefit_checker,
                ],
                model_client=self.model_client,
                # 10 = task(1) + validator(1) + outreach(1) + benefit(1) + possible follow-ups(6)
                termination_condition=MaxMessageTermination(max_messages=10),
                selector_prompt="""You are coordinating a care gap management team. Select the next agent:

- care_gap_validator  : Use first. Validates member compliance against each quality measure.
                        Explains why each gap is open (wrong CPT, expired lookback, no claim).
- outreach_advisor    : Use after validation. Generates prioritised outreach plan and
                        care manager talking points for each open gap.
- benefit_checker     : Use after outreach plan. Confirms plan coverage and member cost
                        for each required service.

Rules:
- Always start with care_gap_validator
- Do not repeat an agent unless new information in the conversation requires it
- Stop after all 3 agents have responded""",
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

    def validate_and_suggest(self, member_id: str) -> Dict[str, Any]:
        """
        Main entry point.
        1. Fetch member profile + claims from Neo4j
        2. Filter applicable QualityMeasure golden reference nodes by age/gender/diagnosis
        3. Check each measure's CPT codes against claims within lookback window
        4. Auto-create CareGap nodes in Neo4j for newly detected gaps
        5. Run agent team → validation report + outreach plan + benefit check
        """
        profile = get_member_profile(member_id)
        if not profile:
            return {"error": f"Member {member_id} not found in knowledge graph"}

        age = _parse_age(profile.get("age_str", "0"))
        gender = str(profile.get("gender", ""))

        # Fetch claims — icd_code needed for HbA1c diabetes eligibility check
        claims = get_member_claims_cpt_codes(member_id)
        icd_codes = [c.get("icd_code", "") for c in claims]

        # Filter golden reference measures applicable to this member
        all_measures = get_applicable_measures(age, gender)
        applicable = [m for m in all_measures if _measure_applies(m, age, gender, icd_codes)]

        # System-level CPT + lookback validation (no LLM involved here)
        detected_gaps = []
        satisfied_measures = []
        for measure in applicable:
            satisfied = _gap_already_satisfied(
                claims,
                measure.get("cpt_codes", ""),
                int(measure.get("lookback_months") or 12),
            )
            if not satisfied:
                detected_gaps.append(measure)
                # Auto-create CareGap node in Neo4j so it persists in the graph
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

        # Fetch existing open gaps from graph (includes manually loaded ones from Excel)
        existing_gaps = get_member_open_gaps(member_id)

        # Build clean, readable prompt for agents
        task = f"""
=== CARE GAP ANALYSIS REQUEST ===

MEMBER PROFILE:
  Member ID  : {member_id}
  Name       : {profile.get('name')}
  Age        : {profile.get('age_str')}
  Gender     : {gender}
  DOB        : {profile.get('dob')}
  Plan       : {profile.get('plan_id')} | Copay: ${profile.get('copay')} | Deductible: $500
  Preventive Services Covered: {profile.get('preventive_covered')}
  Eligibility Rules: {profile.get('eligibility_rules')}
  PCP        : {profile.get('pcp_name')} ({profile.get('pcp_specialty')}) — {profile.get('pcp_network_status')}

APPLICABLE QUALITY MEASURES (GOLDEN REFERENCE — {len(applicable)} measures apply):
{_format_measures_for_prompt(applicable)}

MEMBER'S CLAIMS HISTORY:
{_format_claims_for_prompt(claims)}

SYSTEM-VALIDATED GAP STATUS (CPT code + lookback window check):
  Open Gaps    : {[m['measure_id'] for m in detected_gaps] or 'None'}
  Compliant    : {satisfied_measures or 'None'}

EXISTING OPEN GAPS IN KNOWLEDGE GRAPH:
{_format_gaps_for_prompt(existing_gaps)}

=== INSTRUCTIONS ===
1. care_gap_validator: Validate compliance for each applicable measure. Explain exactly why each gap is open.
2. outreach_advisor: Generate a prioritised outreach plan with care manager talking points.
3. benefit_checker: Confirm coverage and member cost for each required service under plan {profile.get('plan_id')}.
"""
        responses = self._run_team(task)

        return {
            "member_id": member_id,
            "member_name": profile.get("name"),
            "age": profile.get("age_str"),
            "gender": gender,
            "applicable_measures": [m["measure_id"] for m in applicable],
            "compliant_measures": satisfied_measures,
            "open_gaps_detected": [m["measure_id"] for m in detected_gaps],
            "existing_graph_gaps": existing_gaps,
            "agent_responses": responses,
        }
