"""
Wipe only Member-tied data from Neo4j, preserving reference data
(QualityMeasure, BenefitPlan, Provider).

Usage:
    python -m src.wipe_members
"""
import logging
from src.neo4j_connection import get_knowledge_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def wipe_members():
    kg = get_knowledge_graph()
    labels_to_wipe = [
        "Outreach", "CareGap", "Claim", "Enrollment",
        "Lifestyle", "FamilyMember", "Condition", "MedicalHistoryEntry",
        "Persona", "Member",
    ]
    for label in labels_to_wipe:
        while True:
            result = kg.run_query(f"""
                MATCH (n:{label})
                WITH n LIMIT 1000
                DETACH DELETE n
                RETURN count(n) AS deleted
            """)
            deleted = result[0]["deleted"] if result else 0
            logger.info(f"  Deleted batch of {deleted} :{label} nodes")
            if deleted == 0:
                break
    total = kg.run_query("MATCH (m:Member) RETURN count(m) AS c")[0]["c"]
    logger.info(f"Remaining :Member nodes = {total}")


if __name__ == "__main__":
    wipe_members()
