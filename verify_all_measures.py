"""
verify_all_measures.py
Displays all loaded measures with their details.
"""

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
URI  = os.getenv("NEO4J_URI")
USER = os.getenv("NEO4J_USERNAME")
PWD  = os.getenv("NEO4J_PASSWORD")
DB   = os.getenv("NEO4J_DATABASE")

driver = GraphDatabase.driver(URI, auth=(USER, PWD))

with driver.session(database=DB) as session:
    result = session.run("""
        MATCH (m:Measure)
        OPTIONAL MATCH (m)-[:HAS_COMPLIANCE_CODE]->(cc)
        OPTIONAL MATCH (m)-[:HAS_EXCLUSION_CODE]->(ec)
        OPTIONAL MATCH (p:Persona)-[:BELONGS_TO_MEASURE]->(m)
        RETURN m.measure_id as id, 
               m.name as name,
               m.eligible_gender as gender,
               m.eligible_age_min as age_min,
               m.eligible_age_max as age_max,
               count(DISTINCT cc) as compliance_codes,
               count(DISTINCT ec) as exclusion_codes,
               count(DISTINCT p) as personas
        ORDER BY m.measure_id
    """)
    
    print("\n" + "="*90)
    print(f"{'ID':<8} {'Measure Name':<38} {'Gender':<8} {'Age':<10} {'CC':<5} {'EC':<5} {'Personas':<8}")
    print("="*90)
    
    total_personas = 0
    for record in result:
        age_range = f"{record['age_min']}-{record['age_max']}"
        gender = record['gender'] or 'Any'
        print(f"{record['id']:<8} {record['name']:<38} {gender:<8} {age_range:<10} "
              f"{record['compliance_codes']:<5} {record['exclusion_codes']:<5} {record['personas']:<8}")
        total_personas += record['personas']
    
    print("="*90)
    print(f"Total Personas: {total_personas}")
    print()

driver.close()
