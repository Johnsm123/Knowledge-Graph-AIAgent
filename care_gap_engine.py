"""
Multi-Measure Care Gap Engine
Reads all measure configs from measures/*_config.json and evaluates
every member in Neo4j against every measure.

Usage:
    python care_gap_engine.py
"""

import os
import json
import glob
from datetime import date
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DB       = os.getenv("NEO4J_DATABASE")

MEASUREMENT_YEAR = 2026
MEASURES_DIR     = os.path.join(os.path.dirname(__file__), "measures")


# ── Load all measure configs ──────────────────────────────────────────────────
def load_all_configs() -> list:
    configs = []
    for path in glob.glob(os.path.join(MEASURES_DIR, "*_config.json")):
        with open(path, encoding="utf-8") as f:
            configs.append(json.load(f))
    return configs


# ── Build flat code sets from config ─────────────────────────────────────────
def build_code_sets(config: dict) -> tuple:
    compliance = set()
    for codes in config.get("compliance_codes", {}).values():
        for c in codes:
            compliance.add(str(c).strip())

    exclusion_map = {}  # code -> exclusion_reason
    for reason, code_map in config.get("exclusion_codes", {}).items():
        for codes in code_map.values():
            if isinstance(codes, list):
                for c in codes:
                    exclusion_map[str(c).strip()] = reason

    return compliance, exclusion_map


# ── Lookback window for a measure ─────────────────────────────────────────────
def get_lookback(config: dict) -> tuple:
    lookback_years  = config.get("lookback_years", 1) or 1
    start_month     = config.get("lookback_start_month", 1) or 1
    start_day       = config.get("lookback_start_day", 1) or 1
    try:
        start = date(MEASUREMENT_YEAR - lookback_years, start_month, start_day)
    except ValueError:
        start = date(MEASUREMENT_YEAR - lookback_years, 1, 1)
    end = date(MEASUREMENT_YEAR, 12, 31)
    return start, end


# ── Age band from config ───────────────────────────────────────────────────────
def get_age_band(age: int, config: dict) -> str | None:
    for band in config.get("age_bands", []):
        if band["min"] <= age <= band["max"]:
            return band["code"]
    return None


# ── Evaluate one member against one measure ───────────────────────────────────
def evaluate_member(member: dict, claims: list, config: dict) -> dict:
    mid             = member["member_id"]
    age             = member.get("age_years") or 0
    gender          = (member.get("gender") or "").upper()
    measure_id      = config["measure_id"]
    eligible_gender = (config.get("eligible_gender") or "Any").strip()
    age_min         = config.get("eligible_age_min", 0)
    age_max         = config.get("eligible_age_max", 999)

    # Gender check
    if eligible_gender.lower() not in ("any", "") and gender != "F":
        return {"status": "NOT_ELIGIBLE", "reason": "Gender not eligible", "age_band": None}

    # Age check
    if not (age_min <= age <= age_max):
        return {"status": "NOT_ELIGIBLE", "reason": f"Age {age} outside {age_min}-{age_max}", "age_band": None}

    age_band = get_age_band(age, config)
    compliance_codes, exclusion_map = build_code_sets(config)
    lookback_start, lookback_end    = get_lookback(config)

    exclusion_reason  = None
    compliance_found  = False

    for c in claims:
        cpt = (c.get("cpt_code") or "").strip()
        icd = (c.get("icd_code") or "").strip()
        svc = c.get("service_date")

        # Exclusion check
        if not exclusion_reason:
            if cpt in exclusion_map:
                exclusion_reason = exclusion_map[cpt]
            elif icd in exclusion_map:
                exclusion_reason = exclusion_map[icd]

        # Compliance check within lookback window
        if not compliance_found and cpt in compliance_codes and svc:
            try:
                svc_date = date.fromisoformat(str(svc)[:10])
                if lookback_start <= svc_date <= lookback_end:
                    compliance_found = True
            except ValueError:
                pass

    if exclusion_reason:
        status = "EXCLUDED"
    elif compliance_found:
        status = "COMPLIANT"
    else:
        status = "OPEN_GAP"

    return {"status": status, "reason": exclusion_reason, "age_band": age_band, "has_compliance": compliance_found}


# ── Write CareGap node + relationships ────────────────────────────────────────
def write_care_gap(session, member_id: str, measure_id: str, result: dict):
    gap_id   = f"GAP-{measure_id}-{member_id}"
    age_band = result.get("age_band")
    status   = result["status"]

    session.run("""
        MERGE (g:CareGap {gap_id: $gap_id})
        SET g.member_id        = $mid,
            g.measure          = $measure,
            g.status           = $status,
            g.exclusion_reason = $excl,
            g.has_compliance   = $has_compliance,
            g.created_on       = $today
        WITH g
        MATCH (m:Member {member_id: $mid})
        MERGE (m)-[:HAS_CARE_GAP]->(g)
        WITH g
        MATCH (meas:Measure {measure_id: $measure})
        MERGE (g)-[:FOR_MEASURE]->(meas)
    """, gap_id=gap_id, mid=member_id, measure=measure_id,
         status=status, excl=result.get("reason"),
         has_compliance=result.get("has_compliance", False),
         today=str(date.today()))

    # Match to persona
    if age_band and status != "NOT_ELIGIBLE":
        gc_code = "GC1" if result.get("gender_eligible") else None
        session.run("""
            MATCH (mem:Member {member_id: $mid})
            MATCH (p:Persona {
                measure: $measure,
                age_band_code: $ab,
                care_gap_status: $status
            })
            WITH mem, p LIMIT 1
            MERGE (mem)-[:MATCHES_PERSONA]->(p)
        """, mid=member_id, measure=measure_id, ab=age_band, status=status)


# ── Main engine ───────────────────────────────────────────────────────────────
def run_engine(driver):
    configs = load_all_configs()
    print(f"Loaded {len(configs)} measure configs: {[c['measure_id'] for c in configs]}\n")

    with driver.session(database=DB) as session:
        members = session.run("""
            MATCH (m:Member)
            RETURN m.member_id AS member_id, m.gender AS gender, m.age_years AS age_years
        """).data()

        # Build member → claims lookup once
        all_claims = session.run("""
            MATCH (m:Member)-[:HAS_CLAIM]->(c:Claim)
            RETURN m.member_id AS member_id, c.cpt_code AS cpt_code,
                   c.icd_code AS icd_code, c.service_date AS service_date
        """).data()

        claims_by_member = {}
        for c in all_claims:
            claims_by_member.setdefault(c["member_id"], []).append(c)

        overall_summary = {}

        for config in configs:
            measure_id = config["measure_id"]
            summary    = {"OPEN_GAP": 0, "COMPLIANT": 0, "EXCLUDED": 0, "NOT_ELIGIBLE": 0}

            for member in members:
                mid    = member["member_id"]
                claims = claims_by_member.get(mid, [])
                result = evaluate_member(member, claims, config)
                result["gender_eligible"] = (member.get("gender") or "").upper() == "F"

                if result["status"] != "NOT_ELIGIBLE":
                    write_care_gap(session, mid, measure_id, result)

                summary[result["status"]] = summary.get(result["status"], 0) + 1

            overall_summary[measure_id] = summary
            print(f"{measure_id:<10} | OPEN_GAP: {summary['OPEN_GAP']:<4} COMPLIANT: {summary['COMPLIANT']:<4} "
                  f"EXCLUDED: {summary['EXCLUDED']:<4} NOT_ELIGIBLE: {summary['NOT_ELIGIBLE']}")

        return overall_summary


def main():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        driver.verify_connectivity()
        print("Neo4j connected.\n")
        print(f"{'Measure':<10} | {'OPEN_GAP':<12} {'COMPLIANT':<12} {'EXCLUDED':<12} {'NOT_ELIGIBLE'}")
        print("-" * 65)
        run_engine(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
