"""
Neo4j MERGE operations for Care Gap schema.
All writes use MERGE to safely handle re-loads and duplicate data.
"""
from src.neo4j_connection import get_knowledge_graph


def setup_constraints():
    """Create uniqueness constraints (run once)."""
    kg = get_knowledge_graph()
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Member) REQUIRE m.member_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Provider) REQUIRE p.provider_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (b:BenefitPlan) REQUIRE b.plan_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (q:QualityMeasure) REQUIRE q.measure_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Claim) REQUIRE c.claim_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (g:CareGap) REQUIRE g.care_gap_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (o:Outreach) REQUIRE o.outreach_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:ExclusionCriteria) REQUIRE e.exclusion_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cs:CodeSet) REQUIRE cs.code_set_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cg:ClinicalGuideline) REQUIRE cg.guideline_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (so:ScreeningOption) REQUIRE so.option_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (bp:BestPractices) REQUIRE bp.best_practices_id IS UNIQUE",
    ]
    for c in constraints:
        kg.execute_write(c)


# ── Static / Golden Reference Nodes ──────────────────────────────────────────

def merge_quality_measure_comprehensive(measure_data: dict):
    """
    Load comprehensive HEDIS measure with all attributes.
    measure_data should come from hedis_golden_reference.py
    """
    kg = get_knowledge_graph()
    
    # Create main QualityMeasure node with comprehensive attributes
    kg.execute_write("""
        MERGE (q:QualityMeasure {measure_id: $measure_id})
        SET q.name = $name,
            q.description = $description,
            q.age_range = $age_range,
            q.min_age = $min_age,
            q.max_age = $max_age,
            q.gender_requirement = $gender_requirement,
            q.lookback_months = $lookback_months,
            q.lookback_description = $lookback_description,
            q.numerator_criteria = $numerator_criteria,
            q.denominator_criteria = $denominator_criteria,
            q.continuous_enrollment = $continuous_enrollment,
            q.product_lines = $product_lines,
            q.diagnosis_requirement = $diagnosis_requirement
    """, {
        "measure_id": measure_data["measure_id"],
        "name": measure_data["name"],
        "description": measure_data["description"],
        "age_range": measure_data["age_range"],
        "min_age": measure_data["min_age"],
        "max_age": measure_data["max_age"],
        "gender_requirement": measure_data.get("gender_requirement", "Any"),
        "lookback_months": measure_data.get("lookback_months"),
        "lookback_description": measure_data.get("lookback_description", ""),
        "numerator_criteria": measure_data.get("numerator_criteria", ""),
        "denominator_criteria": measure_data.get("denominator_criteria", ""),
        "continuous_enrollment": measure_data.get("continuous_enrollment", ""),
        "product_lines": measure_data.get("product_lines", []),
        "diagnosis_requirement": measure_data.get("diagnosis_requirement", "")
    })
    
    # Load screening options if present (for COL has 5 options, CCS has 3 options)
    # Each option gets its own CodeSet so per-option lookback gap detection works.
    if "screening_options" in measure_data:
        for option in measure_data["screening_options"]:
            option_id = f"{measure_data['measure_id']}_{option['type']}"
            kg.execute_write("""
                MERGE (so:ScreeningOption {option_id: $option_id})
                SET so.type = $type,
                    so.lookback_months = $lookback_months,
                    so.description = $description,
                    so.age_range = $age_range
                WITH so
                MATCH (q:QualityMeasure {measure_id: $measure_id})
                MERGE (q)-[:HAS_SCREENING_OPTION]->(so)
            """, {
                "option_id": option_id,
                "type": option["type"],
                "lookback_months": option["lookback_months"],
                "description": option["description"],
                "age_range": option.get("age_range", ""),
                "measure_id": measure_data["measure_id"]
            })

            # Store the CPT codes for this specific screening option
            # Relationship: ScreeningOption -[:USES_CODES]-> CodeSet
            cpt_codes = option.get("cpt", [])
            hcpcs_codes = option.get("hcpcs", [])
            if cpt_codes:
                opt_cset_id = f"{option_id}_cpt"
                kg.execute_write("""
                    MERGE (cs:CodeSet {code_set_id: $code_set_id})
                    SET cs.code_type = $code_type,
                        cs.codes = $codes,
                        cs.measure_id = $measure_id
                    WITH cs
                    MATCH (so:ScreeningOption {option_id: $option_id})
                    MERGE (so)-[:USES_CODES]->(cs)
                """, {
                    "code_set_id": opt_cset_id,
                    "code_type": f"{option['type']}_cpt",
                    "codes": cpt_codes,
                    "measure_id": measure_data["measure_id"],
                    "option_id": option_id
                })
            if hcpcs_codes:
                opt_hset_id = f"{option_id}_hcpcs"
                kg.execute_write("""
                    MERGE (cs:CodeSet {code_set_id: $code_set_id})
                    SET cs.code_type = $code_type,
                        cs.codes = $codes,
                        cs.measure_id = $measure_id
                    WITH cs
                    MATCH (so:ScreeningOption {option_id: $option_id})
                    MERGE (so)-[:USES_CODES]->(cs)
                """, {
                    "code_set_id": opt_hset_id,
                    "code_type": f"{option['type']}_hcpcs",
                    "codes": hcpcs_codes,
                    "measure_id": measure_data["measure_id"],
                    "option_id": option_id
                })
    
    # Load code sets
    if "codes" in measure_data:
        for code_type, codes in measure_data["codes"].items():
            if isinstance(codes, list):
                code_set_id = f"{measure_data['measure_id']}_{code_type}"
                kg.execute_write("""
                    MERGE (cs:CodeSet {code_set_id: $code_set_id})
                    SET cs.code_type = $code_type,
                        cs.codes = $codes,
                        cs.measure_id = $measure_id
                    WITH cs
                    MATCH (q:QualityMeasure {measure_id: $measure_id})
                    MERGE (q)-[:REQUIRES_CODES]->(cs)
                """, {
                    "code_set_id": code_set_id,
                    "code_type": code_type,
                    "codes": codes,
                    "measure_id": measure_data["measure_id"]
                })
    
    # Load exclusions
    if "exclusions" in measure_data:
        for exclusion_category, exclusions in measure_data["exclusions"].items():
            for idx, exclusion in enumerate(exclusions):
                exclusion_id = f"{measure_data['measure_id']}_{exclusion['type']}_{exclusion_category}"
                
                # Extract codes from exclusion
                cpt_codes = exclusion.get("cpt", [])
                hcpcs_codes = exclusion.get("hcpcs", [])
                icd10_codes = exclusion.get("icd10", [])
                icd10pcs_codes = exclusion.get("icd10pcs", [])
                modifiers = exclusion.get("modifiers", [])
                
                kg.execute_write("""
                    MERGE (e:ExclusionCriteria {exclusion_id: $exclusion_id})
                    SET e.type = $type,
                        e.description = $description,
                        e.category = $category,
                        e.cpt_codes = $cpt_codes,
                        e.hcpcs_codes = $hcpcs_codes,
                        e.icd10_codes = $icd10_codes,
                        e.icd10pcs_codes = $icd10pcs_codes,
                        e.modifiers = $modifiers,
                        e.criteria = $criteria,
                        e.measure_id = $measure_id
                    WITH e
                    MATCH (q:QualityMeasure {measure_id: $measure_id})
                    MERGE (q)-[:HAS_EXCLUSION {category: $category}]->(e)
                """, {
                    "exclusion_id": exclusion_id,
                    "type": exclusion["type"],
                    "description": exclusion["description"],
                    "category": exclusion_category,
                    "cpt_codes": cpt_codes,
                    "hcpcs_codes": hcpcs_codes,
                    "icd10_codes": icd10_codes,
                    "icd10pcs_codes": icd10pcs_codes,
                    "modifiers": modifiers,
                    "criteria": exclusion.get("criteria", ""),
                    "measure_id": measure_data["measure_id"]
                })
    
    # Load clinical guidelines
    if "clinical_guidelines" in measure_data:
        guidelines = measure_data["clinical_guidelines"]
        guideline_id = f"{measure_data['measure_id']}_clinical_guidelines"
        
        kg.execute_write("""
            MERGE (cg:ClinicalGuideline {guideline_id: $guideline_id})
            SET cg.acceptable = $acceptable,
                cg.not_acceptable = $not_acceptable,
                cg.measure_id = $measure_id
            WITH cg
            MATCH (q:QualityMeasure {measure_id: $measure_id})
            MERGE (q)-[:FOLLOWS_GUIDELINE]->(cg)
        """, {
            "guideline_id": guideline_id,
            "acceptable": guidelines.get("acceptable", []),
            "not_acceptable": guidelines.get("not_acceptable", []),
            "measure_id": measure_data["measure_id"]
        })
    
    # Load best practices
    if "best_practices" in measure_data:
        best_practices_id = f"{measure_data['measure_id']}_best_practices"
        kg.execute_write("""
            MERGE (bp:BestPractices {best_practices_id: $best_practices_id})
            SET bp.practices = $practices,
                bp.measure_id = $measure_id
            WITH bp
            MATCH (q:QualityMeasure {measure_id: $measure_id})
            MERGE (q)-[:HAS_BEST_PRACTICES]->(bp)
        """, {
            "best_practices_id": best_practices_id,
            "practices": measure_data["best_practices"],
            "measure_id": measure_data["measure_id"]
        })


def merge_quality_measure(measure_id, name, age_range, lookback_months,
                           proactive_lookback_months, cpt_codes, description):
    """Legacy function - kept for backward compatibility"""
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (q:QualityMeasure {measure_id: $measure_id})
        SET q.name = $name,
            q.age_range = $age_range,
            q.lookback_months = $lookback_months,
            q.proactive_lookback_months = $proactive_lookback_months,
            q.cpt_codes = $cpt_codes,
            q.description = $description
    """, {"measure_id": measure_id, "name": name, "age_range": age_range,
          "lookback_months": lookback_months,
          "proactive_lookback_months": proactive_lookback_months,
          "cpt_codes": cpt_codes, "description": description})


def merge_benefit_plan(plan_id, preventive_covered, copay, deductible, eligibility_rules):
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (b:BenefitPlan {plan_id: $plan_id})
        SET b.preventive_covered = $preventive_covered,
            b.copay = $copay,
            b.deductible = $deductible,
            b.eligibility_rules = $eligibility_rules
    """, {"plan_id": plan_id, "preventive_covered": preventive_covered,
          "copay": copay, "deductible": deductible,
          "eligibility_rules": eligibility_rules})


def merge_provider(provider_id, name, specialty, facility_type, network_status, location):
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (p:Provider {provider_id: $provider_id})
        SET p.name = $name,
            p.specialty = $specialty,
            p.facility_type = $facility_type,
            p.network_status = $network_status,
            p.location = $location
    """, {"provider_id": provider_id, "name": name, "specialty": specialty,
          "facility_type": facility_type, "network_status": network_status,
          "location": location})


# ── Dynamic / Transactional Nodes ─────────────────────────────────────────────

def merge_member(member_id, name, dob, gender, pcp_id, zip_code,
                 enrollment_start, enrollment_end, age_str):
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (m:Member {member_id: $member_id})
        SET m.name = $name,
            m.dob = $dob,
            m.gender = $gender,
            m.pcp_id = $pcp_id,
            m.zip = $zip_code,
            m.enrollment_start = $enrollment_start,
            m.enrollment_end = $enrollment_end,
            m.age_str = $age_str
    """, {"member_id": member_id, "name": name, "dob": str(dob), "gender": gender,
          "pcp_id": pcp_id, "zip_code": str(zip_code),
          "enrollment_start": str(enrollment_start),
          "enrollment_end": str(enrollment_end), "age_str": age_str})


def merge_enrollment(member_id, plan_id, pcp_id, effective_from, effective_to):
    kg = get_knowledge_graph()
    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (b:BenefitPlan {plan_id: $plan_id})
        MERGE (m)-[r:ENROLLED_IN {plan_id: $plan_id}]->(b)
        SET r.effective_from = $effective_from,
            r.effective_to = $effective_to,
            r.pcp_id = $pcp_id
    """, {"member_id": member_id, "plan_id": plan_id, "pcp_id": pcp_id,
          "effective_from": str(effective_from), "effective_to": str(effective_to)})

    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (p:Provider {provider_id: $pcp_id})
        MERGE (m)-[:ASSIGNED_TO]->(p)
    """, {"member_id": member_id, "pcp_id": pcp_id})


def merge_claim(claim_id, member_id, provider_id, cpt_code, icd_code,
                service_date, status):
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (c:Claim {claim_id: $claim_id})
        SET c.cpt_code = $cpt_code,
            c.icd_code = $icd_code,
            c.service_date = $service_date,
            c.status = $status
    """, {"claim_id": claim_id, "cpt_code": cpt_code, "icd_code": icd_code,
          "service_date": service_date, "status": status})

    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (c:Claim {claim_id: $claim_id})
        MERGE (m)-[:HAS_CLAIM]->(c)
    """, {"member_id": member_id, "claim_id": claim_id})

    kg.execute_write("""
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (p:Provider {provider_id: $provider_id})
        MERGE (c)-[:SERVICED_BY]->(p)
    """, {"claim_id": claim_id, "provider_id": provider_id})


def merge_care_gap(care_gap_id, member_id, measure_id, gap_status, is_open,
                   created_on, closed_on):
    """
    FIX: gap_status (Open/Closed) is read directly from the sheet's CareManagerID column.
    is_open is passed in explicitly — not inferred from closed_on being blank.
    """
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (g:CareGap {care_gap_id: $care_gap_id})
        SET g.gap_status = $gap_status,
            g.is_open = $is_open,
            g.created_on = $created_on,
            g.closed_on = $closed_on
    """, {"care_gap_id": care_gap_id, "gap_status": gap_status,
          "is_open": is_open, "created_on": created_on, "closed_on": closed_on})

    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        MERGE (m)-[:HAS_CARE_GAP]->(g)
    """, {"member_id": member_id, "care_gap_id": care_gap_id})

    kg.execute_write("""
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        MATCH (q:QualityMeasure {measure_id: $measure_id})
        MERGE (g)-[:RELATES_TO]->(q)
    """, {"care_gap_id": care_gap_id, "measure_id": measure_id})


def merge_outreach(outreach_id, care_gap_id, member_id, care_manager_id,
                   channel, date, status):
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (o:Outreach {outreach_id: $outreach_id})
        SET o.channel = $channel,
            o.date = $date,
            o.status = $status,
            o.care_manager_id = $care_manager_id
    """, {"outreach_id": outreach_id, "channel": channel, "date": date,
          "status": status, "care_manager_id": care_manager_id})

    kg.execute_write("""
        MATCH (o:Outreach {outreach_id: $outreach_id})
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        MERGE (o)-[:TARGETS]->(g)
    """, {"outreach_id": outreach_id, "care_gap_id": care_gap_id})

    kg.execute_write("""
        MATCH (o:Outreach {outreach_id: $outreach_id})
        MATCH (m:Member {member_id: $member_id})
        MERGE (o)-[:CONTACTS]->(m)
    """, {"outreach_id": outreach_id, "member_id": member_id})


# ── Query helpers used by agents ──────────────────────────────────────────────

def get_member_open_gaps(member_id: str):
    kg = get_knowledge_graph()
    results = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        WHERE g.is_open = true
        OPTIONAL MATCH (q)-[:REQUIRES_CODES]->(cs:CodeSet)
        WITH g, q,
             [x IN collect({type: cs.code_type, codes: cs.codes})
              WHERE x.type IS NOT NULL AND toLower(x.type) CONTAINS 'cpt'] AS cpt_sets
        RETURN g.care_gap_id AS care_gap_id,
               g.created_on AS created_on,
               g.gap_status AS gap_status,
               q.measure_id AS measure_id,
               q.name AS measure_name,
               q.description AS resolution_guide,
               q.lookback_months AS lookback_months,
               cpt_sets
    """, {"member_id": member_id})

    for gap in results:
        all_cpt: list = []
        for cs in (gap.pop("cpt_sets", []) or []):
            codes = cs.get("codes", [])
            if isinstance(codes, list):
                all_cpt.extend(str(c).strip() for c in codes if c)
        gap["required_cpt_codes"] = ", ".join(all_cpt)

    return results


def get_applicable_measures(age: int, gender: str):
    """
    Return all QualityMeasure golden reference nodes with:
      - flat cpt_codes (union of all CPT CodeSets) for simple gap checks
      - screening_options list (per-option type/lookback/cpt_codes) for
        measures like COL and CCS that have multiple screening paths.
    Age/gender filtering is done in Python by _measure_applies().
    """
    kg = get_knowledge_graph()

    # ── 1. Flat CPT codes from measure-level CodeSet nodes ────────────────────
    results = kg.run_query("""
        MATCH (q:QualityMeasure)
        OPTIONAL MATCH (q)-[:REQUIRES_CODES]->(cs:CodeSet)
        WITH q,
             [x IN collect({type: cs.code_type, codes: cs.codes})
              WHERE x.type IS NOT NULL] AS code_sets
        RETURN q.measure_id AS measure_id,
               q.name AS name,
               q.age_range AS age_range,
               q.lookback_months AS lookback_months,
               q.description AS description,
               q.diagnosis_requirement AS diagnosis_requirement,
               code_sets
    """, {})

    for m in results:
        all_cpt: list = []
        for cs in (m.pop("code_sets", []) or []):
            if cs and "cpt" in str(cs.get("type", "")).lower():
                codes = cs.get("codes", [])
                if isinstance(codes, list):
                    all_cpt.extend(str(c).strip() for c in codes if c)
        m["cpt_codes"] = ",".join(all_cpt)
        m["screening_options"] = []   # filled in step 2

    # ── 2. Per-ScreeningOption codes (COL has 5 options, CCS has 3) ───────────
    option_rows = kg.run_query("""
        MATCH (q:QualityMeasure)-[:HAS_SCREENING_OPTION]->(so:ScreeningOption)
        OPTIONAL MATCH (so)-[:USES_CODES]->(soc:CodeSet)
        WHERE toLower(soc.code_type) CONTAINS 'cpt'
        WITH q, so, collect(soc.codes) AS code_lists
        RETURN q.measure_id AS measure_id,
               so.type AS option_type,
               so.lookback_months AS option_lookback,
               code_lists
        ORDER BY so.lookback_months DESC
    """, {})

    # Build a lookup: measure_id -> [{type, lookback_months, cpt_codes}, ...]
    from collections import defaultdict
    options_by_measure: dict = defaultdict(list)
    for row in option_rows:
        all_cpt = []
        for code_list in (row.get("code_lists", []) or []):
            if isinstance(code_list, list):
                all_cpt.extend(str(c).strip() for c in code_list if c)
        if all_cpt:
            options_by_measure[row["measure_id"]].append({
                "type": row["option_type"],
                "lookback_months": int(row["option_lookback"] or 12),
                "cpt_codes": ",".join(all_cpt),
            })

    for m in results:
        m["screening_options"] = options_by_measure.get(m["measure_id"], [])

    return results


def get_member_claims_cpt_codes(member_id: str):
    kg = get_knowledge_graph()
    return kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_CLAIM]->(c:Claim)
        RETURN c.cpt_code AS cpt_code,
               c.service_date AS service_date,
               c.icd_code AS icd_code
        ORDER BY c.service_date DESC
    """, {"member_id": member_id})


def get_member_profile(member_id: str):
    kg = get_knowledge_graph()
    results = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})
        OPTIONAL MATCH (m)-[:ENROLLED_IN]->(b:BenefitPlan)
        OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
        RETURN m.name AS name, m.dob AS dob, m.gender AS gender,
               m.age_str AS age_str, b.plan_id AS plan_id,
               b.copay AS copay, b.preventive_covered AS preventive_covered,
               b.eligibility_rules AS eligibility_rules,
               p.name AS pcp_name, p.specialty AS pcp_specialty,
               p.network_status AS pcp_network_status
    """, {"member_id": member_id})
    return results[0] if results else {}


def get_measure_comprehensive(measure_id: str):
    """
    Get comprehensive measure definition with all related nodes.
    Returns: measure details, code sets, exclusions, guidelines, best practices
    """
    kg = get_knowledge_graph()
    
    # Get main measure
    measure = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})
        RETURN q.measure_id AS measure_id,
               q.name AS name,
               q.description AS description,
               q.age_range AS age_range,
               q.min_age AS min_age,
               q.max_age AS max_age,
               q.gender_requirement AS gender_requirement,
               q.lookback_months AS lookback_months,
               q.lookback_description AS lookback_description,
               q.numerator_criteria AS numerator_criteria,
               q.denominator_criteria AS denominator_criteria,
               q.diagnosis_requirement AS diagnosis_requirement
    """, {"measure_id": measure_id})
    
    if not measure:
        return None
    
    result = measure[0]
    
    # Get code sets
    code_sets = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})-[:REQUIRES_CODES]->(cs:CodeSet)
        RETURN cs.code_type AS code_type, cs.codes AS codes
    """, {"measure_id": measure_id})
    result["code_sets"] = {cs["code_type"]: cs["codes"] for cs in code_sets}
    
    # Get exclusions
    exclusions = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})-[r:HAS_EXCLUSION]->(e:ExclusionCriteria)
        RETURN e.type AS type,
               e.description AS description,
               e.category AS category,
               e.cpt_codes AS cpt_codes,
               e.hcpcs_codes AS hcpcs_codes,
               e.icd10_codes AS icd10_codes,
               e.icd10pcs_codes AS icd10pcs_codes,
               e.modifiers AS modifiers,
               e.criteria AS criteria
    """, {"measure_id": measure_id})
    result["exclusions"] = exclusions
    
    # Get clinical guidelines
    guidelines = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})-[:FOLLOWS_GUIDELINE]->(cg:ClinicalGuideline)
        RETURN cg.acceptable AS acceptable, cg.not_acceptable AS not_acceptable
    """, {"measure_id": measure_id})
    result["clinical_guidelines"] = guidelines[0] if guidelines else {}
    
    # Get best practices
    best_practices = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})-[:HAS_BEST_PRACTICES]->(bp:BestPractices)
        RETURN bp.practices AS practices
    """, {"measure_id": measure_id})
    result["best_practices"] = best_practices[0]["practices"] if best_practices else []
    
    # Get screening options if present
    screening_options = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})-[:HAS_SCREENING_OPTION]->(so:ScreeningOption)
        RETURN so.type AS type,
               so.lookback_months AS lookback_months,
               so.description AS description,
               so.age_range AS age_range
    """, {"measure_id": measure_id})
    result["screening_options"] = screening_options
    
    return result


def check_member_exclusions(member_id: str, measure_id: str):
    """
    Check if member meets any exclusion criteria for a measure.
    Returns list of exclusions that apply to this member.
    """
    kg = get_knowledge_graph()
    
    # Get member's claims with codes
    member_claims = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_CLAIM]->(c:Claim)
        RETURN c.cpt_code AS cpt_code,
               c.icd_code AS icd_code,
               c.service_date AS service_date
    """, {"member_id": member_id})
    
    # Get exclusion criteria for measure
    exclusions = kg.run_query("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})-[:HAS_EXCLUSION]->(e:ExclusionCriteria)
        RETURN e.type AS type,
               e.description AS description,
               e.category AS category,
               e.cpt_codes AS cpt_codes,
               e.icd10_codes AS icd10_codes
    """, {"measure_id": measure_id})
    
    matched_exclusions = []
    
    for exclusion in exclusions:
        # Check if member has any matching codes
        member_cpt_codes = [c["cpt_code"] for c in member_claims if c["cpt_code"]]
        member_icd_codes = [c["icd_code"] for c in member_claims if c["icd_code"]]
        
        exclusion_cpt = exclusion.get("cpt_codes", [])
        exclusion_icd = exclusion.get("icd10_codes", [])
        
        # Check for matches
        if exclusion_cpt and any(code in exclusion_cpt for code in member_cpt_codes):
            matched_exclusions.append(exclusion)
        elif exclusion_icd and any(code in exclusion_icd for code in member_icd_codes):
            matched_exclusions.append(exclusion)
    
    return matched_exclusions
