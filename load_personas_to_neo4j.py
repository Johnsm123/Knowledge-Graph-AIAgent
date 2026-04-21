"""
load_personas_to_neo4j.py
Generic loader — reads any measure's personas JSON and loads into Neo4j.

Usage:
  python load_personas_to_neo4j.py measures/bcs_e_personas.json
  python load_personas_to_neo4j.py measures/aap_personas.json
"""

import os, json, sys
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USERNAME")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DB       = os.getenv("NEO4J_DATABASE")

BATCH_SIZE = 500


def load_personas(driver, personas: list):
    measure_id = personas[0].get("measure", "UNKNOWN")

    with driver.session(database=DB) as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Persona) REQUIRE p.persona_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:Measure) REQUIRE m.measure_id IS UNIQUE")

        # Remove old personas for this measure before reloading
        session.run("MATCH (p:Persona {measure: $measure_id}) DETACH DELETE p", measure_id=measure_id)
        print(f"Cleared old {measure_id} personas.")

        # Load in batches
        total = len(personas)
        for i in range(0, total, BATCH_SIZE):
            batch = personas[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $batch AS p
                MERGE (node:Persona {persona_id: p.persona_id})
                SET node += p
                WITH node, p
                MATCH (m:Measure {measure_id: p.measure})
                MERGE (node)-[:BELONGS_TO_MEASURE]->(m)
            """, batch=batch)
            print(f"  Loaded {min(i + BATCH_SIZE, total)}/{total} personas...")

        # Summary counts
        result = session.run("""
            MATCH (p:Persona {measure: $measure_id})
            RETURN p.care_gap_status AS status, COUNT(p) AS count
            ORDER BY status
        """, measure_id=measure_id)

        print(f"\nNeo4j summary for {measure_id}:")
        total_loaded = 0
        for record in result:
            print(f"  {record['status']:<20}: {record['count']}")
            total_loaded += record["count"]
        print(f"  {'TOTAL':<20}: {total_loaded}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python load_personas_to_neo4j.py measures/aap_personas.json")
        sys.exit(1)

    personas_path = sys.argv[1]
    if not os.path.exists(personas_path):
        print(f"File not found: {personas_path}")
        sys.exit(1)

    with open(personas_path, encoding="utf-8") as f:
        personas = json.load(f)

    print(f"Loaded {len(personas)} personas from {personas_path}")

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        driver.verify_connectivity()
        print("Neo4j connected.")
        load_personas(driver, personas)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
