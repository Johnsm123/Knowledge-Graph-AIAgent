#!/usr/bin/env python3
"""
HEDIS Golden Reference Persona System - Standalone Mode
Runs the complete persona system without requiring Neo4j
"""

import json
from datetime import datetime
from pathlib import Path
from persona_generator import HEDISPersonaGenerator

def identify_care_gaps(patient, personas):
    """Simple care gap identification without full analyzer"""
    gaps = []
    
    # Find matching personas based on demographics
    matching_personas = []
    for persona in personas:
        # Get patient node from persona
        patient_node = None
        for node in persona.get('nodes', []):
            if node.get('type') == 'patient':
                patient_node = node
                break
        
        if patient_node:
            props = patient_node.get('properties', {})
            # Simple matching logic
            age_match = abs(props.get('age', 0) - patient['age']) <= 10
            gender_match = props.get('gender') == patient['gender']
            product_match = props.get('product_line') == patient['product_line']
            
            if age_match and gender_match and product_match:
                matching_personas.append(persona)
    
    # Check for gaps in matching personas
    for persona in matching_personas[:2]:  # Top 2 matches
        if persona.get('compliance_status') == 'non_compliant':
            for care_gap in persona.get('care_gaps', []):
                gaps.append({
                    'gap_type': care_gap.get('gap_type', 'unknown'),
                    'severity': care_gap.get('severity', 'medium'),
                    'recommended_action': care_gap.get('recommended_action', 'Review required'),
                    'timeline': care_gap.get('timeline', '30_days'),
                    'description': care_gap.get('description', 'Care gap identified')
                })
    
    return gaps

def run_standalone_demo():
    """Run the persona system in standalone mode with sample patient analysis"""
    
    print("\nHEDIS GOLDEN REFERENCE PERSONA SYSTEM - STANDALONE MODE")
    print("="*70)
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"Base directory: {Path.cwd()}")
    print("="*70)
    
    # Step 1: Generate personas (already done)
    print("STEP 1: LOADING EXISTING PERSONAS")
    print("="*70)
    
    personas_by_measure = {}
    persona_files = [
        "generated_personas/BCS_personas.json",
        "generated_personas/COL_personas.json", 
        "generated_personas/CCS_personas.json",
        "generated_personas/CDC-HbA1c_personas.json"
    ]
    
    total_personas = 0
    for file in persona_files:
        if Path(file).exists():
            with open(file, 'r') as f:
                data = json.load(f)
                measure = file.replace("generated_personas/", "").replace("_personas.json", "")
                personas_by_measure[measure] = data['personas']
                total_personas += len(data['personas'])
                print(f"Loaded {len(data['personas'])} personas for {measure}")
    
    print(f"\nTotal personas loaded: {total_personas}")
    
    # Step 2: Demonstrate care gap analysis
    print("\n" + "="*70)
    print("STEP 2: CARE GAP ANALYSIS DEMONSTRATION")
    print("="*70)
    
    # Sample patients for testing
    sample_patients = [
        {
            "patient_id": "P001",
            "age": 52,
            "gender": "Female",
            "product_line": "Commercial",
            "last_mammogram": None,
            "medical_history": ["No significant history"],
            "exclusions": []
        },
        {
            "patient_id": "P002", 
            "age": 58,
            "gender": "Male",
            "product_line": "Medicare",
            "last_colonoscopy": "2020-03-15",
            "medical_history": ["Hypertension"],
            "exclusions": []
        },
        {
            "patient_id": "P003",
            "age": 28,
            "gender": "Female", 
            "product_line": "Commercial",
            "last_pap_smear": "2023-01-10",
            "medical_history": ["No significant history"],
            "exclusions": []
        },
        {
            "patient_id": "P004",
            "age": 45,
            "gender": "Male",
            "product_line": "Commercial", 
            "last_hba1c": None,
            "medical_history": ["Type 2 Diabetes"],
            "exclusions": []
        }
    ]
    
    print(f"Analyzing {len(sample_patients)} sample patients...")
    
    # Analyze each patient
    for patient in sample_patients:
        print(f"\n--- PATIENT {patient['patient_id']} ---")
        print(f"Age: {patient['age']}, Gender: {patient['gender']}, Product: {patient['product_line']}")
        
        # Find applicable measures based on patient demographics
        applicable_measures = []
        
        # BCS: Women 50-74
        if patient['gender'] == 'Female' and 50 <= patient['age'] <= 74:
            applicable_measures.append('BCS')
            
        # COL: Adults 50-75  
        if 50 <= patient['age'] <= 75:
            applicable_measures.append('COL')
            
        # CCS: Women 21-64
        if patient['gender'] == 'Female' and 21 <= patient['age'] <= 64:
            applicable_measures.append('CCS')
            
        # CDC-HbA1c: Adults 18-75 with diabetes
        if 18 <= patient['age'] <= 75 and any('diabetes' in h.lower() for h in patient.get('medical_history', [])):
            applicable_measures.append('CDC-HbA1c')
        
        print(f"Applicable measures: {applicable_measures}")
        
        # Analyze care gaps for each applicable measure
        for measure in applicable_measures:
            if measure in personas_by_measure:
                gaps = identify_care_gaps(patient, personas_by_measure[measure])
                
                if gaps:
                    print(f"\n  {measure} Care Gaps Found:")
                    for gap in gaps[:2]:  # Show top 2 gaps
                        print(f"    • {gap['gap_type']} (Severity: {gap['severity']})")
                        print(f"      Action: {gap['recommended_action']}")
                        print(f"      Timeline: {gap['timeline']}")
                else:
                    print(f"  {measure}: No care gaps identified")
    
    # Step 3: Generate summary report
    print("\n" + "="*70)
    print("STEP 3: SYSTEM SUMMARY REPORT")
    print("="*70)
    
    # Count personas by compliance status
    compliance_counts = {"compliant": 0, "non_compliant": 0, "excluded": 0}
    measure_counts = {}
    
    for measure, personas in personas_by_measure.items():
        measure_counts[measure] = len(personas)
        for persona in personas:
            status = persona.get('compliance_status', 'unknown')
            if status in compliance_counts:
                compliance_counts[status] += 1
    
    print("Persona Generation Summary:")
    for measure, count in measure_counts.items():
        print(f"  {measure}: {count} personas")
    
    print(f"\nCompliance Distribution:")
    for status, count in compliance_counts.items():
        print(f"  {status.replace('_', ' ').title()}: {count} personas")
    
    print(f"\nTotal Personas: {total_personas}")
    print(f"Measures Covered: {len(measure_counts)}")
    print(f"Sample Patients Analyzed: {len(sample_patients)}")
    
    print("\n" + "="*70)
    print("STANDALONE DEMO COMPLETE!")
    print("="*70)
    print("To use Neo4j integration:")
    print("1. Run: python setup_neo4j.py")
    print("2. Then run: python run_system.py")
    print("="*70)

if __name__ == "__main__":
    run_standalone_demo()