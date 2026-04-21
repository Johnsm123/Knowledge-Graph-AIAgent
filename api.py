from flask import Flask, request, jsonify
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os
from datetime import date

load_dotenv()

app = Flask(__name__)

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
)
DB = os.getenv("NEO4J_DATABASE")

BCS_COMPLIANCE_CPT = {"77061", "77062", "77063", "77065", "77066", "77067"}
BCS_EXCLUSION_CPT  = {"19180","19200","19220","19240","19303","19304","19305","19306","19307","19318"}
BCS_EXCLUSION_ICD  = {"Z90.13","Z90.12","Z90.11","F64.1","F64.2","F64.8","F64.9","Z87.890"}
BCS_EXCLUSION_PCS  = {"0HTV0ZZ","0HTU0ZZ","0HTT0ZZ"}

LOOKBACK_START = date(2024, 10, 1)
MEASUREMENT_END = date(2026, 12, 31)


@app.route("/care-gap/bcs", methods=["POST"])
def check_care_gap():
    data = request.get_json()
    member_id = data.get("member_id")

    if not member_id:
        return jsonify({"error": "member_id is required"}), 400

    with driver.session(database=DB) as session:
        # Fetch member
        member = session.run("""
            MATCH (m:Member {member_id: $mid})
            RETURN m.member_id AS member_id, m.gender AS gender,
                   m.age_years AS age, m.enrollment_start AS enrollment_start,
                   m.enrollment_end AS enrollment_end
        """, mid=member_id).single()

        if not member:
            return jsonify({"error": f"Member '{member_id}' not found"}), 404

        member = dict(member)
        gender = (member.get("gender") or "").upper()
        age = member.get("age") or 0

        # Gender check
        if gender != "F":
            return jsonify(build_response(member, "NOT_ELIGIBLE", "Gender not Female"))

        # Age check
        if not (42 <= age <= 74):
            return jsonify(build_response(member, "NOT_ELIGIBLE", f"Age {age} outside 42-74"))

        # Fetch claims
        claims = session.run("""
            MATCH (m:Member {member_id: $mid})-[:HAS_CLAIM]->(c:Claim)
            RETURN c.cpt_code AS cpt_code, c.icd_code AS icd_code,
                   c.service_date AS service_date, c.status AS status
        """, mid=member_id)
        claims = [dict(c) for c in claims]

        # Exclusion check
        exclusion_reason = None
        for c in claims:
            cpt = (c.get("cpt_code") or "").strip()
            icd = (c.get("icd_code") or "").strip()
            if cpt in BCS_EXCLUSION_CPT:
                exclusion_reason = "gender_affirming_chest_surgery" if cpt == "19318" else "unilateral_mastectomy_both_sides"
                break
            if icd in BCS_EXCLUSION_ICD:
                exclusion_reason = (
                    "bilateral_mastectomy" if icd == "Z90.13"
                    else "unilateral_mastectomy_both_sides" if icd in {"Z90.12", "Z90.11"}
                    else "gender_affirming_chest_surgery"
                )
                break
            if icd in BCS_EXCLUSION_PCS:
                exclusion_reason = "bilateral_mastectomy"
                break

        if exclusion_reason:
            return jsonify(build_response(member, "EXCLUDED", exclusion_reason, claims=claims))

        # Mammogram compliance check
        has_mammogram = False
        compliant_claim = None
        for c in claims:
            cpt = (c.get("cpt_code") or "").strip()
            svc = c.get("service_date")
            if cpt in BCS_COMPLIANCE_CPT and svc:
                try:
                    svc_date = date.fromisoformat(str(svc)[:10])
                    if LOOKBACK_START <= svc_date <= MEASUREMENT_END:
                        has_mammogram = True
                        compliant_claim = {"cpt_code": cpt, "service_date": str(svc_date)}
                        break
                except ValueError:
                    pass

        status = "COMPLIANT" if has_mammogram else "OPEN_GAP"
        open_gap_reason = None if has_mammogram else (
            f"No mammography CPT (77061-77067) found between "
            f"{LOOKBACK_START} and {MEASUREMENT_END}"
        )
        return jsonify(build_response(member, status, reason=open_gap_reason,
                                      compliant_claim=compliant_claim, claims=claims))


def build_response(member, status, reason=None, compliant_claim=None, claims=None):
    mammogram_cpts = [
        {"cpt_code": c.get("cpt_code"), "service_date": str(c.get("service_date", ""))}
        for c in (claims or [])
        if (c.get("cpt_code") or "").strip() in BCS_COMPLIANCE_CPT
    ]
    return {
        "member_id": member.get("member_id"),
        "gender": member.get("gender"),
        "age": member.get("age"),
        "measure": "BCS-E",
        "care_gap_status": status,
        "reason": reason,
        "compliant_mammogram": compliant_claim,
        "mammogram_claims_found": mammogram_cpts,
        "recommendation": (
            "Schedule a mammogram screening — no qualifying mammogram found in the lookback window."
            if status == "OPEN_GAP" else None
        ),
        "lookback_window": (
            {"start": str(LOOKBACK_START), "end": str(MEASUREMENT_END)}
            if status == "OPEN_GAP" else None
        ),
        "total_claims": len(claims) if claims else 0
    }


if __name__ == "__main__":
    app.run(debug=True, port=5000)
