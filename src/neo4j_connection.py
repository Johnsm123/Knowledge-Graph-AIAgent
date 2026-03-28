"""
Neo4j Database Connection Module
Handles all Neo4j Aura interactions for the medical knowledge graph
"""
from neo4j import GraphDatabase, Session, Transaction
from typing import Any, Dict, List, Optional
import logging
from config.settings import settings

logger = logging.getLogger(__name__)


class MedicalKnowledgeGraph:
    """
    Manages connections to Neo4j Aura and provides utility methods
    for medical knowledge graph operations
    """
    
    def __init__(self):
        """Initialize Neo4j driver with Aura configuration"""
        try:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
                encrypted=True
            )
            self.verify_connection()
            logger.info("Successfully connected to Neo4j Aura")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {str(e)}")
            raise
    
    def verify_connection(self) -> bool:
        """Verify database connection"""
        try:
            with self.driver.session(database=settings.neo4j_database) as session:
                result = session.run("RETURN 1")
                return result.single() is not None
        except Exception as e:
            logger.error(f"Connection verification failed: {str(e)}")
            return False
    
    def close(self):
        """Close the database connection"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")
    
    def run_query(self, query: str, parameters: Optional[Dict] = None) -> List[Dict]:
        """
        Execute a Cypher query and return results
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            List of result dictionaries
        """
        try:
            with self.driver.session(database=settings.neo4j_database) as session:
                result = session.run(query, parameters or {})
                return [record.data() for record in result]
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            raise
    
    def execute_write(self, query: str, parameters: Optional[Dict] = None) -> Any:
        """
        Execute a write operation
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            Query results
        """
        try:
            with self.driver.session(database=settings.neo4j_database) as session:
                result = session.execute_write(
                    self._write_transaction, query, parameters or {}
                )
                return result
        except Exception as e:
            logger.error(f"Write operation failed: {str(e)}")
            raise
    
    @staticmethod
    def _write_transaction(tx: Transaction, query: str, parameters: Dict) -> Any:
        """Execute write transaction"""
        result = tx.run(query, parameters)
        return result.consume().counters
    
    def create_patient(self, patient_id: str, name: str, age: int, gender: str) -> bool:
        """Create a patient node"""
        query = """
        CREATE (p:Patient {
            patient_id: $patient_id,
            name: $name,
            age: $age,
            gender: $gender,
            created_at: datetime()
        })
        RETURN p
        """
        try:
            self.execute_write(query, {
                "patient_id": patient_id,
                "name": name,
                "age": age,
                "gender": gender
            })
            logger.info(f"Created patient: {patient_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create patient: {str(e)}")
            return False
    
    def create_medical_condition(self, condition_id: str, name: str, 
                                 severity: str, description: str) -> bool:
        """Create a medical condition node"""
        query = """
        CREATE (c:Condition {
            condition_id: $condition_id,
            name: $name,
            severity: $severity,
            description: $description,
            created_at: datetime()
        })
        RETURN c
        """
        try:
            self.execute_write(query, {
                "condition_id": condition_id,
                "name": name,
                "severity": severity,
                "description": description
            })
            logger.info(f"Created condition: {condition_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create condition: {str(e)}")
            return False
    
    def relate_patient_to_condition(self, patient_id: str, condition_id: str,
                                   diagnosed_date: str, status: str) -> bool:
        """Create relationship between patient and medical condition"""
        query = """
        MATCH (p:Patient {patient_id: $patient_id})
        MATCH (c:Condition {condition_id: $condition_id})
        CREATE (p)-[r:HAS_CONDITION {
            diagnosed_date: $diagnosed_date,
            status: $status,
            created_at: datetime()
        }]->(c)
        RETURN r
        """
        try:
            self.execute_write(query, {
                "patient_id": patient_id,
                "condition_id": condition_id,
                "diagnosed_date": diagnosed_date,
                "status": status
            })
            logger.info(f"Related patient {patient_id} to condition {condition_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create relationship: {str(e)}")
            return False
    
    def get_patient_history(self, patient_id: str) -> List[Dict]:
        """Get complete medical history for a patient"""
        query = """
        MATCH (p:Patient {patient_id: $patient_id})-[r:HAS_CONDITION]->(c:Condition)
        RETURN {
            patient_id: p.patient_id,
            patient_name: p.name,
            condition_id: c.condition_id,
            condition_name: c.name,
            diagnosed_date: r.diagnosed_date,
            status: r.status,
            severity: c.severity
        } as history
        ORDER BY r.diagnosed_date DESC
        """
        try:
            return self.run_query(query, {"patient_id": patient_id})
        except Exception as e:
            logger.error(f"Failed to retrieve patient history: {str(e)}")
            return []
    
    def find_similar_patients(self, patient_id: str, limit: int = 5) -> List[Dict]:
        """Find patients with similar conditions"""
        query = """
        MATCH (p1:Patient {patient_id: $patient_id})-[:HAS_CONDITION]->(c:Condition)
        MATCH (p2:Patient)-[:HAS_CONDITION]->(c:Condition)
        WHERE p2.patient_id <> $patient_id
        RETURN {
            patient_id: p2.patient_id,
            patient_name: p2.name,
            common_conditions: count(c),
            age: p2.age,
            gender: p2.gender
        } as similar_patient
        ORDER BY common_conditions DESC
        LIMIT $limit
        """
        try:
            return self.run_query(query, {"patient_id": patient_id, "limit": limit})
        except Exception as e:
            logger.error(f"Failed to find similar patients: {str(e)}")
            return []


# Global instance
kg = None


def get_knowledge_graph() -> MedicalKnowledgeGraph:
    """Get or create knowledge graph instance"""
    global kg
    if kg is None:
        kg = MedicalKnowledgeGraph()
    return kg
