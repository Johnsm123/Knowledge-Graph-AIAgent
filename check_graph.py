import sys, os
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
uri  = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USERNAME")
pwd  = os.getenv("NEO4J_PASSWORD")
db   = os.getenv("NEO4J_DATABASE")

print("URI :", uri)
print("USER:", user)
print("DB  :", db)

driver = GraphDatabase.driver(uri, auth=(user, pwd))
driver.verify_connectivity()
print("Connection: OK")

with driver.session(database=db) as s:
    rows = s.run("MATCH (n) RETURN labels(n)[0] AS lbl, count(n) AS cnt ORDER BY lbl").data()
    if not rows:
        print("Graph is EMPTY — no nodes found")
    else:
        print(f"\n{'Label':<20} {'Count':>8}")
        print("-" * 30)
        for r in rows:
            print(f"{str(r['lbl']):<20} {r['cnt']:>8}")

    rel = s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS cnt ORDER BY t").data()
    if rel:
        print(f"\n{'Relationship':<30} {'Count':>8}")
        print("-" * 40)
        for r in rel:
            print(f"{r['t']:<30} {r['cnt']:>8}")
    else:
        print("\nNo relationships found")

    measures = s.run("""
        MATCH (m:Measure)
        OPTIONAL MATCH (p:Persona)-[:BELONGS_TO_MEASURE]->(m)
        OPTIONAL MATCH (m)-[:HAS_COMPLIANCE_CODE]->(cc)
        OPTIONAL MATCH (m)-[:HAS_EXCLUSION_CODE]->(ec)
        RETURN m.measure_id AS measure,
               count(DISTINCT p)  AS personas,
               count(DISTINCT cc) AS compliance_codes,
               count(DISTINCT ec) AS exclusion_codes
        ORDER BY measure
    """).data()
    if measures:
        print(f"\n{'Measure':<10} {'Personas':>10} {'CPT/Codes':>10} {'Excl Codes':>12}")
        print("-" * 45)
        for r in measures:
            print(f"{r['measure']:<10} {r['personas']:>10} {r['compliance_codes']:>10} {r['exclusion_codes']:>12}")
    else:
        print("\nNo Measure nodes found")

driver.close()
