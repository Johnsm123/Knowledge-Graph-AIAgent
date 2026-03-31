"""
Wipe all existing Neo4j data and reload fresh from Excel.
Run this once to clear stale/old schema data before testing agents.

Usage:
    python -m src.wipe_and_reload
"""
import logging
from src.neo4j_connection import get_knowledge_graph
from src.care_gap_data_loader import load_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def wipe_all():
    """
    Delete ALL nodes and relationships in the database.
    Covers both old schema (Patient, Condition, Medication, Symptom, LabTest, Treatment)
    and new care gap schema (Member, Provider, BenefitPlan, QualityMeasure,
    Claim, CareGap, Outreach).
    """
    kg = get_knowledge_graph()

    logger.info("Wiping all existing nodes and relationships...")

    # Drop all constraints first so MERGE/CREATE won't conflict after wipe
    drop_constraints = kg.run_query("SHOW CONSTRAINTS YIELD name RETURN name")
    for row in drop_constraints:
        constraint_name = row.get("name")
        if constraint_name:
            kg.execute_write(f"DROP CONSTRAINT {constraint_name} IF EXISTS")
            logger.info(f"  Dropped constraint: {constraint_name}")

    # Delete all nodes and relationships in batches (safe for large graphs)
    while True:
        result = kg.run_query("""
            MATCH (n)
            WITH n LIMIT 1000
            DETACH DELETE n
            RETURN count(n) AS deleted
        """)
        deleted = result[0]["deleted"] if result else 0
        logger.info(f"  Deleted batch of {deleted} nodes")
        if deleted == 0:
            break

    logger.info("Database wiped clean.")


def verify_empty():
    """Confirm the database is empty before reloading."""
    kg = get_knowledge_graph()
    result = kg.run_query("MATCH (n) RETURN count(n) AS total")
    total = result[0]["total"] if result else 0
    if total == 0:
        logger.info("Verified: database is empty. Ready to reload.")
        return True
    else:
        logger.warning(f"Database still has {total} nodes — wipe may have failed.")
        return False


def wipe_and_reload():
    wipe_all()
    if verify_empty():
        logger.info("Starting fresh data load from Excel...")
        load_all()
        logger.info("Done. Neo4j is ready with clean care gap data.")
    else:
        logger.error("Aborting reload — database was not fully wiped.")


if __name__ == "__main__":
    wipe_and_reload()
