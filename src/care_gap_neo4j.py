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
        "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Lifestyle) REQUIRE l.lifestyle_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (fm:FamilyMember) REQUIRE fm.family_member_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (cond:Condition) REQUIRE cond.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (mh:MedicalHistoryEntry) REQUIRE mh.entry_id IS UNIQUE",
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

def get_next_member_id():
    """
    Return the next available member ID by finding the highest numeric
    suffix among existing Member nodes that match the pattern M<digits>.
    E.g. if the highest is M0030, returns 'M0031'.
    Falls back to 'M0001' if no members exist or none match the pattern.
    """
    kg = get_knowledge_graph()
    rows = kg.run_query("""
        MATCH (m:Member)
        WHERE m.member_id =~ 'M[0-9]+'
        RETURN m.member_id AS member_id
        ORDER BY m.member_id DESC
    """, {})
    if not rows:
        return "M0001"
    # Extract numeric parts and find the max
    max_num = 0
    for row in rows:
        mid = row.get("member_id", "")
        try:
            num = int(mid[1:])
            if num > max_num:
                max_num = num
        except (ValueError, IndexError):
            continue
    next_num = max_num + 1
    # Preserve at least 4 digits of padding (e.g. M0031), grow naturally beyond that
    pad = max(4, len(str(next_num)))
    return f"M{str(next_num).zfill(pad)}"


def merge_member(member_id, name, dob, gender, pcp_id, zip_code,
                 enrollment_start, enrollment_end, age_str,
                 email="", phone="", street_address="", city="", state="",
                 race="", language="English", tobacco_use=False,
                 insurance_type="Commercial", chronic_conditions=None):
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
            m.age_str = $age_str,
            m.email = $email,
            m.phone = $phone,
            m.street_address = $street_address,
            m.city = $city,
            m.state = $state,
            m.race = $race,
            m.language = $language,
            m.tobacco_use = $tobacco_use,
            m.insurance_type = $insurance_type,
            m.chronic_conditions = $chronic_conditions
    """, {"member_id": member_id, "name": name, "dob": str(dob), "gender": gender,
          "pcp_id": pcp_id, "zip_code": str(zip_code),
          "enrollment_start": str(enrollment_start),
          "enrollment_end": str(enrollment_end), "age_str": age_str,
          "email": email, "phone": phone, "street_address": street_address,
          "city": city, "state": state, "race": race, "language": language,
          "tobacco_use": tobacco_use, "insurance_type": insurance_type,
          "chronic_conditions": chronic_conditions or []})


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
                   created_on, closed_on, primary_cpt_code="", primary_icd10=""):
    """
    Write or update a CareGap node.
    - gap_status: "Open" or "Closed"
    - is_open: bool
    - primary_cpt_code: single CPT to display/order to close this gap
    - primary_icd10: single ICD-10 code (member's diagnosis or screening encounter code)

    Demo-scope guard (lowest layer of defense): refuses to write any CareGap
    whose measure_id is outside CARE_GAP_ENABLED_MEASURES (default
    'BCS,CCS,COL'). Set CARE_GAP_ENABLED_MEASURES='*' to disable.
    """
    import os as _os
    _raw = _os.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL").strip()
    if _raw not in ("*", "all", "ALL"):
        _enabled = {m.strip().upper() for m in _raw.split(",") if m.strip()}
        if _enabled and (measure_id or "").upper() not in _enabled:
            # Print so it shows up in the Flask console regardless of log config.
            print(f"[CARE-GAP-WRITE-BLOCKED] refused to write {measure_id} for "
                  f"{member_id} — outside demo scope {sorted(_enabled)}")
            return  # silently no-op — every layer above this also filters
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (g:CareGap {care_gap_id: $care_gap_id})
        SET g.gap_status = $gap_status,
            g.is_open = $is_open,
            g.created_on = $created_on,
            g.closed_on = $closed_on,
            g.measure_id = $measure_id,
            g.primary_cpt_code = $primary_cpt_code,
            g.primary_icd10 = $primary_icd10
    """, {"care_gap_id": care_gap_id, "gap_status": gap_status,
          "is_open": is_open, "created_on": created_on, "closed_on": closed_on,
          "measure_id": measure_id, "primary_cpt_code": primary_cpt_code,
          "primary_icd10": primary_icd10})

    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        MERGE (m)-[:HAS_CARE_GAP]->(g)
    """, {"member_id": member_id, "care_gap_id": care_gap_id})

    # MERGE (not MATCH) the QualityMeasure node so it is always created if
    # the golden-reference measure_id (e.g. "KED") doesn't yet have a node
    # in the graph. A silent MATCH failure would leave the RELATES_TO link
    # missing, causing get_all_members to count zero open gaps.
    # Also populate name/description/lookback from the Python golden reference
    # so the member panel shows correct measure names even before load_all() runs.
    try:
        from src.hedis_golden_reference import HEDIS_MEASURES as _HM
        _mdata = _HM.get(measure_id, {})
    except Exception:
        _mdata = {}
    kg.execute_write("""
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        MERGE (q:QualityMeasure {measure_id: $measure_id})
        SET q.name               = $name,
            q.description        = $description,
            q.lookback_months    = $lookback_months,
            q.age_range          = $age_range,
            q.gender_requirement = $gender_requirement
        MERGE (g)-[:RELATES_TO]->(q)
    """, {
        "care_gap_id":        care_gap_id,
        "measure_id":         measure_id,
        "name":               _mdata.get("name", measure_id),
        "description":        _mdata.get("description", ""),
        "lookback_months":    _mdata.get("lookback_months"),
        "age_range":          _mdata.get("age_range", ""),
        "gender_requirement": _mdata.get("gender_requirement", "Any"),
    })


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
    """Return open CareGaps for the member.

    Honors the CARE_GAP_ENABLED_MEASURES env var (default 'BCS,CCS,COL') so
    that even if older non-demo CareGap nodes still exist in the graph, they
    never surface in the email / PDF / member panel. To restore unrestricted
    behavior set CARE_GAP_ENABLED_MEASURES='*'.
    """
    import os as _os
    kg = get_knowledge_graph()
    results = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        WHERE g.is_open = true
        RETURN g.care_gap_id       AS care_gap_id,
               g.created_on        AS created_on,
               g.gap_status        AS gap_status,
               g.primary_cpt_code  AS primary_cpt_code,
               g.primary_icd10     AS primary_icd10,
               q.measure_id        AS measure_id,
               q.name              AS measure_name,
               q.description       AS resolution_guide,
               q.lookback_months   AS lookback_months
    """, {"member_id": member_id})

    # Demo-scope filter — applied here so every consumer (email, PDF, member
    # panel, dashboard) sees the same scoped list without each one having to
    # re-implement the filter.
    raw = _os.environ.get("CARE_GAP_ENABLED_MEASURES", "BCS,CCS,COL").strip()
    if raw not in ("*", "all", "ALL"):
        enabled = {m.strip().upper() for m in raw.split(",") if m.strip()}
        if enabled:
            results = [g for g in results
                       if (g.get("measure_id") or "").upper() in enabled]

    # Normalise: expose primary_cpt_code also as required_cpt_codes for
    # backward compatibility with any frontend field that still reads that key.
    for gap in results:
        gap["required_cpt_codes"] = gap.get("primary_cpt_code") or ""

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
               q.gender_requirement AS gender_requirement,
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
        RETURN c.claim_id    AS claim_id,
               c.measure_id  AS measure_id,
               c.cpt_code    AS cpt_code,
               c.service_date AS service_date,
               c.icd_code    AS icd_code,
               c.status      AS status
        ORDER BY c.service_date DESC
    """, {"member_id": member_id})


def get_member_profile(member_id: str):
    kg = get_knowledge_graph()
    results = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})
        OPTIONAL MATCH (m)-[:ENROLLED_IN]->(b:BenefitPlan)
        OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
        RETURN m.name AS name, m.dob AS dob, m.gender AS gender,
               m.age_str AS age_str, m.age_str AS age,
               b.plan_id AS plan_id, b.plan_id AS plan, b.plan_id AS plan_name,
               b.copay AS copay, b.preventive_covered AS preventive_covered,
               b.eligibility_rules AS eligibility_rules,
               p.name AS pcp_name, p.provider_id AS pcp_id,
               p.specialty AS pcp_specialty,
               p.network_status AS pcp_network_status,
               m.chronic_conditions AS chronic_conditions,
               m.tobacco_use AS tobacco_use,
               m.insurance_type AS insurance_type,
               m.race AS race,
               m.language AS language,
               m.email AS email,
               m.phone AS phone,
               m.address AS address
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


def check_member_exclusions(member_id: str, measure_id: str, extra_icd_codes: list = None):
    """
    Check if member meets any exclusion criteria for a measure.
    extra_icd_codes: ICD codes synthesised from chronic_conditions (for new members with no claims).
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
        member_cpt_codes = [c["cpt_code"] for c in member_claims if c["cpt_code"]]
        # Merge claim ICD codes with condition-derived ICD codes
        member_icd_codes = [c["icd_code"] for c in member_claims if c["icd_code"]]
        if extra_icd_codes:
            member_icd_codes = list(set(member_icd_codes + extra_icd_codes))

        exclusion_cpt = exclusion.get("cpt_codes", [])
        exclusion_icd = exclusion.get("icd10_codes", [])

        if exclusion_cpt and any(code in exclusion_cpt for code in member_cpt_codes):
            matched_exclusions.append(exclusion)
        elif exclusion_icd and any(code in exclusion_icd for code in member_icd_codes):
            matched_exclusions.append(exclusion)

    return matched_exclusions


# ── Email Functions ───────────────────────────────────────────────────────────

def merge_email(email_id: str, member_id: str, subject: str, body: str,
                from_email: str, to_email: str, timestamp: str,
                direction: str, is_read: bool = False):
    """Store an email node and link it to the member."""
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (e:Email {email_id: $email_id})
        SET e.member_id  = $member_id,
            e.subject    = $subject,
            e.body       = $body,
            e.from_email = $from_email,
            e.to_email   = $to_email,
            e.timestamp  = $timestamp,
            e.direction  = $direction,
            e.is_read    = $is_read
    """, {
        "email_id": email_id, "member_id": member_id, "subject": subject,
        "body": body, "from_email": from_email, "to_email": to_email,
        "timestamp": timestamp, "direction": direction, "is_read": is_read,
    })
    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (e:Email {email_id: $email_id})
        MERGE (m)-[:HAS_EMAIL]->(e)
    """, {"member_id": member_id, "email_id": email_id})


def get_member_emails(member_id: str):
    """Return all emails for a member, newest first."""
    kg = get_knowledge_graph()
    return kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_EMAIL]->(e:Email)
        RETURN e.email_id   AS email_id,
               e.subject    AS subject,
               e.body       AS body,
               e.html_body  AS html_body,
               e.from_email AS from_email,
               e.to_email   AS to_email,
               e.timestamp  AS timestamp,
               e.direction  AS direction,
               e.is_read    AS is_read,
               e.email_type     AS email_type,
               e.appointment_id AS appointment_id,
               e.measure_id     AS measure_id,
               e.care_gap_id    AS care_gap_id
        ORDER BY e.timestamp DESC
    """, {"member_id": member_id})


def mark_email_read(email_id: str):
    """Mark a single email as read."""
    kg = get_knowledge_graph()
    kg.execute_write("""
        MATCH (e:Email {email_id: $email_id})
        SET e.is_read = true
    """, {"email_id": email_id})


# ── Appointment Functions ─────────────────────────────────────────────────────

def merge_appointment(appointment_id: str, member_id: str, measure_id: str,
                      appointment_date: str, appointment_time: str,
                      lab_number: str, lab_specialist: str, lab_location: str,
                      screening_name: str, cpt_codes: str, icd_codes: str,
                      provider_id: str, status: str = "Scheduled",
                      care_gap_id: str = ""):
    """Store an Appointment node and link it to Member and QualityMeasure."""
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (a:Appointment {appointment_id: $appointment_id})
        SET a.member_id        = $member_id,
            a.measure_id       = $measure_id,
            a.appointment_date = $appointment_date,
            a.appointment_time = $appointment_time,
            a.lab_number       = $lab_number,
            a.lab_specialist   = $lab_specialist,
            a.lab_location     = $lab_location,
            a.screening_name   = $screening_name,
            a.cpt_codes        = $cpt_codes,
            a.icd_codes        = $icd_codes,
            a.provider_id      = $provider_id,
            a.status           = $status,
            a.care_gap_id      = $care_gap_id,
            a.created_at       = datetime()
    """, {"appointment_id": appointment_id, "member_id": member_id,
          "measure_id": measure_id, "appointment_date": appointment_date,
          "appointment_time": appointment_time, "lab_number": lab_number,
          "lab_specialist": lab_specialist, "lab_location": lab_location,
          "screening_name": screening_name, "cpt_codes": cpt_codes,
          "icd_codes": icd_codes, "provider_id": provider_id, "status": status,
          "care_gap_id": care_gap_id})
    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})
        MATCH (a:Appointment {appointment_id: $appointment_id})
        MERGE (m)-[:HAS_APPOINTMENT]->(a)
    """, {"member_id": member_id, "appointment_id": appointment_id})
    kg.execute_write("""
        MATCH (q:QualityMeasure {measure_id: $measure_id})
        MATCH (a:Appointment {appointment_id: $appointment_id})
        MERGE (a)-[:FOR_MEASURE]->(q)
    """, {"measure_id": measure_id, "appointment_id": appointment_id})


def get_appointment(appointment_id: str):
    """Return full appointment details including member and plan info."""
    kg = get_knowledge_graph()
    results = kg.run_query("""
        MATCH (a:Appointment {appointment_id: $appointment_id})
        MATCH (m:Member {member_id: a.member_id})
        OPTIONAL MATCH (m)-[:ENROLLED_IN]->(b:BenefitPlan)
        OPTIONAL MATCH (m)-[:ASSIGNED_TO]->(p:Provider)
        RETURN a.appointment_id   AS appointment_id,
               a.member_id        AS member_id,
               a.measure_id       AS measure_id,
               a.appointment_date AS appointment_date,
               a.appointment_time AS appointment_time,
               a.lab_number       AS lab_number,
               a.lab_specialist   AS lab_specialist,
               a.lab_location     AS lab_location,
               a.screening_name   AS screening_name,
               a.cpt_codes        AS cpt_codes,
               a.icd_codes        AS icd_codes,
               a.provider_id      AS provider_id,
               a.status           AS status,
               m.name             AS member_name,
               m.email            AS member_email,
               m.phone            AS member_phone,
               m.insurance_type   AS insurance_type,
               b.plan_id          AS plan_id,
               b.copay            AS copay,
               p.name             AS pcp_name
    """, {"appointment_id": appointment_id})
    return results[0] if results else None


def close_care_gap_with_claim(care_gap_id: str, member_id: str, measure_id: str,
                               provider_id: str, cpt_code: str, icd_code: str,
                               service_date: str, claim_id: str, plan_id: str):
    """Create a Claim, link it to Member/Provider, then close the CareGap."""
    kg = get_knowledge_graph()
    # Create and link claim
    kg.execute_write("""
        MERGE (c:Claim {claim_id: $claim_id})
        SET c.cpt_code     = $cpt_code,
            c.icd_code     = $icd_code,
            c.service_date = $service_date,
            c.status       = 'Processed',
            c.plan_id      = $plan_id,
            c.measure_id   = $measure_id
    """, {"claim_id": claim_id, "cpt_code": cpt_code, "icd_code": icd_code,
          "service_date": service_date, "plan_id": plan_id, "measure_id": measure_id})
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
    # Close the care gap
    kg.execute_write("""
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        SET g.is_open    = false,
            g.closed_on  = $service_date,
            g.claim_id   = $claim_id,
            g.gap_status = 'Closed'
    """, {"care_gap_id": care_gap_id, "service_date": service_date, "claim_id": claim_id})
    # Link claim to care gap
    kg.execute_write("""
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (g:CareGap {care_gap_id: $care_gap_id})
        MERGE (c)-[:CLOSES_GAP]->(g)
    """, {"claim_id": claim_id, "care_gap_id": care_gap_id})


# ── Extended Patient Record: Lifestyle, Family History, Medical History ──────

HEREDITARY_HIGH_RISK_CONDITIONS = {
    "Diabetes Type 2", "Diabetes Type 1", "Hypertension", "Coronary Artery Disease",
    "Stroke", "Breast Cancer", "Colorectal Cancer", "Prostate Cancer",
    "Ovarian Cancer", "Alzheimer's Disease", "Parkinson's Disease",
    "Asthma", "High Cholesterol", "Depression", "Bipolar Disorder",
    "Schizophrenia", "Thyroid Disease", "Kidney Disease", "Liver Disease",
    "Osteoporosis", "Rheumatoid Arthritis", "Sickle Cell Disease",
    "Hemophilia", "Cystic Fibrosis", "Huntington's Disease",
}

FIRST_DEGREE_RELATIONS = {"father", "mother", "sibling", "son", "daughter"}


def merge_lifestyle(member_id: str, lifestyle: dict):
    """
    Upsert a member's Lifestyle node (1:1 with Member).
    lifestyle keys (all optional):
      bmi, height_cm, weight_kg, smoking_status, alcohol_use,
      exercise_frequency, diet_type, sleep_hours_avg, stress_level, notes
    """
    lifestyle = lifestyle or {}
    kg = get_knowledge_graph()
    lifestyle_id = f"{member_id}_lifestyle"
    kg.execute_write("""
        MERGE (l:Lifestyle {lifestyle_id: $lifestyle_id})
        SET l.member_id          = $member_id,
            l.bmi                = $bmi,
            l.height_cm          = $height_cm,
            l.weight_kg          = $weight_kg,
            l.smoking_status     = $smoking_status,
            l.alcohol_use        = $alcohol_use,
            l.exercise_frequency = $exercise_frequency,
            l.diet_type          = $diet_type,
            l.sleep_hours_avg    = $sleep_hours_avg,
            l.stress_level       = $stress_level,
            l.notes              = $notes,
            l.updated_at         = datetime()
        WITH l
        MATCH (m:Member {member_id: $member_id})
        MERGE (m)-[:HAS_LIFESTYLE]->(l)
    """, {
        "lifestyle_id": lifestyle_id,
        "member_id": member_id,
        "bmi": lifestyle.get("bmi"),
        "height_cm": lifestyle.get("height_cm"),
        "weight_kg": lifestyle.get("weight_kg"),
        "smoking_status": lifestyle.get("smoking_status", ""),
        "alcohol_use": lifestyle.get("alcohol_use", ""),
        "exercise_frequency": lifestyle.get("exercise_frequency", ""),
        "diet_type": lifestyle.get("diet_type", ""),
        "sleep_hours_avg": lifestyle.get("sleep_hours_avg"),
        "stress_level": lifestyle.get("stress_level", ""),
        "notes": lifestyle.get("notes", ""),
    })


def merge_condition(name: str, icd10: str = ""):
    """Upsert a Condition node keyed by canonical name."""
    if not name:
        return
    kg = get_knowledge_graph()
    kg.execute_write("""
        MERGE (c:Condition {name: $name})
        ON CREATE SET c.icd10 = $icd10
        SET c.icd10 = coalesce($icd10, c.icd10, '')
    """, {"name": name.strip(), "icd10": icd10 or ""})


def replace_family_history(member_id: str, family_members: list):
    """
    Replace the member's family history with the provided list. Each entry:
      {relation, name?, alive, age_or_age_at_death, conditions: [..],
       cause_of_death?, notes?}
    Safe to call repeatedly; wipes prior FamilyMember nodes for this member.
    """
    kg = get_knowledge_graph()
    # Detach delete old FamilyMember nodes for this member (keeps Condition nodes reusable).
    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_RELATIVE]->(fm:FamilyMember)
        DETACH DELETE fm
    """, {"member_id": member_id})

    for idx, fm in enumerate(family_members or []):
        relation = (fm.get("relation") or "").strip()
        if not relation:
            continue
        fm_id = f"{member_id}_fm_{idx}_{relation}".replace(" ", "_")
        conditions = [c for c in (fm.get("conditions") or []) if c]
        kg.execute_write("""
            MERGE (fm:FamilyMember {family_member_id: $fm_id})
            SET fm.member_id           = $member_id,
                fm.relation            = $relation,
                fm.name                = $name,
                fm.alive               = $alive,
                fm.age_or_age_at_death = $age,
                fm.cause_of_death      = $cause,
                fm.notes               = $notes,
                fm.conditions_summary  = $conditions
            WITH fm
            MATCH (m:Member {member_id: $member_id})
            MERGE (m)-[:HAS_RELATIVE]->(fm)
        """, {
            "fm_id": fm_id,
            "member_id": member_id,
            "relation": relation,
            "name": fm.get("name", ""),
            "alive": bool(fm.get("alive", True)),
            "age": fm.get("age_or_age_at_death") or "",
            "cause": fm.get("cause_of_death", ""),
            "notes": fm.get("notes", ""),
            "conditions": conditions,
        })
        for cond_name in conditions:
            merge_condition(cond_name)
            kg.execute_write("""
                MATCH (fm:FamilyMember {family_member_id: $fm_id})
                MATCH (c:Condition {name: $name})
                MERGE (fm)-[:HAS_CONDITION]->(c)
            """, {"fm_id": fm_id, "name": cond_name.strip()})


def replace_medical_history(member_id: str, entries: dict):
    """
    Replace the member's medical history. `entries` shape:
      {
        past_conditions:   [{name, onset_year?, status?, notes?}, ...],
        current_conditions:[{name, onset_year?, notes?}, ...],
        surgeries:         [{name, year?, notes?}, ...],
        allergies:         [{substance, severity?, reaction?}, ...],
        medications:       [{name, dose?, started?, purpose?}, ...],
        immunizations:     [{name, year?}, ...]
      }
    """
    kg = get_knowledge_graph()
    kg.execute_write("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_MEDICAL_HISTORY]->(e:MedicalHistoryEntry)
        DETACH DELETE e
    """, {"member_id": member_id})

    buckets = [
        ("past_condition",    (entries or {}).get("past_conditions")   or []),
        ("current_condition", (entries or {}).get("current_conditions") or []),
        ("surgery",           (entries or {}).get("surgeries")          or []),
        ("allergy",           (entries or {}).get("allergies")          or []),
        ("medication",        (entries or {}).get("medications")        or []),
        ("immunization",      (entries or {}).get("immunizations")      or []),
    ]

    for bucket_type, items in buckets:
        for idx, item in enumerate(items):
            entry_id = f"{member_id}_{bucket_type}_{idx}"
            label = item.get("name") or item.get("substance") or ""
            if not label:
                continue
            kg.execute_write("""
                MERGE (e:MedicalHistoryEntry {entry_id: $entry_id})
                SET e.member_id  = $member_id,
                    e.type       = $type,
                    e.label      = $label,
                    e.year       = $year,
                    e.status     = $status,
                    e.severity   = $severity,
                    e.reaction   = $reaction,
                    e.dose       = $dose,
                    e.started    = $started,
                    e.purpose    = $purpose,
                    e.notes      = $notes
                WITH e
                MATCH (m:Member {member_id: $member_id})
                MERGE (m)-[:HAS_MEDICAL_HISTORY]->(e)
            """, {
                "entry_id": entry_id,
                "member_id": member_id,
                "type": bucket_type,
                "label": label,
                "year": str(item.get("year") or item.get("onset_year") or ""),
                "status": item.get("status", ""),
                "severity": item.get("severity", ""),
                "reaction": item.get("reaction", ""),
                "dose": item.get("dose", ""),
                "started": str(item.get("started") or ""),
                "purpose": item.get("purpose", ""),
                "notes": item.get("notes", ""),
            })
            if bucket_type in ("past_condition", "current_condition"):
                merge_condition(label)
                kg.execute_write("""
                    MATCH (e:MedicalHistoryEntry {entry_id: $entry_id})
                    MATCH (c:Condition {name: $name})
                    MERGE (e)-[:REFERENCES_CONDITION]->(c)
                """, {"entry_id": entry_id, "name": label.strip()})


def get_member_lifestyle(member_id: str):
    kg = get_knowledge_graph()
    rows = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_LIFESTYLE]->(l:Lifestyle)
        RETURN l.bmi                AS bmi,
               l.height_cm          AS height_cm,
               l.weight_kg          AS weight_kg,
               l.smoking_status     AS smoking_status,
               l.alcohol_use        AS alcohol_use,
               l.exercise_frequency AS exercise_frequency,
               l.diet_type          AS diet_type,
               l.sleep_hours_avg    AS sleep_hours_avg,
               l.stress_level       AS stress_level,
               l.notes              AS notes
    """, {"member_id": member_id})
    return rows[0] if rows else {}


def get_member_family_history(member_id: str):
    kg = get_knowledge_graph()
    return kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_RELATIVE]->(fm:FamilyMember)
        OPTIONAL MATCH (fm)-[:HAS_CONDITION]->(c:Condition)
        WITH fm, collect(DISTINCT c.name) AS condition_names
        RETURN fm.family_member_id   AS family_member_id,
               fm.relation           AS relation,
               fm.name               AS name,
               fm.alive              AS alive,
               fm.age_or_age_at_death AS age_or_age_at_death,
               fm.cause_of_death     AS cause_of_death,
               fm.notes              AS notes,
               [x IN condition_names WHERE x IS NOT NULL] AS conditions
        ORDER BY fm.relation
    """, {"member_id": member_id})


def get_member_medical_history(member_id: str):
    kg = get_knowledge_graph()
    rows = kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_MEDICAL_HISTORY]->(e:MedicalHistoryEntry)
        RETURN e.type      AS type,
               e.label     AS label,
               e.year      AS year,
               e.status    AS status,
               e.severity  AS severity,
               e.reaction  AS reaction,
               e.dose      AS dose,
               e.started   AS started,
               e.purpose   AS purpose,
               e.notes     AS notes
        ORDER BY e.type, e.year DESC
    """, {"member_id": member_id})

    buckets = {
        "past_conditions": [], "current_conditions": [], "surgeries": [],
        "allergies": [], "medications": [], "immunizations": [],
    }
    type_to_bucket = {
        "past_condition": "past_conditions",
        "current_condition": "current_conditions",
        "surgery": "surgeries",
        "allergy": "allergies",
        "medication": "medications",
        "immunization": "immunizations",
    }
    for r in rows:
        bkt = type_to_bucket.get(r.get("type"))
        if not bkt:
            continue
        buckets[bkt].append({k: v for k, v in r.items() if v not in (None, "")})
    return buckets


def compute_hereditary_risks(family_history: list) -> list:
    """
    Derive a list of elevated hereditary risks from first-degree relatives'
    conditions. Each entry: {condition, relatives: [..]}.
    """
    risk_map: dict = {}
    for fm in family_history or []:
        relation = (fm.get("relation") or "").lower()
        is_first_degree = any(rel in relation for rel in FIRST_DEGREE_RELATIONS)
        if not is_first_degree:
            continue
        for cond in (fm.get("conditions") or []):
            if cond in HEREDITARY_HIGH_RISK_CONDITIONS:
                risk_map.setdefault(cond, set()).add(fm.get("relation"))
    return [
        {"condition": cond, "relatives": sorted(r for r in rels if r)}
        for cond, rels in sorted(risk_map.items())
    ]


def get_member_extended_profile(member_id: str) -> dict:
    """Return lifestyle + family_history + medical_history + hereditary_risks."""
    family_history = get_member_family_history(member_id)
    return {
        "lifestyle": get_member_lifestyle(member_id),
        "family_history": family_history,
        "medical_history": get_member_medical_history(member_id),
        "hereditary_risks": compute_hereditary_risks(family_history),
    }
