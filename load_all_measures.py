"""
load_all_measures.py
Loads all 9 HEDIS measures into Neo4j using existing config and persona files.
"""

import os, json
from datetime import date
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
URI  = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USERNAME")
PWD  = os.getenv("NEO4J_PASSWORD")
DB   = os.getenv("NEO4J_DATABASE")

MEASURES = [
    ("measures/bcs_e_config.json", "measures/bcs_e_personas.json"),
    ("measures/ccs_e_config.json", "measures/ccs_e_personas.json"),
    ("measures/chl_config.json", "measures/chl_personas.json"),
    ("measures/col_e_config.json", "measures/col_e_personas.json"),
    ("measures/aap_config.json", "measures/aap_personas.json"),
    ("measures/ais_e_config.json", "measures/ais_e_personas.json"),
    ("measures/cis_e_config.json", "measures/cis_e_personas.json"),
    ("measures/ima_e_config.json", "measures/ima_e_personas.json"),
    ("measures/wcv_config.json", "measures/wcv_personas.json"),
]


def setup_constraints(session):
    """Create uniqueness constraints to prevent duplicates."""
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Measure) REQUIRE m.measure_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Persona) REQUIRE p.persona_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:ComplianceCode) REQUIRE c.code IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:ExclusionCode) REQUIRE (e.code, e.measure) IS UNIQUE",
    ]
    for c in constraints:
        try:
            session.run(c)
        except Exception:
            pass  # Constraint may already exist


def load_measure(session, config):
    session.run("""
        MERGE (m:Measure {measure_id: $mid})
        SET m.name             = $name,
            m.eligible_age_min = $age_min,
            m.eligible_age_max = $age_max,
            m.eligible_gender  = $gender,
            m.measurement_year = $year,
            m.lookback_years   = $lookback,
            m.updated_on       = $today
    """, mid=config["measure_id"], name=config["measure_name"],
         age_min=config["eligible_age_min"], age_max=config["eligible_age_max"],
         gender=config["eligible_gender"], year=config.get("measurement_year"),
         lookback=config.get("lookback_years"), today=str(date.today()))


def load_compliance_codes(session, config):
    mid, count = config["measure_id"], 0
    for code_type, codes in config.get("compliance_codes", {}).items():
        for code in codes:
            session.run("""
                MERGE (c:ComplianceCode {code: $code})
                SET c.type = $ctype, c.measure = $mid
                WITH c
                MATCH (m:Measure {measure_id: $mid})
                MERGE (m)-[:HAS_COMPLIANCE_CODE]->(c)
            """, code=code, ctype=code_type, mid=mid)
            count += 1
    return count


def load_exclusion_codes(session, config):
    mid, count = config["measure_id"], 0
    for excl_name, code_map in config.get("exclusion_codes", {}).items():
        for code_type, codes in code_map.items():
            for code in codes:
                session.run("""
                    MERGE (e:ExclusionCode {code: $code, measure: $mid})
                    SET e.type = $ctype, e.exclusion_reason = $excl
                    WITH e
                    MATCH (m:Measure {measure_id: $mid})
                    MERGE (m)-[:HAS_EXCLUSION_CODE]->(e)
                """, code=code, ctype=code_type, excl=excl_name, mid=mid)
                count += 1
    return count


def load_personas(session, personas, measure_id):
    """Load personas in batches of 100."""
    for i in range(0, len(personas), 100):
        batch = personas[i:i+100]
        session.run("""
            UNWIND $personas AS p
            MERGE (n:Persona {persona_id: p.persona_id})
            SET n += p
            WITH n
            MATCH (m:Measure {measure_id: $mid})
            MERGE (n)-[:BELONGS_TO_MEASURE]->(m)
        """, personas=batch, mid=measure_id)


def main():
    driver = GraphDatabase.driver(URI, auth=(USER, PWD))
    driver.verify_connectivity()
    print("Neo4j connected\n")

    # Setup constraints first
    with driver.session(database=DB) as s:
        setup_constraints(s)

    print("="*60)

    total_personas = 0

    for config_path, persona_path in MEASURES:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        with open(persona_path, encoding="utf-8") as f:
            personas = json.load(f)

        mid = config["measure_id"]

        with driver.session(database=DB) as s:
            load_measure(s, config)
            cc_count = load_compliance_codes(s, config)
            ec_count = load_exclusion_codes(s, config)
            load_personas(s, personas, mid)

        total_personas += len(personas)
        print(f"{mid:8} | {config['measure_name'][:35]:35} | Personas: {len(personas):4} | CC: {cc_count:3} | EC: {ec_count:3}")

    print("="*60)
    print(f"Total personas loaded: {total_personas}")

    # Final counts
    with driver.session(database=DB) as s:
        measures = s.run("MATCH (m:Measure) RETURN count(m) as cnt").single()["cnt"]
        personas = s.run("MATCH (p:Persona) RETURN count(p) as cnt").single()["cnt"]
        cc = s.run("MATCH (c:ComplianceCode) RETURN count(c) as cnt").single()["cnt"]
        ec = s.run("MATCH (e:ExclusionCode) RETURN count(e) as cnt").single()["cnt"]

    print(f"\nFinal Neo4j counts:")
    print(f"  Measures: {measures}")
    print(f"  Personas: {personas}")
    print(f"  ComplianceCodes: {cc}")
    print(f"  ExclusionCodes: {ec}")

    driver.close()


if __name__ == "__main__":
    main()