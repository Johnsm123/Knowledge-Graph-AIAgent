"""
Medical Knowledge Graph Schema
Defines all nodes and relationships for the medical knowledge graph
"""
from typing import Optional

# Node Types
PATIENT = "Patient"
CONDITION = "Condition"
MEDICATION = "Medication"
SYMPTOM = "Symptom"
LAB_TEST = "LabTest"
TREATMENT = "Treatment"
SIDE_EFFECT = "SideEffect"
RISK_FACTOR = "RiskFactor"
PREVENTION = "Prevention"

# Relationship Types
HAS_CONDITION = "HAS_CONDITION"
HAS_SYMPTOM = "HAS_SYMPTOM"
TAKES_MEDICATION = "TAKES_MEDICATION"
UNDERWENT_TEST = "UNDERWENT_TEST"
UNDERWENT_TREATMENT = "UNDERWENT_TREATMENT"
HAS_RISK_FACTOR = "HAS_RISK_FACTOR"
RELATED_TO = "RELATED_TO"
CAUSES = "CAUSES"
CAUSED_BY = "CAUSED_BY"
TREATS = "TREATS"
CAUSES_SIDE_EFFECT = "CAUSES_SIDE_EFFECT"
PREVENTED_BY = "PREVENTED_BY"
COMPOUNDS = "COMPOUNDS"
CONTRAINDICATES = "CONTRAINDICATES"

# Schema Constraints
SCHEMA_CONSTRAINTS = """
// Create uniqueness constraints
CREATE CONSTRAINT patient_id IF NOT EXISTS FOR (p:Patient) REQUIRE p.patient_id IS UNIQUE;
CREATE CONSTRAINT condition_id IF NOT EXISTS FOR (c:Condition) REQUIRE c.condition_id IS UNIQUE;
CREATE CONSTRAINT medication_id IF NOT EXISTS FOR (m:Medication) REQUIRE m.medication_id IS UNIQUE;
CREATE CONSTRAINT symptom_id IF NOT EXISTS FOR (s:Symptom) REQUIRE s.symptom_id IS UNIQUE;
CREATE CONSTRAINT lab_test_id IF NOT EXISTS FOR (l:LabTest) REQUIRE l.lab_test_id IS UNIQUE;
CREATE CONSTRAINT treatment_id IF NOT EXISTS FOR (t:Treatment) REQUIRE t.treatment_id IS UNIQUE;
"""

# Create Indexes
SCHEMA_INDEXES = """
// Create indexes for better query performance
CREATE INDEX patient_name IF NOT EXISTS FOR (p:Patient) ON (p.name);
CREATE INDEX condition_name IF NOT EXISTS FOR (c:Condition) ON (c.name);
CREATE INDEX condition_severity IF NOT EXISTS FOR (c:Condition) ON (c.severity);
CREATE INDEX patient_age IF NOT EXISTS FOR (p:Patient) ON (p.age);
CREATE INDEX medication_name IF NOT EXISTS FOR (m:Medication) ON (m.name);
CREATE INDEX symptom_name IF NOT EXISTS FOR (s:Symptom) ON (s.name);
"""

# Sample Data Initialization
INITIAL_DATA = {
    "conditions": [
        {
            "condition_id": "COND001",
            "name": "Type 2 Diabetes",
            "severity": "High",
            "description": "Chronic metabolic disorder affecting blood glucose levels"
        },
        {
            "condition_id": "COND002",
            "name": "Hypertension",
            "severity": "High",
            "description": "Elevated blood pressure condition"
        },
        {
            "condition_id": "COND003",
            "name": "Asthma",
            "severity": "Medium",
            "description": "Chronic respiratory disorder"
        },
        {
            "condition_id": "COND004",
            "name": "Coronary Artery Disease",
            "severity": "Critical",
            "description": "Narrowing of arteries due to plaque buildup"
        }
    ],
    "symptoms": [
        {
            "symptom_id": "SYM001",
            "name": "Fatigue",
            "description": "Persistent tiredness and lack of energy"
        },
        {
            "symptom_id": "SYM002",
            "name": "Chest Pain",
            "description": "Discomfort or pain in the chest area"
        },
        {
            "symptom_id": "SYM003",
            "name": "Shortness of Breath",
            "description": "Difficulty breathing or feeling out of breath"
        },
        {
            "symptom_id": "SYM004",
            "name": "Frequent Urination",
            "description": "Need to urinate more frequently than normal"
        }
    ],
    "medications": [
        {
            "medication_id": "MED001",
            "name": "Metformin",
            "dosage": "500mg",
            "description": "Primary treatment for Type 2 Diabetes"
        },
        {
            "medication_id": "MED002",
            "name": "Lisinopril",
            "dosage": "10mg",
            "description": "ACE inhibitor for hypertension"
        },
        {
            "medication_id": "MED003",
            "name": "Albuterol",
            "dosage": "100mcg",
            "description": "Bronchodilator for asthma relief"
        }
    ],
    "risk_factors": [
        {
            "risk_factor_id": "RF001",
            "name": "Obesity",
            "description": "Excess body weight increases disease risk"
        },
        {
            "risk_factor_id": "RF002",
            "name": "Smoking",
            "description": "Active or passive smoking increases multiple health risks"
        },
        {
            "risk_factor_id": "RF003",
            "name": "Sedentary Lifestyle",
            "description": "Lack of physical activity increases disease risk"
        }
    ],
    "preventions": [
        {
            "prevention_id": "PRV001",
            "name": "Regular Exercise",
            "description": "150 minutes of moderate activity per week"
        },
        {
            "prevention_id": "PRV002",
            "name": "Healthy Diet",
            "description": "Balanced nutrition with reduced sodium and sugar"
        },
        {
            "prevention_id": "PRV003",
            "name": "Regular Health Checkups",
            "description": "Annual or bi-annual medical examinations"
        }
    ]
}

# Cypher Queries for Common Operations
COMMON_QUERIES = {
    "get_patient_risk_profile": """
    MATCH (p:Patient {patient_id: $patient_id})
    OPTIONAL MATCH (p)-[:HAS_RISK_FACTOR]->(rf:RiskFactor)
    OPTIONAL MATCH (p)-[:HAS_CONDITION]->(c:Condition)
    RETURN {
        patient: p,
        risk_factors: collect(rf.name),
        conditions: collect(c.name),
        condition_severities: collect(c.severity)
    }
    """,
    
    "get_patient_medications": """
    MATCH (p:Patient {patient_id: $patient_id})-[r:TAKES_MEDICATION]->(m:Medication)
    RETURN {
        medication: m.name,
        dosage: m.dosage,
        start_date: r.start_date,
        status: r.status
    }
    ORDER BY r.start_date DESC
    """,
    
    "find_condition_complications": """
    MATCH (c1:Condition {condition_id: $condition_id})-[r:COMPOUNDS]->(c2:Condition)
    RETURN {
        complications: c2.name,
        severity: c2.severity,
        description: c2.description
    }
    """,
    
    "patient_disease_progression": """
    MATCH (p:Patient {patient_id: $patient_id})-[r:HAS_CONDITION]->(c:Condition)
    RETURN {
        condition: c.name,
        diagnosed_date: r.diagnosed_date,
        status: r.status,
        severity: c.severity
    }
    ORDER BY r.diagnosed_date ASC
    """,
    
    "similar_patients_outcomes": """
    MATCH (p1:Patient {patient_id: $patient_id})-[:HAS_CONDITION]->(c:Condition)<-[:HAS_CONDITION]-(p2:Patient)
    WHERE p1.patient_id <> p2.patient_id
    RETURN DISTINCT {
        patient_id: p2.patient_id,
        shared_conditions: collect(c.name),
        similar_age: abs(p1.age - p2.age) < 5
    }
    LIMIT 10
    """
}
