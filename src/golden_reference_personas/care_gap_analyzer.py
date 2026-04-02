"""
Care Gap Analyzer
Compares patient data against golden reference personas to identify care gaps
"""

import json
import os
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hedis_golden_reference import HEDIS_MEASURES

@dataclass
class CareGapFinding:
    """Represents a care gap finding"""
    gap_id: str
    patient_id: str
    measure_id: str
    measure_name: str
    gap_type: str
    description: str
    severity: str  # 'critical', 'high', 'medium', 'low'
    recommended_action: str
    timeline: str
    codes_needed: List[str]
    persona_match_score: float
    evidence: Dict[str, Any]

@dataclass
class PatientData:
    """Patient data structure for comparison"""
    patient_id: str
    age: int
    gender: str
    product_line: str
    conditions: List[Dict[str, Any]]
    procedures: List[Dict[str, Any]]
    medications: List[Dict[str, Any]]
    exclusions: List[Dict[str, Any]]
    enrollment_data: Dict[str, Any]

class CareGapAnalyzer:
    """Analyzes care gaps by comparing patients against golden reference personas"""
    
    def __init__(self, personas_dir: str):
        self.personas_dir = personas_dir
        self.personas_cache = {}
        self.load_personas()
    
    def load_personas(self):
        """Load all personas from files"""
        print("Loading golden reference personas...")
        
        if not os.path.exists(self.personas_dir):
            print(f"Personas directory not found: {self.personas_dir}")
            return
        
        for filename in os.listdir(self.personas_dir):
            if filename.endswith('_personas.json'):
                measure_id = filename.replace('_personas.json', '')
                filepath = os.path.join(self.personas_dir, filename)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.personas_cache[measure_id] = data['personas']
                        print(f"Loaded {len(data['personas'])} personas for {measure_id}")
                except Exception as e:
                    print(f"Error loading {filename}: {e}")
        
        print(f"Total measures loaded: {len(self.personas_cache)}")
    
    def analyze_patient(self, patient_data: PatientData) -> List[CareGapFinding]:
        """Analyze a patient against all relevant personas to find care gaps"""
        all_gaps = []
        
        # Determine applicable measures based on patient demographics
        applicable_measures = self._get_applicable_measures(patient_data)
        
        for measure_id in applicable_measures:
            if measure_id in self.personas_cache:
                measure_gaps = self._analyze_patient_for_measure(patient_data, measure_id)
                all_gaps.extend(measure_gaps)
        
        # Sort gaps by severity and persona match score
        all_gaps.sort(key=lambda x: (
            self._severity_score(x.severity), 
            -x.persona_match_score
        ), reverse=True)
        
        return all_gaps
    
    def _get_applicable_measures(self, patient_data: PatientData) -> List[str]:
        """Determine which HEDIS measures apply to this patient"""
        applicable = []
        
        for measure_id, measure_info in HEDIS_MEASURES.items():
            if self._patient_eligible_for_measure(patient_data, measure_info):
                applicable.append(measure_id)
        
        return applicable
    
    def _patient_eligible_for_measure(self, patient_data: PatientData, measure_info: Dict) -> bool:
        """Check if patient is eligible for a specific measure"""
        # Age check
        min_age = measure_info.get('min_age', 0)
        max_age = measure_info.get('max_age', 150)
        if not (min_age <= patient_data.age <= max_age):
            return False
        
        # Gender check
        gender_req = measure_info.get('gender_requirement', 'Any')
        if gender_req != 'Any' and patient_data.gender != gender_req:
            return False
        
        # Product line check
        product_lines = measure_info.get('product_lines', [])
        if product_lines and patient_data.product_line not in product_lines:
            return False
        
        # Check for required diagnosis
        diagnosis_req = measure_info.get('diagnosis_requirement')
        if diagnosis_req:
            patient_conditions = [c.get('name', '').lower() for c in patient_data.conditions]
            if not any(diagnosis_req.lower() in condition for condition in patient_conditions):
                return False
        
        return True
    
    def _analyze_patient_for_measure(self, patient_data: PatientData, measure_id: str) -> List[CareGapFinding]:
        """Analyze patient for a specific measure"""
        gaps = []
        personas = self.personas_cache.get(measure_id, [])
        
        if not personas:
            return gaps
        
        # Find best matching personas
        best_matches = self._find_matching_personas(patient_data, personas)
        
        for persona, match_score in best_matches[:3]:  # Top 3 matches
            persona_gaps = self._compare_with_persona(patient_data, persona, match_score)
            gaps.extend(persona_gaps)
        
        # Remove duplicates and merge similar gaps
        gaps = self._deduplicate_gaps(gaps)
        
        return gaps
    
    def _find_matching_personas(self, patient_data: PatientData, personas: List[Dict]) -> List[Tuple[Dict, float]]:
        """Find personas that best match the patient"""
        matches = []
        
        for persona in personas:
            match_score = self._calculate_persona_match_score(patient_data, persona)
            if match_score > 0.5:  # Only consider good matches
                matches.append((persona, match_score))
        
        # Sort by match score
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches
    
    def _calculate_persona_match_score(self, patient_data: PatientData, persona: Dict) -> float:
        """Calculate how well a persona matches the patient"""
        score = 0.0
        total_factors = 0
        
        # Get patient node from persona
        patient_node = None
        for node in persona.get('nodes', []):
            if node.get('type') == 'patient':
                patient_node = node
                break
        
        if not patient_node:
            return 0.0
        
        patient_props = patient_node.get('properties', {})
        
        # Age similarity (weight: 0.3)
        persona_age = patient_props.get('age', 0)
        age_diff = abs(patient_data.age - persona_age)
        age_score = max(0, 1 - (age_diff / 20))  # 20-year tolerance
        score += age_score * 0.3
        total_factors += 0.3
        
        # Gender match (weight: 0.2)
        if patient_props.get('gender') == patient_data.gender:
            score += 0.2
        total_factors += 0.2
        
        # Product line match (weight: 0.2)
        if patient_props.get('product_line') == patient_data.product_line:
            score += 0.2
        total_factors += 0.2
        
        # Condition similarity (weight: 0.3)
        persona_conditions = [n for n in persona.get('nodes', []) if n.get('type') == 'condition']
        patient_condition_names = [c.get('name', '').lower() for c in patient_data.conditions]
        
        condition_matches = 0
        for p_condition in persona_conditions:
            condition_name = p_condition.get('properties', {}).get('condition_name', '').lower()
            if any(condition_name in p_name for p_name in patient_condition_names):
                condition_matches += 1
        
        if persona_conditions:
            condition_score = condition_matches / len(persona_conditions)
            score += condition_score * 0.3
        total_factors += 0.3
        
        return score / total_factors if total_factors > 0 else 0.0
    
    def _compare_with_persona(self, patient_data: PatientData, persona: Dict, match_score: float) -> List[CareGapFinding]:
        """Compare patient with persona to identify gaps"""
        gaps = []
        
        # If persona is compliant but patient might not be, check for gaps
        if persona.get('compliance_status') == 'compliant':
            gaps.extend(self._check_compliance_gaps(patient_data, persona, match_score))
        
        # If persona is excluded, check if patient should also be excluded
        if persona.get('compliance_status') == 'excluded':
            gaps.extend(self._check_exclusion_gaps(patient_data, persona, match_score))
        
        # Check for care gaps from persona
        persona_care_gaps = persona.get('care_gaps', [])
        for care_gap in persona_care_gaps:
            gap_finding = self._create_gap_finding_from_persona(
                patient_data, persona, care_gap, match_score
            )
            gaps.append(gap_finding)
        
        return gaps
    
    def _check_compliance_gaps(self, patient_data: PatientData, persona: Dict, match_score: float) -> List[CareGapFinding]:
        """Check if patient has compliance gaps compared to compliant persona"""
        gaps = []
        
        # Get required procedures from persona
        persona_procedures = [n for n in persona.get('nodes', []) if n.get('type') == 'procedure']
        patient_procedure_codes = []
        
        for proc in patient_data.procedures:
            patient_procedure_codes.extend(proc.get('cpt_codes', []))
            patient_procedure_codes.extend(proc.get('hcpcs_codes', []))
        
        # Check if patient has required procedures
        for p_procedure in persona_procedures:
            proc_props = p_procedure.get('properties', {})
            required_codes = proc_props.get('cpt_codes', [])
            
            # Check if patient has any of the required codes
            has_procedure = any(code in patient_procedure_codes for code in required_codes)
            
            if not has_procedure:
                gap = CareGapFinding(
                    gap_id=f"gap_{patient_data.patient_id}_{persona['measure_id']}_{p_procedure['id']}",
                    patient_id=patient_data.patient_id,
                    measure_id=persona['measure_id'],
                    measure_name=persona['measure_name'],
                    gap_type="missing_procedure",
                    description=f"Missing required procedure: {proc_props.get('procedure_type', 'Unknown')}",
                    severity="high",
                    recommended_action=f"Schedule {proc_props.get('procedure_type', 'procedure')} within 30 days",
                    timeline="30_days",
                    codes_needed=required_codes,
                    persona_match_score=match_score,
                    evidence={
                        "persona_procedure": proc_props,
                        "patient_procedures": patient_data.procedures,
                        "missing_codes": required_codes
                    }
                )
                gaps.append(gap)
        
        return gaps
    
    def _check_exclusion_gaps(self, patient_data: PatientData, persona: Dict, match_score: float) -> List[CareGapFinding]:
        """Check exclusion-related gaps"""
        gaps = []
        
        # Get exclusions from persona
        persona_exclusions = [n for n in persona.get('nodes', []) if n.get('type') == 'exclusion']
        
        for exclusion in persona_exclusions:
            excl_props = exclusion.get('properties', {})
            excl_type = excl_props.get('exclusion_type', '')
            
            # Check if patient has similar exclusion criteria
            patient_has_exclusion = self._patient_has_exclusion(patient_data, excl_props)
            
            if not patient_has_exclusion:
                gap = CareGapFinding(
                    gap_id=f"gap_{patient_data.patient_id}_{persona['measure_id']}_exclusion",
                    patient_id=patient_data.patient_id,
                    measure_id=persona['measure_id'],
                    measure_name=persona['measure_name'],
                    gap_type="potential_exclusion",
                    description=f"Patient may qualify for exclusion: {excl_type}",
                    severity="medium",
                    recommended_action=f"Review patient for {excl_type} exclusion criteria",
                    timeline="60_days",
                    codes_needed=excl_props.get('icd10_codes', []),
                    persona_match_score=match_score,
                    evidence={
                        "exclusion_criteria": excl_props,
                        "patient_conditions": patient_data.conditions
                    }
                )
                gaps.append(gap)
        
        return gaps
    
    def _patient_has_exclusion(self, patient_data: PatientData, exclusion_props: Dict) -> bool:
        """Check if patient has exclusion criteria"""
        excl_icd10_codes = exclusion_props.get('icd10_codes', [])
        excl_cpt_codes = exclusion_props.get('cpt_codes', [])
        
        # Check conditions
        for condition in patient_data.conditions:
            condition_codes = condition.get('icd10_codes', [])
            if any(code in excl_icd10_codes for code in condition_codes):
                return True
        
        # Check procedures
        for procedure in patient_data.procedures:
            proc_codes = procedure.get('cpt_codes', [])
            if any(code in excl_cpt_codes for code in proc_codes):
                return True
        
        # Check explicit exclusions
        for exclusion in patient_data.exclusions:
            if exclusion.get('type') == exclusion_props.get('exclusion_type'):
                return True
        
        return False
    
    def _create_gap_finding_from_persona(self, patient_data: PatientData, persona: Dict, 
                                       care_gap: Dict, match_score: float) -> CareGapFinding:
        """Create gap finding from persona care gap"""
        return CareGapFinding(
            gap_id=care_gap.get('gap_id', f"gap_{patient_data.patient_id}_{persona['measure_id']}"),
            patient_id=patient_data.patient_id,
            measure_id=persona['measure_id'],
            measure_name=persona['measure_name'],
            gap_type=care_gap.get('gap_type', 'unknown'),
            description=care_gap.get('description', ''),
            severity=care_gap.get('severity', 'medium'),
            recommended_action=care_gap.get('recommended_action', ''),
            timeline=care_gap.get('timeline', '30_days'),
            codes_needed=care_gap.get('codes_needed', []),
            persona_match_score=match_score,
            evidence={
                "persona_care_gap": care_gap,
                "persona_match_score": match_score
            }
        )
    
    def _deduplicate_gaps(self, gaps: List[CareGapFinding]) -> List[CareGapFinding]:
        """Remove duplicate gaps and merge similar ones"""
        unique_gaps = {}
        
        for gap in gaps:
            # Create key based on measure, gap type, and description
            key = f"{gap.measure_id}_{gap.gap_type}_{hash(gap.description)}"
            
            if key not in unique_gaps:
                unique_gaps[key] = gap
            else:
                # Keep the one with higher persona match score
                if gap.persona_match_score > unique_gaps[key].persona_match_score:
                    unique_gaps[key] = gap
        
        return list(unique_gaps.values())
    
    def _severity_score(self, severity: str) -> int:
        """Convert severity to numeric score for sorting"""
        severity_map = {
            'critical': 4,
            'high': 3,
            'medium': 2,
            'low': 1
        }
        return severity_map.get(severity.lower(), 0)
    
    def generate_care_gap_report(self, patient_data: PatientData, gaps: List[CareGapFinding]) -> Dict[str, Any]:
        """Generate comprehensive care gap report"""
        report = {
            "patient_id": patient_data.patient_id,
            "analysis_date": datetime.now().isoformat(),
            "patient_summary": {
                "age": patient_data.age,
                "gender": patient_data.gender,
                "product_line": patient_data.product_line,
                "total_conditions": len(patient_data.conditions),
                "total_procedures": len(patient_data.procedures),
                "total_medications": len(patient_data.medications)
            },
            "care_gaps_summary": {
                "total_gaps": len(gaps),
                "critical": len([g for g in gaps if g.severity == 'critical']),
                "high": len([g for g in gaps if g.severity == 'high']),
                "medium": len([g for g in gaps if g.severity == 'medium']),
                "low": len([g for g in gaps if g.severity == 'low'])
            },
            "gaps_by_measure": {},
            "priority_actions": [],
            "detailed_gaps": []
        }
        
        # Group gaps by measure
        for gap in gaps:
            measure_id = gap.measure_id
            if measure_id not in report["gaps_by_measure"]:
                report["gaps_by_measure"][measure_id] = {
                    "measure_name": gap.measure_name,
                    "gaps": []
                }
            report["gaps_by_measure"][measure_id]["gaps"].append({
                "gap_type": gap.gap_type,
                "severity": gap.severity,
                "description": gap.description,
                "recommended_action": gap.recommended_action,
                "timeline": gap.timeline
            })
        
        # Priority actions (critical and high severity)
        priority_gaps = [g for g in gaps if g.severity in ['critical', 'high']]
        for gap in priority_gaps[:5]:  # Top 5 priority actions
            report["priority_actions"].append({
                "action": gap.recommended_action,
                "timeline": gap.timeline,
                "measure": gap.measure_name,
                "severity": gap.severity
            })
        
        # Detailed gaps
        for gap in gaps:
            report["detailed_gaps"].append({
                "gap_id": gap.gap_id,
                "measure_id": gap.measure_id,
                "measure_name": gap.measure_name,
                "gap_type": gap.gap_type,
                "description": gap.description,
                "severity": gap.severity,
                "recommended_action": gap.recommended_action,
                "timeline": gap.timeline,
                "codes_needed": gap.codes_needed,
                "persona_match_score": gap.persona_match_score,
                "evidence": gap.evidence
            })
        
        return report

def create_sample_patient() -> PatientData:
    """Create a sample patient for testing"""
    return PatientData(
        patient_id="SAMPLE_001",
        age=55,
        gender="Female",
        product_line="Commercial",
        conditions=[
            {
                "name": "Type 2 Diabetes",
                "icd10_codes": ["E11.9"],
                "diagnosis_date": "2023-01-15",
                "active": True
            },
            {
                "name": "Hypertension",
                "icd10_codes": ["I10"],
                "diagnosis_date": "2022-06-10",
                "active": True
            }
        ],
        procedures=[
            {
                "name": "Office Visit",
                "cpt_codes": ["99213"],
                "procedure_date": "2024-11-01",
                "completed": True
            }
        ],
        medications=[
            {
                "name": "Metformin",
                "ndc_codes": ["00093-7267-01"],
                "prescribed_date": "2024-01-15",
                "active": True
            }
        ],
        exclusions=[],
        enrollment_data={
            "enrollment_start": "2024-01-01",
            "continuous_enrollment": True,
            "product_line": "Commercial"
        }
    )

def main():
    """Main function for testing the care gap analyzer"""
    # Path to generated personas
    personas_dir = os.path.join(os.path.dirname(__file__), "generated_personas")
    
    # Initialize analyzer
    analyzer = CareGapAnalyzer(personas_dir)
    
    # Create sample patient
    sample_patient = create_sample_patient()
    
    # Analyze patient
    print(f"Analyzing patient: {sample_patient.patient_id}")
    gaps = analyzer.analyze_patient(sample_patient)
    
    # Generate report
    report = analyzer.generate_care_gap_report(sample_patient, gaps)
    
    # Save report
    report_path = os.path.join(personas_dir, f"care_gap_report_{sample_patient.patient_id}.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\nCare Gap Analysis Complete!")
    print(f"Total gaps found: {len(gaps)}")
    print(f"Priority actions: {len(report['priority_actions'])}")
    print(f"Report saved to: {report_path}")
    
    # Print summary
    print("\nTop 3 Care Gaps:")
    for i, gap in enumerate(gaps[:3], 1):
        print(f"{i}. {gap.description} (Severity: {gap.severity})")
        print(f"   Action: {gap.recommended_action}")
        print(f"   Timeline: {gap.timeline}")
        print()

if __name__ == "__main__":
    main()