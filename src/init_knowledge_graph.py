"""
Initialize medical knowledge graph with comprehensive hospital data
Loads 50+ patients, conditions, medications, symptoms, treatments, lab tests
and all relationships into Neo4j Aura
"""
import logging
from src.neo4j_connection import get_knowledge_graph
from src.hospital_data import HOSPITAL_DATA

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def initialize_knowledge_graph():
    """Initialize Neo4j knowledge graph with comprehensive hospital data"""
    
    kg = get_knowledge_graph()
    
    try:
        logger.info("Starting knowledge graph initialization...")
        
        # 1. Create all patients
        logger.info("Creating patients...")
        for patient in HOSPITAL_DATA["patients"]:
            kg.create_patient(
                patient_id=patient["patient_id"],
                name=patient["name"],
                age=patient["age"],
                gender=patient["gender"],
                blood_type=patient.get("blood_type", "O+"),
                admission_date=patient.get("admission_date", "")
            )
        logger.info(f"Created {len(HOSPITAL_DATA['patients'])} patients")
        
        # 2. Create all conditions
        logger.info("Creating conditions...")
        for condition in HOSPITAL_DATA["conditions"]:
            kg.create_medical_condition(
                condition_id=condition["condition_id"],
                name=condition["name"],
                severity=condition["severity"],
                icd_code=condition.get("icd_code", ""),
                description=condition["description"]
            )
        logger.info(f"Created {len(HOSPITAL_DATA['conditions'])} conditions")
        
        # 3. Create all medications
        logger.info("Creating medications...")
        for medication in HOSPITAL_DATA["medications"]:
            kg.create_medication(
                medication_id=medication["medication_id"],
                name=medication["name"],
                dosage=medication["dosage"],
                frequency=medication["frequency"],
                category=medication["category"]
            )
        logger.info(f"Created {len(HOSPITAL_DATA['medications'])} medications")
        
        # 4. Create all symptoms
        logger.info("Creating symptoms...")
        for symptom in HOSPITAL_DATA["symptoms"]:
            kg.create_symptom(
                symptom_id=symptom["symptom_id"],
                name=symptom["name"],
                severity=symptom["severity"],
                description=symptom["description"]
            )
        logger.info(f"Created {len(HOSPITAL_DATA['symptoms'])} symptoms")
        
        # 5. Create all lab tests
        logger.info("Creating lab tests...")
        for test in HOSPITAL_DATA["lab_tests"]:
            kg.create_lab_test(
                test_id=test["test_id"],
                name=test["name"],
                code=test["code"],
                normal_range=test["normal_range"],
                unit=test["unit"]
            )
        logger.info(f"Created {len(HOSPITAL_DATA['lab_tests'])} lab tests")
        
        # 6. Create all treatments
        logger.info("Creating treatments...")
        for treatment in HOSPITAL_DATA["treatments"]:
            kg.create_treatment(
                treatment_id=treatment["treatment_id"],
                name=treatment["name"],
                treatment_type=treatment["type"],
                duration_days=treatment["duration_days"],
                description=treatment["description"]
            )
        logger.info(f"Created {len(HOSPITAL_DATA['treatments'])} treatments")
        
        # 7. Create patient-condition relationships
        logger.info("Creating patient-condition relationships...")
        for patient_id, condition_id, diagnosed_date, status in HOSPITAL_DATA["patient_condition_relationships"]:
            kg.relate_patient_to_condition(
                patient_id=patient_id,
                condition_id=condition_id,
                diagnosed_date=diagnosed_date,
                status=status
            )
        logger.info(f"Created {len(HOSPITAL_DATA['patient_condition_relationships'])} patient-condition relationships")
        
        # 8. Create condition-symptom relationships
        logger.info("Creating condition-symptom relationships...")
        for condition_id, symptom_id, relationship_type in HOSPITAL_DATA["condition_symptom_relationships"]:
            kg.relate_condition_to_symptom(
                condition_id=condition_id,
                symptom_id=symptom_id,
                relationship_type=relationship_type
            )
        logger.info(f"Created {len(HOSPITAL_DATA['condition_symptom_relationships'])} condition-symptom relationships")
        
        # 9. Create medication-condition relationships
        logger.info("Creating medication-condition relationships...")
        for medication_id, condition_id, relationship_type in HOSPITAL_DATA["medication_condition_relationships"]:
            kg.relate_medication_to_condition(
                medication_id=medication_id,
                condition_id=condition_id,
                relationship_type=relationship_type
            )
        logger.info(f"Created {len(HOSPITAL_DATA['medication_condition_relationships'])} medication-condition relationships")
        
        # 10. Create condition-complication relationships
        logger.info("Creating condition-complication relationships...")
        for condition_id1, condition_id2, relationship_type in HOSPITAL_DATA["condition_complication_relationships"]:
            kg.relate_condition_complications(
                condition_id1=condition_id1,
                condition_id2=condition_id2,
                relationship_type=relationship_type
            )
        logger.info(f"Created {len(HOSPITAL_DATA['condition_complication_relationships'])} condition-complication relationships")
        
        logger.info("✓ Knowledge graph initialization completed successfully!")
        logger.info(f"Total nodes created:")
        logger.info(f"  - Patients: {len(HOSPITAL_DATA['patients'])}")
        logger.info(f"  - Conditions: {len(HOSPITAL_DATA['conditions'])}")
        logger.info(f"  - Medications: {len(HOSPITAL_DATA['medications'])}")
        logger.info(f"  - Symptoms: {len(HOSPITAL_DATA['symptoms'])}")
        logger.info(f"  - Lab Tests: {len(HOSPITAL_DATA['lab_tests'])}")
        logger.info(f"  - Treatments: {len(HOSPITAL_DATA['treatments'])}")
        logger.info(f"Total relationships created:")
        logger.info(f"  - Patient-Condition: {len(HOSPITAL_DATA['patient_condition_relationships'])}")
        logger.info(f"  - Condition-Symptom: {len(HOSPITAL_DATA['condition_symptom_relationships'])}")
        logger.info(f"  - Medication-Condition: {len(HOSPITAL_DATA['medication_condition_relationships'])}")
        logger.info(f"  - Condition-Complication: {len(HOSPITAL_DATA['condition_complication_relationships'])}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize knowledge graph: {str(e)}")
        return False
    
    finally:
        kg.close()


if __name__ == "__main__":
    success = initialize_knowledge_graph()
    if success:
        logger.info("Knowledge graph is ready for use!")
    else:
        logger.error("Knowledge graph initialization failed!")
