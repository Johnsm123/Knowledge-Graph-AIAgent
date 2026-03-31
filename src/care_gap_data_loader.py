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
    merge_quality_measure, merge_benefit_plan, merge_provider,
    merge_member, merge_enrollment, merge_claim,
    merge_care_gap, merge_outreach,
)

logger = logging.getLogger(__name__)
EXCEL_PATH = "src/Scenario 2_care_gap_multi_measure_dataset.xlsx"

# ── Golden Reference — hardcoded for all 4 HEDIS measures ─────────────────────
# Excel sheet has messy merged cells; these are the authoritative values.
GOLDEN_REFERENCE = [
    {
        "measure_id": "BCS",
        "name": "Breast Cancer Screening",
        "age_range": "42-74 Female",
        "lookback_months": 24,
        "proactive_lookback_months": 18,
        "cpt_codes": "77062,77061,77066,77065,77063,77067,G0202",
        "description": (
            "Breast Cancer Screening (BCS) — Annual bilateral screening mammogram for women aged 42-74. "
            "To close this gap, the member needs a screening mammogram. "
            "Primary code: CPT 77067 (bilateral mammogram, 2-views + CAD). "
            "If 3D tomosynthesis is added: bill CPT 77067 + 77063 together. "
            "Medicare legacy code: G0202. "
            "Refer to an In-Network Radiology or Imaging Center. "
            "Typical workflow: Schedule routine annual mammogram → provider obtains 2 X-ray views per breast "
            "→ CAD analysis → if 3D imaging added, add CPT 77063. "
            "Outreach: Call member, confirm last mammogram date, schedule with radiology if overdue."
        ),
    },
    {
        "measure_id": "COL",
        "name": "Colorectal Cancer Screening",
        "age_range": "45-75",
        "lookback_months": 120,
        "proactive_lookback_months": 96,
        "cpt_codes": (
            "44388,44389,44390,44391,44392,44394,44401,44402,44403,44404,44405,44406,44407,44408,"
            "45378,45379,45380,45381,45382,45384,45385,45386,45388,45389,45390,45391,45392,45393,45398,"
            "G0105,G0121,FOBT,FIT"
        ),
        "description": (
            "Colorectal Cancer Screening (COL) — Screening for members aged 45-75 (any gender). "
            "Lookback window is 10 years (120 months) for colonoscopy. "
            "To close this gap, the member needs one of: "
            "Colonoscopy (CPT 45378-45398 series) — valid for 10 years; "
            "Flexible sigmoidoscopy (CPT 44388-44408 series) — valid for 5 years; "
            "FIT/FOBT stool test (HCPCS G0105, G0121) — valid for 1 year. "
            "Refer to In-Network Gastroenterology or General Surgery. "
            "Outreach: Ask member preference (colonoscopy vs stool test), "
            "schedule with gastroenterologist or order lab kit for home stool test."
        ),
    },
    {
        "measure_id": "CCS",
        "name": "Cervical Cancer Screening",
        "age_range": "21-64 Female",
        "lookback_months": 36,
        "proactive_lookback_months": 30,
        "cpt_codes": "88141,88142,88143,88147,88148,88150,88152,88153,88164,88165,88166,88167,88174,88175",
        "description": (
            "Cervical Cancer Screening (CCS) — Pap smear / HPV co-test for women aged 21-64. "
            "Lookback window is 36 months (3 years). "
            "To close this gap, the member needs a cervical cytology (Pap smear): "
            "CPT 88141-88143, 88147-88148, 88150, 88152-88153, 88164-88167 (cytology interpretation); "
            "or HPV co-test: CPT 88174-88175. "
            "Refer to In-Network OB/GYN or Women's Health clinic. "
            "Outreach: Confirm last Pap smear date, schedule with OB/GYN if overdue. "
            "For members aged 30-64, HPV co-test (88174/88175) extends interval to 5 years if negative."
        ),
    },
    {
        "measure_id": "CDC-HbA1c",
        "name": "HbA1c Testing (Diabetes Care)",
        "age_range": "18-75",
        "lookback_months": 12,
        "proactive_lookback_months": 9,
        "cpt_codes": "83036,83037",
        "description": (
            "HbA1c Testing — CDC Diabetes Care measure for members aged 18-75 with a Diabetes diagnosis (ICD: E11.x). "
            "Lookback window is 12 months (annual test required). "
            "To close this gap, the member needs an HbA1c lab test: "
            "CPT 83036 (HbA1c with interpretation) or CPT 83037 (HbA1c point-of-care). "
            "Refer to In-Network Laboratory or Endocrinology clinic. "
            "Outreach: Confirm member has diabetes diagnosis, remind them annual HbA1c is required, "
            "order lab requisition or schedule with endocrinologist. "
            "Goal: HbA1c < 8% for good control; flag if result > 9% for urgent follow-up."
        ),
    },
]


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
    """Load golden reference from GOLDEN_REFERENCE — not from Excel cells (messy merged cells)."""
    for m in GOLDEN_REFERENCE:
        merge_quality_measure(
            measure_id=m["measure_id"],
            name=m["name"],
            age_range=m["age_range"],
            lookback_months=m["lookback_months"],
            proactive_lookback_months=m["proactive_lookback_months"],
            cpt_codes=m["cpt_codes"],
            description=m["description"],
        )
    logger.info(f"Loaded {len(GOLDEN_REFERENCE)} QualityMeasure golden reference nodes (BCS, COL, CCS, CDC-HbA1c)")


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


def load_care_gaps():
    df = _read("CareGaps_Dashboard")
    for _, r in df.iterrows():
        # FIX: "CareManagerID" column in this sheet actually stores "Open"/"Closed" status
        gap_status = str(r.get("CareManagerID", "Open")).strip()
        is_open = gap_status.lower() == "open"
        closed_on = _parse_date(r.get("ClosedOn", "")) if not is_open else ""
        merge_care_gap(
            care_gap_id=str(r["CareGapID"]),
            member_id=str(r["MemberID"]),
            measure_id=str(r["MeasureID"]),
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
