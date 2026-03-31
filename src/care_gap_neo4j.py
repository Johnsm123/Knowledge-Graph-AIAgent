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
    ]
    for c in constraints:
        kg.execute_write(c)


# ── Static / Golden Reference Nodes ──────────────────────────────────────────

def merge_quality_measure(measure_id, name, age_range, lookback_months,
                           proactive_lookback_months, cpt_codes, description):
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
    return kg.run_query("""
        MATCH (m:Member {member_id: $member_id})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        WHERE g.is_open = true
        RETURN g.care_gap_id AS care_gap_id,
               g.created_on AS created_on,
               g.gap_status AS gap_status,
               q.measure_id AS measure_id,
               q.name AS measure_name,
               q.description AS resolution_guide,
               q.cpt_codes AS required_cpt_codes,
               q.lookback_months AS lookback_months
    """, {"member_id": member_id})


def get_applicable_measures(age: int, gender: str):
    """Return all QualityMeasure golden reference nodes — age/gender filtering done in Python."""
    kg = get_knowledge_graph()
    return kg.run_query("""
        MATCH (q:QualityMeasure)
        RETURN q.measure_id AS measure_id,
               q.name AS name,
               q.age_range AS age_range,
               q.lookback_months AS lookback_months,
               q.proactive_lookback_months AS proactive_lookback_months,
               q.cpt_codes AS cpt_codes,
               q.description AS description
    """, {})


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
