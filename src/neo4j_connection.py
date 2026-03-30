"""
Neo4j Database Connection Module
Handles all Neo4j Aura interactions via Bolt protocol
"""
from neo4j import GraphDatabase
import logging
from typing import Any, Dict, List, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class MedicalKnowledgeGraph:
    """
    Manages connections to Neo4j Aura via Bolt protocol
    Provides utility methods for medical knowledge graph operations
    """
    
    def __init__(self):
        """Initialize Neo4j Bolt connection"""
        try:
            self.driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password)
            )
            self.driver.verify_connectivity()
            logger.info("Successfully connected to Neo4j Aura via Bolt")
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {str(e)}")
            raise
    
    def close(self):
        """Close the database connection"""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")
    
    def run_query(self, query: str, parameters: Optional[Dict] = None) -> List[Dict]:
        """Execute a Cypher query and return results"""
        try:
            with self.driver.session() as session:
                result = session.run(query, parameters or {})
                return result.data()
        except Exception as e:
            logger.error(f"Query execution failed: {str(e)}")
            return []
    
    def execute_write(self, query: str, parameters: Optional[Dict] = None) -> bool:
        """Execute a write operation"""
        try:
            with self.driver.session() as session:
                session.run(query, parameters or {})
                return True
        except Exception as e:
            logger.error(f"Write operation failed: {str(e)}")
            return False
    
    # Patient operations
    def create_patient(self, patient_id: str, name: str, age: int, gender: str, 
                      blood_type: str = "O+", admission_date: str = "") -> bool:
        """Create a patient node"""
        query = """
        CREATE (p:Patient {
            patient_id: $patient_id,
            name: $name,
            age: $age,
            gender: $gender,
            blood_type: $blood_type,
            admission_date: $admission_date,
            created_at: datetime()
        })
        RETURN p
        """
        return self.execute_write(query, {
            "patient_id": patient_id,
            "name": name,
            "age": age,
            "gender": gender,
            "blood_type": blood_type,
            "admission_date": admission_date
        })
    
    def create_medical_condition(self, condition_id: str, name: str, 
                                severity: str, icd_code: str, description: str) -> bool:
        """Create a medical condition node"""
        query = """
        CREATE (c:Condition {
            condition_id: $condition_id,
            name: $name,
            severity: $severity,
            icd_code: $icd_code,
            description: $description,
            created_at: datetime()
        })
        RETURN c
        """
        return self.execute_write(query, {
            "condition_id": condition_id,
            "name": name,
            "severity": severity,
            "icd_code": icd_code,
            "description": description
        })
    
    def create_medication(self, medication_id: str, name: str, dosage: str, 
                         frequency: str, category: str) -> bool:
        """Create a medication node"""
        query = """
        CREATE (m:Medication {
            medication_id: $medication_id,
            name: $name,
            dosage: $dosage,
            frequency: $frequency,
            category: $category,
            created_at: datetime()
        })
        RETURN m
        """
        return self.execute_write(query, {
            "medication_id": medication_id,
            "name": name,
            "dosage": dosage,
            "frequency": frequency,
            "category": category
        })
    
    def create_symptom(self, symptom_id: str, name: str, severity: str, description: str) -> bool:
        """Create a symptom node"""
        query = """
        CREATE (s:Symptom {
            symptom_id: $symptom_id,
            name: $name,
            severity: $severity,
            description: $description,
            created_at: datetime()
        })
        RETURN s
        """
        return self.execute_write(query, {
            "symptom_id": symptom_id,
            "name": name,
            "severity": severity,
            "description": description
        })
    
    def create_lab_test(self, test_id: str, name: str, code: str, 
                       normal_range: str, unit: str) -> bool:
        """Create a lab test node"""
        query = """
        CREATE (l:LabTest {
            test_id: $test_id,
            name: $name,
            code: $code,
            normal_range: $normal_range,
            unit: $unit,
            created_at: datetime()
        })
        RETURN l
        """
        return self.execute_write(query, {
            "test_id": test_id,
            "name": name,
            "code": code,
            "normal_range": normal_range,
            "unit": unit
        })
    
    def create_treatment(self, treatment_id: str, name: str, treatment_type: str, 
                        duration_days: int, description: str) -> bool:
        """Create a treatment node"""
        query = """
        CREATE (t:Treatment {
            treatment_id: $treatment_id,
            name: $name,
            type: $treatment_type,
            duration_days: $duration_days,
            description: $description,
            created_at: datetime()
        })
        RETURN t
        """
        return self.execute_write(query, {
            "treatment_id": treatment_id,
            "name": name,
            "treatment_type": treatment_type,
            "duration_days": duration_days,
            "description": description
        })
    
    def relate_patient_to_condition(self, patient_id: str, condition_id: str,
                                   diagnosed_date: str, status: str) -> bool:
        """Create relationship between patient and condition"""
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
        return self.execute_write(query, {
            "patient_id": patient_id,
            "condition_id": condition_id,
            "diagnosed_date": diagnosed_date,
            "status": status
        })
    
    def relate_condition_to_symptom(self, condition_id: str, symptom_id: str, 
                                   relationship_type: str) -> bool:
        """Create relationship between condition and symptom"""
        query = """
        MATCH (c:Condition {condition_id: $condition_id})
        MATCH (s:Symptom {symptom_id: $symptom_id})
        CREATE (c)-[r:PRESENTS_WITH {
            type: $relationship_type,
            created_at: datetime()
        }]->(s)
        RETURN r
        """
        return self.execute_write(query, {
            "condition_id": condition_id,
            "symptom_id": symptom_id,
            "relationship_type": relationship_type
        })
    
    def relate_medication_to_condition(self, medication_id: str, condition_id: str, 
                                      relationship_type: str) -> bool:
        """Create relationship between medication and condition"""
        query = """
        MATCH (m:Medication {medication_id: $medication_id})
        MATCH (c:Condition {condition_id: $condition_id})
        CREATE (m)-[r:TREATS {
            type: $relationship_type,
            created_at: datetime()
        }]->(c)
        RETURN r
        """
        return self.execute_write(query, {
            "medication_id": medication_id,
            "condition_id": condition_id,
            "relationship_type": relationship_type
        })
    
    def relate_condition_complications(self, condition_id1: str, condition_id2: str, 
                                      relationship_type: str) -> bool:
        """Create relationship between conditions (complications)"""
        query = """
        MATCH (c1:Condition {condition_id: $condition_id1})
        MATCH (c2:Condition {condition_id: $condition_id2})
        CREATE (c1)-[r:COMPOUNDS {
            type: $relationship_type,
            created_at: datetime()
        }]->(c2)
        RETURN r
        """
        return self.execute_write(query, {
            "condition_id1": condition_id1,
            "condition_id2": condition_id2,
            "relationship_type": relationship_type
        })
    
    # Query operations
    def get_patient_history(self, patient_id: str) -> List[Dict]:
        """Get complete medical history for a patient"""
        query = """
        MATCH (p:Patient {patient_id: $patient_id})-[r:HAS_CONDITION]->(c:Condition)
        RETURN {
            patient_id: p.patient_id,
            patient_name: p.name,
            age: p.age,
            blood_type: p.blood_type,
            condition_id: c.condition_id,
            condition_name: c.name,
            diagnosed_date: r.diagnosed_date,
            status: r.status,
            severity: c.severity,
            icd_code: c.icd_code
        } as history
        ORDER BY r.diagnosed_date DESC
        """
        results = self.run_query(query, {"patient_id": patient_id})
        return [r["history"] for r in results]
    
    def find_similar_patients(self, patient_id: str, limit: int = 5) -> List[Dict]:
        """Find patients with similar conditions"""
        query = """
        MATCH (p1:Patient {patient_id: $patient_id})-[:HAS_CONDITION]->(c:Condition)
        MATCH (p2:Patient)-[:HAS_CONDITION]->(c:Condition)
        WHERE p2.patient_id <> $patient_id
        RETURN {
            patient_id: p2.patient_id,
            patient_name: p2.name,
            age: p2.age,
            gender: p2.gender,
            common_conditions: count(c),
            blood_type: p2.blood_type
        } as similar_patient
        ORDER BY common_conditions DESC
        LIMIT $limit
        """
        results = self.run_query(query, {"patient_id": patient_id, "limit": limit})
        return [r["similar_patient"] for r in results]
    
    def get_patient_medications(self, patient_id: str) -> List[Dict]:
        """Get all medications for a patient"""
        query = """
        MATCH (p:Patient {patient_id: $patient_id})-[:HAS_CONDITION]->(c:Condition)
        MATCH (m:Medication)-[:TREATS]->(c)
        RETURN {
            medication_id: m.medication_id,
            medication_name: m.name,
            dosage: m.dosage,
            frequency: m.frequency,
            category: m.category,
            condition: c.name
        } as medication
        """
        results = self.run_query(query, {"patient_id": patient_id})
        return [r["medication"] for r in results]
    
    def get_condition_symptoms(self, condition_id: str) -> List[Dict]:
        """Get all symptoms for a condition"""
        query = """
        MATCH (c:Condition {condition_id: $condition_id})-[r:PRESENTS_WITH]->(s:Symptom)
        RETURN {
            symptom_id: s.symptom_id,
            symptom_name: s.name,
            severity: s.severity,
            relationship_type: r.type,
            description: s.description
        } as symptom
        """
        results = self.run_query(query, {"condition_id": condition_id})
        return [r["symptom"] for r in results]
    
    def get_condition_complications(self, condition_id: str) -> List[Dict]:
        """Get potential complications of a condition"""
        query = """
        MATCH (c1:Condition {condition_id: $condition_id})-[r:COMPOUNDS]->(c2:Condition)
        RETURN {
            complication_id: c2.condition_id,
            complication_name: c2.name,
            severity: c2.severity,
            relationship_type: r.type,
            description: c2.description
        } as complication
        """
        results = self.run_query(query, {"condition_id": condition_id})
        return [r["complication"] for r in results]
    
    def get_all_patients(self, limit: int = 100) -> List[Dict]:
        """Get all patients"""
        query = """
        MATCH (p:Patient)
        RETURN {
            patient_id: p.patient_id,
            name: p.name,
            age: p.age,
            gender: p.gender,
            blood_type: p.blood_type,
            admission_date: p.admission_date
        } as patient
        LIMIT $limit
        """
        results = self.run_query(query, {"limit": limit})
        return [r["patient"] for r in results]
    
    def get_all_conditions(self) -> List[Dict]:
        """Get all conditions"""
        query = """
        MATCH (c:Condition)
        RETURN {
            condition_id: c.condition_id,
            name: c.name,
            severity: c.severity,
            icd_code: c.icd_code,
            description: c.description
        } as condition
        """
        results = self.run_query(query)
        return [r["condition"] for r in results]
    
    def get_high_risk_patients(self) -> List[Dict]:
        """Get patients with critical conditions"""
        query = """
        MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition)
        WHERE c.severity = 'Critical'
        RETURN {
            patient_id: p.patient_id,
            patient_name: p.name,
            age: p.age,
            condition: c.name,
            severity: c.severity
        } as high_risk_patient
        """
        results = self.run_query(query)
        return [r["high_risk_patient"] for r in results]
    
    def get_patient_risk_profile(self, patient_id: str) -> Dict:
        """Get comprehensive risk profile for a patient"""
        query = """
        MATCH (p:Patient {patient_id: $patient_id})
        OPTIONAL MATCH (p)-[:HAS_CONDITION]->(c:Condition)
        RETURN {
            patient_id: p.patient_id,
            patient_name: p.name,
            age: p.age,
            conditions: collect(c.name),
            condition_severities: collect(c.severity),
            critical_conditions: [x IN collect(c.severity) WHERE x = 'Critical']
        } as risk_profile
        """
        results = self.run_query(query, {"patient_id": patient_id})
        return results[0]["risk_profile"] if results else {}


# Global instance
kg = None


def get_knowledge_graph() -> MedicalKnowledgeGraph:
    """Get or create knowledge graph instance"""
    global kg
    if kg is None:
        kg = MedicalKnowledgeGraph()
    return kg
