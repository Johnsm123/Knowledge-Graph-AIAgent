from neo4j import GraphDatabase
from synthetic_data import DISEASES
from dotenv import load_dotenv
import os

load_dotenv()


def get_driver():
    uri      = os.getenv("NEO4J_URI")
    user     = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


class Neo4jLoader:
    def __init__(self):
        self.driver = get_driver()

    def close(self):
        self.driver.close()

    def clear_db(self):
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def load_all(self):
        with self.driver.session() as session:
            for disease in DISEASES:
                self._load_disease(session, disease)

    def _load_disease(self, session, d: dict):
        session.run(
            "MERGE (dis:Disease {name: $name}) SET dis.category = $category",
            name=d["name"], category=d["category"]
        )

        def link_nodes(label, items, rel_type):
            for item in items:
                session.run(
                    f"MERGE (n:{label} {{name: $item}}) "
                    f"WITH n MATCH (dis:Disease {{name: $disease}}) "
                    f"MERGE (dis)-[:{rel_type}]->(n)",
                    item=item, disease=d["name"]
                )

        link_nodes("Symptom",      d["symptoms"],      "HAS_SYMPTOM")
        link_nodes("RiskFactor",   d["risk_factors"],  "HAS_RISK_FACTOR")
        link_nodes("Prevention",   d["prevention"],    "PREVENTED_BY")
        link_nodes("Diagnosis",    d["diagnosis"],     "DIAGNOSED_BY")
        link_nodes("Treatment",    d["treatments"],    "TREATED_WITH")
        link_nodes("Cure",         d["cures"],         "CURED_BY")
        link_nodes("Complication", d["complications"], "LEADS_TO")
        link_nodes("CareGap",      d["care_gaps"],     "HAS_CARE_GAP")

        # Cross-disease: shared risk factors
        for other in DISEASES:
            if other["name"] == d["name"]:
                continue
            if set(d["risk_factors"]) & set(other["risk_factors"]):
                session.run(
                    "MATCH (a:Disease {name: $a}), (b:Disease {name: $b}) "
                    "MERGE (a)-[:SHARES_RISK_FACTOR]->(b)",
                    a=d["name"], b=other["name"]
                )

        # Complication → Disease (if complication is itself a known disease)
        disease_names = {dis["name"] for dis in DISEASES}
        for comp in d["complications"]:
            if comp in disease_names:
                session.run(
                    "MATCH (dis:Disease {name: $disease}), (comp_dis:Disease {name: $comp}) "
                    "MERGE (dis)-[:COMPLICATION_LEADS_TO_DISEASE]->(comp_dis)",
                    disease=d["name"], comp=comp
                )


def load_to_neo4j(clear: bool = False):
    loader = Neo4jLoader()
    if clear:
        loader.clear_db()
    loader.load_all()
    loader.close()
    return {"status": "success", "diseases_loaded": len(DISEASES)}
