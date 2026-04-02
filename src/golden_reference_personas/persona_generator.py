"""
HEDIS Golden Reference Persona Generator
Creates comprehensive personas for all HEDIS measures with nodes and relationships
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import sys
import os

# Add parent directory to path to import hedis_golden_reference
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hedis_golden_reference import HEDIS_MEASURES

@dataclass
class PersonaNode:
    """Represents a node in the persona knowledge graph"""
    id: str
    type: str  # 'patient', 'condition', 'procedure', 'medication', 'exclusion', 'care_gap'
    properties: Dict[str, Any]
    created_at: str = datetime.now().isoformat()

@dataclass
class PersonaRelationship:
    """Represents a relationship between nodes"""
    id: str
    source_id: str
    target_id: str
    relationship_type: str  # 'HAS_CONDITION', 'REQUIRES_PROCEDURE', 'EXCLUDED_BY', etc.
    properties: Dict[str, Any]
    created_at: str = datetime.now().isoformat()

@dataclass
class PersonaProfile:
    """Complete persona profile with all nodes and relationships"""
    persona_id: str
    measure_id: str
    measure_name: str
    nodes: List[PersonaNode]
    relationships: List[PersonaRelationship]
    care_gaps: List[Dict[str, Any]]
    compliance_status: str  # 'compliant', 'non_compliant', 'excluded'
    created_at: str = datetime.now().isoformat()

class HEDISPersonaGenerator:
    """Generates comprehensive personas for HEDIS measures"""
    
    def __init__(self):
        self.personas = []
        self.age_groups = [
            (18, 30), (31, 45), (46, 55), (56, 65), (66, 75), (76, 85)
        ]
        self.genders = ['Male', 'Female', 'Non-binary']
        self.product_lines = ['Commercial', 'Medicare', 'Medicaid']
        
    def generate_all_personas(self) -> List[PersonaProfile]:
        """Generate personas for all HEDIS measures"""
        all_personas = []
        
        for measure_id, measure_data in HEDIS_MEASURES.items():
            print(f"Generating personas for {measure_id}: {measure_data['name']}")
            measure_personas = self.generate_measure_personas(measure_id, measure_data)
            all_personas.extend(measure_personas)
            
        return all_personas
    
    def generate_measure_personas(self, measure_id: str, measure_data: Dict) -> List[PersonaProfile]:
        """Generate personas for a specific HEDIS measure"""
        personas = []
        
        # Generate different persona variations
        variations = self._get_persona_variations(measure_data)
        
        for variation in variations:
            persona = self._create_persona_profile(measure_id, measure_data, variation)
            personas.append(persona)
            
        return personas
    
    def _get_persona_variations(self, measure_data: Dict) -> List[Dict]:
        """Get different persona variations based on measure requirements"""
        variations = []
        
        # Base variations for age and gender
        min_age = measure_data.get('min_age', 18)
        max_age = measure_data.get('max_age', 85)
        gender_req = measure_data.get('gender_requirement', 'Any')
        
        # Create age-appropriate variations
        relevant_age_groups = [
            (start, end) for start, end in self.age_groups 
            if not (end < min_age or start > max_age)
        ]
        
        genders = [gender_req] if gender_req != 'Any' else ['Male', 'Female']
        
        for age_start, age_end in relevant_age_groups:
            for gender in genders:
                for product_line in self.product_lines:
                    # Compliant persona
                    variations.append({
                        'age_range': (max(age_start, min_age), min(age_end, max_age)),
                        'gender': gender,
                        'product_line': product_line,
                        'compliance_status': 'compliant',
                        'has_exclusions': False
                    })
                    
                    # Non-compliant persona
                    variations.append({
                        'age_range': (max(age_start, min_age), min(age_end, max_age)),
                        'gender': gender,
                        'product_line': product_line,
                        'compliance_status': 'non_compliant',
                        'has_exclusions': False
                    })
                    
                    # Excluded persona (if exclusions exist)
                    if measure_data.get('exclusions', {}).get('required'):
                        variations.append({
                            'age_range': (max(age_start, min_age), min(age_end, max_age)),
                            'gender': gender,
                            'product_line': product_line,
                            'compliance_status': 'excluded',
                            'has_exclusions': True
                        })
        
        return variations
    
    def _create_persona_profile(self, measure_id: str, measure_data: Dict, variation: Dict) -> PersonaProfile:
        """Create a complete persona profile"""
        persona_id = str(uuid.uuid4())
        nodes = []
        relationships = []
        care_gaps = []
        
        # Create patient node
        patient_node = self._create_patient_node(persona_id, variation)
        nodes.append(patient_node)
        
        # Create condition nodes
        condition_nodes = self._create_condition_nodes(measure_data, variation)
        nodes.extend(condition_nodes)
        
        # Create procedure nodes
        procedure_nodes = self._create_procedure_nodes(measure_data, variation)
        nodes.extend(procedure_nodes)
        
        # Create medication nodes
        medication_nodes = self._create_medication_nodes(measure_data, variation)
        nodes.extend(medication_nodes)
        
        # Create exclusion nodes if applicable
        if variation['has_exclusions']:
            exclusion_nodes = self._create_exclusion_nodes(measure_data, variation)
            nodes.extend(exclusion_nodes)
        
        # Create relationships
        relationships = self._create_relationships(patient_node, nodes, measure_data, variation)
        
        # Identify care gaps
        if variation['compliance_status'] == 'non_compliant':
            care_gaps = self._identify_care_gaps(measure_data, variation)
        
        return PersonaProfile(
            persona_id=persona_id,
            measure_id=measure_id,
            measure_name=measure_data['name'],
            nodes=nodes,
            relationships=relationships,
            care_gaps=care_gaps,
            compliance_status=variation['compliance_status']
        )
    
    def _create_patient_node(self, persona_id: str, variation: Dict) -> PersonaNode:
        """Create patient node with demographics"""
        age_start, age_end = variation['age_range']
        age = (age_start + age_end) // 2  # Use middle age
        
        return PersonaNode(
            id=f"patient_{persona_id}",
            type="patient",
            properties={
                "persona_id": persona_id,
                "age": age,
                "gender": variation['gender'],
                "product_line": variation['product_line'],
                "enrollment_status": "active",
                "continuous_enrollment": True
            }
        )
    
    def _create_condition_nodes(self, measure_data: Dict, variation: Dict) -> List[PersonaNode]:
        """Create condition nodes based on measure requirements"""
        nodes = []
        
        # Add primary condition if specified
        if 'diagnosis_requirement' in measure_data:
            condition_node = PersonaNode(
                id=str(uuid.uuid4()),
                type="condition",
                properties={
                    "condition_name": measure_data['diagnosis_requirement'],
                    "icd10_codes": measure_data.get('codes', {}).get('diabetes_icd10', []),
                    "diagnosis_date": (datetime.now() - timedelta(days=365)).isoformat(),
                    "active": True
                }
            )
            nodes.append(condition_node)
        
        # Add age-related conditions
        age = (variation['age_range'][0] + variation['age_range'][1]) // 2
        if age >= 65:
            # Add common geriatric conditions
            geriatric_conditions = [
                {"name": "Hypertension", "icd10": "I10"},
                {"name": "Hyperlipidemia", "icd10": "E78.5"}
            ]
            
            for condition in geriatric_conditions:
                condition_node = PersonaNode(
                    id=str(uuid.uuid4()),
                    type="condition",
                    properties={
                        "condition_name": condition["name"],
                        "icd10_codes": [condition["icd10"]],
                        "diagnosis_date": (datetime.now() - timedelta(days=730)).isoformat(),
                        "active": True
                    }
                )
                nodes.append(condition_node)
        
        return nodes
    
    def _create_procedure_nodes(self, measure_data: Dict, variation: Dict) -> List[PersonaNode]:
        """Create procedure nodes based on compliance status"""
        nodes = []
        
        if variation['compliance_status'] == 'compliant':
            # Add required procedures
            codes = measure_data.get('codes', {})
            
            for code_type, code_list in codes.items():
                if 'cpt' in code_type.lower() and code_list:
                    procedure_node = PersonaNode(
                        id=str(uuid.uuid4()),
                        type="procedure",
                        properties={
                            "procedure_type": code_type,
                            "cpt_codes": code_list[:3],  # Take first 3 codes as examples
                            "procedure_date": (datetime.now() - timedelta(days=180)).isoformat(),
                            "completed": True,
                            "result": "normal" if "screening" in measure_data['name'].lower() else "completed"
                        }
                    )
                    nodes.append(procedure_node)
        
        return nodes
    
    def _create_medication_nodes(self, measure_data: Dict, variation: Dict) -> List[PersonaNode]:
        """Create medication nodes if applicable"""
        nodes = []
        
        # Check if measure involves medications
        if 'medication' in measure_data.get('name', '').lower() or 'adherence' in measure_data.get('name', '').lower():
            medication_node = PersonaNode(
                id=str(uuid.uuid4()),
                type="medication",
                properties={
                    "medication_class": "diabetes_medications" if "diabetes" in measure_data['name'].lower() else "generic_medication",
                    "prescribed_date": (datetime.now() - timedelta(days=90)).isoformat(),
                    "adherence_rate": 0.85 if variation['compliance_status'] == 'compliant' else 0.45,
                    "active": True
                }
            )
            nodes.append(medication_node)
        
        return nodes
    
    def _create_exclusion_nodes(self, measure_data: Dict, variation: Dict) -> List[PersonaNode]:
        """Create exclusion nodes"""
        nodes = []
        
        exclusions = measure_data.get('exclusions', {}).get('required', [])
        if exclusions:
            # Take first exclusion as example
            exclusion = exclusions[0]
            exclusion_node = PersonaNode(
                id=str(uuid.uuid4()),
                type="exclusion",
                properties={
                    "exclusion_type": exclusion.get('type', 'unknown'),
                    "exclusion_description": exclusion.get('description', ''),
                    "icd10_codes": exclusion.get('icd10', []),
                    "cpt_codes": exclusion.get('cpt', []),
                    "exclusion_date": (datetime.now() - timedelta(days=365)).isoformat(),
                    "active": True
                }
            )
            nodes.append(exclusion_node)
        
        return nodes
    
    def _create_relationships(self, patient_node: PersonaNode, all_nodes: List[PersonaNode], 
                           measure_data: Dict, variation: Dict) -> List[PersonaRelationship]:
        """Create relationships between nodes"""
        relationships = []
        
        for node in all_nodes:
            if node.id != patient_node.id:
                rel_type = self._get_relationship_type(node.type)
                relationship = PersonaRelationship(
                    id=str(uuid.uuid4()),
                    source_id=patient_node.id,
                    target_id=node.id,
                    relationship_type=rel_type,
                    properties={
                        "strength": "strong",
                        "relevance": "high"
                    }
                )
                relationships.append(relationship)
        
        return relationships
    
    def _get_relationship_type(self, node_type: str) -> str:
        """Get appropriate relationship type based on node type"""
        relationship_map = {
            "condition": "HAS_CONDITION",
            "procedure": "HAD_PROCEDURE",
            "medication": "PRESCRIBED_MEDICATION",
            "exclusion": "EXCLUDED_BY"
        }
        return relationship_map.get(node_type, "RELATED_TO")
    
    def _identify_care_gaps(self, measure_data: Dict, variation: Dict) -> List[Dict[str, Any]]:
        """Identify care gaps for non-compliant personas"""
        care_gaps = []
        
        # Primary care gap - missing required procedure/screening
        primary_gap = {
            "gap_id": str(uuid.uuid4()),
            "gap_type": "missing_procedure",
            "measure_id": measure_data.get('measure_id', ''),
            "description": f"Missing required {measure_data['name']} procedure",
            "severity": "high",
            "recommended_action": f"Schedule {measure_data['name']} within next 30 days",
            "codes_needed": list(measure_data.get('codes', {}).keys())[:3],
            "timeline": "30_days"
        }
        care_gaps.append(primary_gap)
        
        # Secondary gaps based on age and conditions
        age = (variation['age_range'][0] + variation['age_range'][1]) // 2
        if age >= 65:
            secondary_gap = {
                "gap_id": str(uuid.uuid4()),
                "gap_type": "preventive_care",
                "description": "Annual wellness visit recommended for Medicare beneficiary",
                "severity": "medium",
                "recommended_action": "Schedule annual wellness visit",
                "timeline": "60_days"
            }
            care_gaps.append(secondary_gap)
        
        return care_gaps
    
    def save_personas_to_files(self, personas: List[PersonaProfile], output_dir: str):
        """Save personas to individual JSON files"""
        os.makedirs(output_dir, exist_ok=True)
        
        # Group personas by measure
        measure_groups = {}
        for persona in personas:
            measure_id = persona.measure_id
            if measure_id not in measure_groups:
                measure_groups[measure_id] = []
            measure_groups[measure_id].append(persona)
        
        # Save each measure group to a separate file
        for measure_id, measure_personas in measure_groups.items():
            filename = f"{measure_id}_personas.json"
            filepath = os.path.join(output_dir, filename)
            
            # Convert personas to dict format
            personas_data = []
            for persona in measure_personas:
                persona_dict = asdict(persona)
                personas_data.append(persona_dict)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    "measure_id": measure_id,
                    "total_personas": len(personas_data),
                    "generated_at": datetime.now().isoformat(),
                    "personas": personas_data
                }, f, indent=2, ensure_ascii=False)
            
            print(f"Saved {len(measure_personas)} personas for {measure_id} to {filename}")
    
    def generate_summary_report(self, personas: List[PersonaProfile]) -> Dict[str, Any]:
        """Generate summary report of all personas"""
        summary = {
            "total_personas": len(personas),
            "generated_at": datetime.now().isoformat(),
            "measures_covered": len(set(p.measure_id for p in personas)),
            "compliance_breakdown": {
                "compliant": len([p for p in personas if p.compliance_status == 'compliant']),
                "non_compliant": len([p for p in personas if p.compliance_status == 'non_compliant']),
                "excluded": len([p for p in personas if p.compliance_status == 'excluded'])
            },
            "measure_breakdown": {}
        }
        
        # Breakdown by measure
        for persona in personas:
            measure_id = persona.measure_id
            if measure_id not in summary["measure_breakdown"]:
                summary["measure_breakdown"][measure_id] = {
                    "measure_name": persona.measure_name,
                    "total_personas": 0,
                    "compliant": 0,
                    "non_compliant": 0,
                    "excluded": 0
                }
            
            summary["measure_breakdown"][measure_id]["total_personas"] += 1
            summary["measure_breakdown"][measure_id][persona.compliance_status] += 1
        
        return summary

def main():
    """Main function to generate all personas"""
    print("Starting HEDIS Golden Reference Persona Generation...")
    
    generator = HEDISPersonaGenerator()
    
    # Generate all personas
    all_personas = generator.generate_all_personas()
    
    # Save personas to files
    output_dir = os.path.join(os.path.dirname(__file__), "generated_personas")
    generator.save_personas_to_files(all_personas, output_dir)
    
    # Generate and save summary report
    summary = generator.generate_summary_report(all_personas)
    summary_path = os.path.join(output_dir, "personas_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"\nGeneration Complete!")
    print(f"Total personas generated: {summary['total_personas']}")
    print(f"Measures covered: {summary['measures_covered']}")
    print(f"Files saved to: {output_dir}")
    
    return all_personas

if __name__ == "__main__":
    main()