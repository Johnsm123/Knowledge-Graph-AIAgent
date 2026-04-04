"""
Reads all 8 sheets from the Excel file and loads them into Neo4j.
Uses MERGE throughout — safe to re-run when new data is added.

Load order matters:
  1. Static/reference nodes first  (QualityMeasure, BenefitPlan, Provider)
  2. Member nodes
  3. Transactional/edge data       (Enrollment, Claims, CareGaps, Outreach)
"""
import pandas as pd
from datetime import datetime
import logging
from src.care_gap_neo4j import (
    setup_constraints,
    merge_quality_measure_comprehensive, merge_benefit_plan, merge_provider,
    merge_member, merge_enrollment, merge_claim,
    merge_care_gap, merge_outreach,
)
from src.hedis_golden_reference import get_all_measures

logger = logging.getLogger(__name__)
EXCEL_PATH = "src/Scenario 2_care_gap_multi_measure_dataset.xlsx"


def _read(sheet: str) -> pd.DataFrame:
    df = pd.read_excel(EXCEL_PATH, sheet_name=sheet)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df


def _parse_date(val) -> str:
    """
    Normalise all date formats to YYYY-MM-DD string.
    Handles: pandas Timestamp, DD-MM-YYYY, M/D/YYYY, YYYY-MM-DD, D/M/YYYY.
    """
    import pandas as pd
    if isinstance(val, (pd.Timestamp,)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    # strip timestamp suffix if present e.g. '1991-07-01 00:00:00'
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def load_quality_measures():
    """Load comprehensive HEDIS golden reference from hedis_golden_reference.py"""
    measures = get_all_measures()
    for measure_id, measure_data in measures.items():
        merge_quality_measure_comprehensive(measure_data)
    logger.info(f"Loaded {len(measures)} comprehensive QualityMeasure nodes with exclusions, code sets, and guidelines")


def load_benefit_plans():
    df = _read("BenefitPlan")
    for _, r in df.iterrows():
        merge_benefit_plan(
            plan_id=str(r["PlanID"]),
            preventive_covered=str(r.get("PreventiveServicesCovered", "")),
            copay=r.get("Copay", 0),
            deductible=r.get("Deductible", 0),
            eligibility_rules=str(r.get("EligibilityRules", "")),
        )
    logger.info(f"Loaded {len(df)} BenefitPlan nodes")


def load_providers():
    df = _read("Providers")
    for _, r in df.iterrows():
        merge_provider(
            provider_id=str(r["ProviderID"]),
            name=str(r["Name"]),
            specialty=str(r.get("Specialty", "")),
            facility_type=str(r.get("FacilityType", "")),
            network_status=str(r.get("NetworkStatus", "")),
            location=str(r.get("Location", "")),
        )
    logger.info(f"Loaded {len(df)} Provider nodes")


def load_members():
    df = _read("Members")
    for _, r in df.iterrows():
        merge_member(
            member_id=str(r["MemberID"]),
            name=str(r["Name"]),
            dob=_parse_date(r.get("DOB", "")),
            gender=str(r.get("Gender", "")),
            pcp_id=str(r.get("PCPID", "")),
            zip_code=str(r.get("ZIP", "")),
            enrollment_start=_parse_date(r.get("EnrollmentStart", "")),
            enrollment_end=_parse_date(r.get("EnrollmentEnd", "")),
            age_str=str(r.get("Member Age", "")),
        )
    logger.info(f"Loaded {len(df)} Member nodes")


def load_enrollments():
    df = _read("Enrolment Eligibility")
    for _, r in df.iterrows():
        merge_enrollment(
            member_id=str(r["MemberID"]),
            plan_id=str(r["PlanID"]),
            pcp_id=str(r["PCPID"]),
            effective_from=_parse_date(r.get("EffectiveFrom", "")),
            effective_to=_parse_date(r.get("EffectiveTo", "")),
        )
    logger.info(f"Loaded {len(df)} ENROLLED_IN + ASSIGNED_TO relationships")


def load_claims():
    df = _read("Claims")
    df = df.dropna(subset=["ClaimID"])
    for _, r in df.iterrows():
        merge_claim(
            claim_id=str(r["ClaimID"]),
            member_id=str(r["MemberID"]),
            provider_id=str(r["ProviderID"]),
            cpt_code=str(r.get("CPTCode", "")).strip(),    # plain number e.g. "83036"
            icd_code=str(r.get("ICDCode", "")).strip(),
            service_date=_parse_date(r.get("ServiceDate", "")),
            status=str(r.get("Status", "")),
        )
    logger.info(f"Loaded {len(df)} Claim nodes")


# Map Excel legacy measure IDs → golden reference measure IDs
_MEASURE_ID_MAP = {
    "CDC-HbA1c": "GSD",   # Excel uses CDC-HbA1c; golden reference uses GSD
    "CDC-EE":    "EED",
    "CDC-KED":   "KED",
    "CDC-BP":    "BPD",
}


def load_care_gaps():
    df = _read("CareGaps_Dashboard")
    for _, r in df.iterrows():
        # FIX: "CareManagerID" column in this sheet actually stores "Open"/"Closed" status
        gap_status = str(r.get("CareManagerID", "Open")).strip()
        is_open = gap_status.lower() == "open"
        closed_on = _parse_date(r.get("ClosedOn", "")) if not is_open else ""
        raw_measure_id = str(r["MeasureID"]).strip()
        measure_id = _MEASURE_ID_MAP.get(raw_measure_id, raw_measure_id)
        merge_care_gap(
            care_gap_id=str(r["CareGapID"]),
            member_id=str(r["MemberID"]),
            measure_id=measure_id,
            gap_status=gap_status,
            is_open=is_open,
            created_on=_parse_date(r.get("CreatedOn", "")),
            closed_on=closed_on,
        )
    logger.info(f"Loaded {len(df)} CareGap nodes")


def load_outreach():
    df = _read("CareMngnt_Outreach_Dashboard")
    for _, r in df.iterrows():
        merge_outreach(
            outreach_id=str(r["OutreachID"]),
            care_gap_id=str(r["CareGapID"]),
            member_id=str(r["MemberID"]),
            care_manager_id=str(r.get("CareManagerID", "")),
            channel=str(r.get("Channel", "")),
            date=_parse_date(r.get("Date", "")),
            status=str(r.get("Status", "")),
        )
    logger.info(f"Loaded {len(df)} Outreach nodes")


def load_all():
    """
    Full load pipeline. Safe to re-run — MERGE handles existing data.
    New rows are inserted; existing rows are updated in place.
    """
    logger.info("Setting up constraints...")
    setup_constraints()

    logger.info("Loading static/golden reference nodes...")
    load_quality_measures()   # golden reference — load first
    load_benefit_plans()
    load_providers()

    logger.info("Loading member nodes...")
    load_members()

    logger.info("Loading transactional/edge data...")
    load_enrollments()        # needs Member + BenefitPlan + Provider
    load_claims()             # needs Member + Provider
    load_care_gaps()          # needs Member + QualityMeasure
    load_outreach()           # needs CareGap + Member

    logger.info("Care gap knowledge graph load complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_all()
