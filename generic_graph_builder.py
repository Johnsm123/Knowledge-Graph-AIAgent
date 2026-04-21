"""
generic_graph_builder.py
Loads ANY HEDIS measure config + ideal personas into Neo4j.

Usage:
  python generic_graph_builder.py <measure_config.json> <personas.json>

Example:
  python generic_graph_builder.py measures/bcs_e_config.json bcs_agent_personas.json
"""

import os, sys, json
sys.stdout.reconfigure(encoding="utf-8")

from datetime import date
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
URI  = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USERNAME")
PWD  = os.getenv("NEO4J_PASSWORD")
DB   = os.getenv("NEO4J_DATABASE")


def cleanup(session, measure_id):
    session.run("MATCH (p:Persona {measure: $mid}) DETACH DELETE p", mid=measure_id)
    session.run("""
        MATCH (m:Measure {measure_id: $mid})
        OPTIONAL MATCH (m)-[:HAS_COMPLIANCE_CODE]->(c:ComplianceCode)
        OPTIONAL MATCH (m)-[:HAS_EXCLUSION_CODE]->(e:ExclusionCode)
        DETACH DELETE c, e
    """, mid=measure_id)
    print(f"Cleanup          : OK")


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
    print(f"Measure          : {config['measure_id']} — {config['measure_name']}")


def load_compliance_codes(session, config):
    mid, count = config["measure_id"], 0
    for code_type, codes in config.get("compliance_codes", {}).items():
        for code in codes:
            session.run("""
                MERGE (c:ComplianceCode {code: $code})
                SET c.type = $ctype, c.measure = $mid
                WITH c MATCH (m:Measure {measure_id: $mid})
                MERGE (m)-[:HAS_COMPLIANCE_CODE]->(c)
            """, code=code, ctype=code_type, mid=mid)
            count += 1
    print(f"ComplianceCode   : {count}")


def load_exclusion_codes(session, config):
    mid, count = config["measure_id"], 0
    for excl_name, code_map in config.get("exclusion_codes", {}).items():
        for code_type, codes in code_map.items():
            for code in codes:
                session.run("""
                    MERGE (e:ExclusionCode {code: $code})
                    SET e.type = $ctype, e.exclusion_reason = $excl, e.measure = $mid
                    WITH e MATCH (m:Measure {measure_id: $mid})
                    MERGE (m)-[:HAS_EXCLUSION_CODE]->(e)
                """, code=code, ctype=code_type, excl=excl_name, mid=mid)
                count += 1
    print(f"ExclusionCode    : {count}")


def load_personas(session, personas, measure_id):
    for i in range(0, len(personas), 100):
        session.run("""
            UNWIND $personas AS p
            MERGE (n:Persona {persona_id: p.persona_id})
            SET n += p
            WITH n MATCH (m:Measure {measure_id: n.measure})
            MERGE (n)-[:BELONGS_TO_MEASURE]->(m)
        """, personas=personas[i:i+100])

    # summary
    from collections import Counter
    counts = Counter(p.get("care_gap_status") for p in personas)
    print(f"Persona nodes    : {len(personas)} | {dict(counts)}")


def print_counts(driver):
    with driver.session(database=DB) as s:
        nodes = s.run("""
            MATCH (n) WHERE labels(n)[0] IN ['Measure','ComplianceCode','ExclusionCode','Persona']
            RETURN labels(n)[0] AS lbl, count(n) AS cnt ORDER BY lbl
        """).data()
        rels = s.run("""
            MATCH ()-[r]->() WHERE type(r) IN ['BELONGS_TO_MEASURE','HAS_COMPLIANCE_CODE','HAS_EXCLUSION_CODE']
            RETURN type(r) AS t, count(r) AS cnt ORDER BY t
        """).data()
    print(f"\n{'='*40}")
    print(f"{'Label':<22} {'Count':>8}")
    print("-" * 32)
    for r in nodes:
        print(f"{str(r['lbl']):<22} {r['cnt']:>8}")
    print(f"\n{'Relationship':<30} {'Count':>8}")
    print("-" * 40)
    for r in rels:
        print(f"{r['t']:<30} {r['cnt']:>8}")
    print("=" * 40)


def main():
    if len(sys.argv) < 3:
        print("Usage: python generic_graph_builder.py <config.json> <personas.json>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        config = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        personas = json.load(f)

    driver = GraphDatabase.driver(URI, auth=(USER, PWD))
    driver.verify_connectivity()
    print(f"Neo4j connected\nLoading: {config['measure_id']}\n")

    try:
        with driver.session(database=DB) as s:
            cleanup(s, config["measure_id"])
            load_measure(s, config)
            load_compliance_codes(s, config)
            load_exclusion_codes(s, config)
            load_personas(s, personas, config["measure_id"])
        print_counts(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
