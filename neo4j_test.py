from dotenv import load_dotenv
import os
load_dotenv()

from neo4j import GraphDatabase

uri      = os.getenv("NEO4J_URI")
user     = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")

print(f"URI:  {uri}")
print(f"USER: {user}")

try:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    print("SUCCESS: Connected to Neo4j Aura!")
    driver.close()
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
