"""
Neo4j Database Connection Module
Handles all Neo4j Aura interactions via Bolt protocol.
Only connection + query utilities — all schema logic lives in care_gap_neo4j.py
"""
from neo4j import GraphDatabase
import logging
from typing import Any, Dict, List, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class MedicalKnowledgeGraph:
    """Manages connections to Neo4j Aura via Bolt protocol."""

    def __init__(self, uri=None, username=None, password=None):
        try:
            self.driver = GraphDatabase.driver(
                uri or settings.neo4j_uri,
                auth=(username or settings.neo4j_username, password or settings.neo4j_password)
            )
            self.driver.verify_connectivity()
            logger.info("Successfully connected to Neo4j Aura via Bolt")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {str(e)}")
            raise

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")

    def run_query(self, query: str, parameters: Optional[Dict] = None) -> List[Dict]:
        """Execute a Cypher query and return results as a list of dicts."""
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters or {})
                return result.data()
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            return []

    def execute_write(self, query: str, parameters: Optional[Dict] = None) -> bool:
        """Execute a write Cypher statement."""
        try:
            with self.driver.session() as session:
                session.run(query, parameters or {})
                return True
        except Exception as e:
            logger.error(f"Write operation failed: {str(e)}")
            return False


# Global singletons
_kg = None
_ref_kg = None


def get_knowledge_graph() -> MedicalKnowledgeGraph:
    """Get or create the singleton knowledge graph connection."""
    global _kg
    if _kg is None:
        _kg = MedicalKnowledgeGraph()
    return _kg


def get_reference_graph() -> MedicalKnowledgeGraph:
    """Get or create the singleton reference (persona visualization) database connection."""
    global _ref_kg
    if _ref_kg is None:
        if not settings.neo4j_ref_uri:
            raise RuntimeError("Reference DB not configured (NEO4J_REF_* env vars)")
        _ref_kg = MedicalKnowledgeGraph(
            uri=settings.neo4j_ref_uri,
            username=settings.neo4j_ref_username,
            password=settings.neo4j_ref_password,
        )
    return _ref_kg


def reset_reference_graph():
    """Force reconnect to reference DB (e.g. after credential change)."""
    global _ref_kg
    if _ref_kg:
        try:
            _ref_kg.close()
        except Exception:
            pass
    _ref_kg = None
