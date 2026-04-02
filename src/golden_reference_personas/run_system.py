"""
Golden Reference Persona System Runner
Orchestrates the complete persona generation, analysis, and care gap identification system
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, List, Any

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persona_generator import HEDISPersonaGenerator, PersonaProfile
from care_gap_analyzer import CareGapAnalyzer, PatientData, CareGapFinding
from neo4j_integration import PersonaNeo4jManager

class GoldenReferenceSystem:
    """Main system orchestrator for golden reference personas"""
    
    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = os.path.dirname(__file__)
        
        self.base_dir = base_dir
        self.personas_dir = os.path.join(base_dir, "generated_personas")
        self.reports_dir = os.path.join(base_dir, "reports")
        self.data_dir = os.path.join(base_dir, "patient_data")
        
        # Create directories if they don't exist
        for directory in [self.personas_dir, self.reports_dir, self.data_dir]:
            os.makedirs(directory, exist_ok=True)
        
        self.generator = HEDISPersonaGenerator()
        self.analyzer = None
        self.neo4j_manager = None
    
    def generate_personas(self, force_regenerate: bool = False) -> List[PersonaProfile]:
        """Generate all golden reference personas"""
        print("=" * 60)
        print("STEP 1: GENERATING GOLDEN REFERENCE PERSONAS")
        print("=" * 60)
        
        # Check if personas already exist
        summary_file = os.path.join(self.personas_dir, "personas_summary.json")
        if os.path.exists(summary_file) and not force_regenerate:
            print("Personas already exist. Use --force-regenerate to recreate them.")
            with open(summary_file, 'r', encoding='utf-8') as f:
                summary = json.load(f)
                print(f"Existing personas: {summary['total_personas']} across {summary['measures_covered']} measures")
                return []
        
        print("Generating comprehensive personas for all HEDIS measures...")
        personas = self.generator.generate_all_personas()
        
        print(f"\nSaving {len(personas)} personas to files...")
        self.generator.save_personas_to_files(personas, self.personas_dir)
        
        # Generate summary report
        summary = self.generator.generate_summary_report(personas)
        summary_path = os.path.join(self.personas_dir, "personas_summary.json")
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\nPersona Generation Complete!")
        print(f"Total personas: {summary['total_personas']}")
        print(f"Measures covered: {summary['measures_covered']}")
        print(f"Compliance breakdown:")
        for status, count in summary['compliance_breakdown'].items():
            print(f"  {status}: {count}")
        
        return personas
    
    def load_personas_to_neo4j(self, clear_existing: bool = True):
        """Load personas into Neo4j graph database"""
        print("\n" + "=" * 60)
        print("STEP 2: LOADING PERSONAS TO NEO4J")
        print("=" * 60)
        
        try:
            self.neo4j_manager = PersonaNeo4jManager()
            
            if clear_existing:
                print("Clearing existing persona data from Neo4j...")
                self.neo4j_manager.clear_all_personas()
            
            print("Loading personas into Neo4j...")
            self.neo4j_manager.load_personas_from_files(self.personas_dir)
            
            # Get statistics
            stats = self.neo4j_manager.get_measure_statistics()
            print(f"\nNeo4j Loading Complete!")
            print(f"Loaded personas for {len(stats)} measures:")
            for measure_id, stat in stats.items():
                print(f"  {measure_id}: {stat['total_personas']} personas")
            
        except Exception as e:
            print(f"Neo4j integration failed: {e}")
            print("Continuing without Neo4j integration...")
            self.neo4j_manager = None
    
    def initialize_analyzer(self):
        """Initialize the care gap analyzer"""
        print("\n" + "=" * 60)
        print("STEP 3: INITIALIZING CARE GAP ANALYZER")
        print("=" * 60)
        
        self.analyzer = CareGapAnalyzer(self.personas_dir)
        print("Care gap analyzer initialized successfully!")
    
    def create_sample_patients(self) -> List[PatientData]:
        """Create sample patients for demonstration"""
        print("\n" + "=" * 60)
        print("STEP 4: CREATING SAMPLE PATIENTS")
        print("=" * 60)
        
        sample_patients = [
            # Patient 1: Diabetic female needing screening
            PatientData(
                patient_id="DEMO_001",
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
            ),
            
            # Patient 2: Elderly Medicare patient
            PatientData(
                patient_id="DEMO_002",
                age=68,
                gender="Male",
                product_line="Medicare",
                conditions=[
                    {
                        "name": "Hypertension",
                        "icd10_codes": ["I10"],
                        "diagnosis_date": "2020-03-15",
                        "active": True
                    },
                    {
                        "name": "Hyperlipidemia",
                        "icd10_codes": ["E78.5"],
                        "diagnosis_date": "2021-07-20",
                        "active": True
                    }
                ],
                procedures=[
                    {
                        "name": "Annual Wellness Visit",
                        "cpt_codes": ["G0438"],
                        "procedure_date": "2024-03-15",
                        "completed": True
                    }
                ],
                medications=[
                    {
                        "name": "Lisinopril",
                        "ndc_codes": ["00093-1530-01"],
                        "prescribed_date": "2024-01-01",
                        "active": True
                    }
                ],
                exclusions=[],
                enrollment_data={
                    "enrollment_start": "2024-01-01",
                    "continuous_enrollment": True,
                    "product_line": "Medicare"
                }
            ),
            
            # Patient 3: Young female needing preventive care
            PatientData(
                patient_id="DEMO_003",
                age=28,
                gender="Female",
                product_line="Medicaid",
                conditions=[],
                procedures=[],
                medications=[],
                exclusions=[],
                enrollment_data={
                    "enrollment_start": "2024-01-01",
                    "continuous_enrollment": True,
                    "product_line": "Medicaid"
                }
            )
        ]
        
        # Save sample patients
        patients_file = os.path.join(self.data_dir, "sample_patients.json")
        patients_data = []
        for patient in sample_patients:
            patient_dict = {
                "patient_id": patient.patient_id,
                "age": patient.age,
                "gender": patient.gender,
                "product_line": patient.product_line,
                "conditions": patient.conditions,
                "procedures": patient.procedures,
                "medications": patient.medications,
                "exclusions": patient.exclusions,
                "enrollment_data": patient.enrollment_data
            }
            patients_data.append(patient_dict)
        
        with open(patients_file, 'w', encoding='utf-8') as f:
            json.dump({
                "created_at": datetime.now().isoformat(),
                "total_patients": len(patients_data),
                "patients": patients_data
            }, f, indent=2, ensure_ascii=False)
        
        print(f"Created {len(sample_patients)} sample patients")
        print(f"Sample patients saved to: {patients_file}")
        
        return sample_patients
    
    def analyze_patients(self, patients: List[PatientData]) -> Dict[str, List[CareGapFinding]]:
        """Analyze patients for care gaps"""
        print("\n" + "=" * 60)
        print("STEP 5: ANALYZING PATIENTS FOR CARE GAPS")
        print("=" * 60)
        
        if not self.analyzer:
            print("Analyzer not initialized!")
            return {}
        
        all_patient_gaps = {}
        
        for patient in patients:
            print(f"\nAnalyzing patient: {patient.patient_id} ({patient.age}y {patient.gender}, {patient.product_line})")
            
            # Analyze patient
            gaps = self.analyzer.analyze_patient(patient)
            all_patient_gaps[patient.patient_id] = gaps
            
            # Generate report
            report = self.analyzer.generate_care_gap_report(patient, gaps)
            
            # Save individual report
            report_file = os.path.join(self.reports_dir, f"care_gap_report_{patient.patient_id}.json")
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            print(f"  Found {len(gaps)} care gaps")
            print(f"  Priority actions: {len(report['priority_actions'])}")
            print(f"  Report saved: {report_file}")
            
            # Print top gaps
            if gaps:
                print("  Top care gaps:")
                for i, gap in enumerate(gaps[:3], 1):
                    print(f"    {i}. {gap.description} (Severity: {gap.severity})")
        
        return all_patient_gaps
    
    def generate_system_report(self, patient_gaps: Dict[str, List[CareGapFinding]]):
        """Generate comprehensive system report"""
        print("\n" + "=" * 60)
        print("STEP 6: GENERATING SYSTEM REPORT")
        print("=" * 60)
        
        # Load personas summary
        summary_file = os.path.join(self.personas_dir, "personas_summary.json")
        personas_summary = {}
        if os.path.exists(summary_file):
            with open(summary_file, 'r', encoding='utf-8') as f:
                personas_summary = json.load(f)
        
        # Aggregate gap statistics
        total_gaps = sum(len(gaps) for gaps in patient_gaps.values())
        gaps_by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        gaps_by_measure = {}
        
        for patient_id, gaps in patient_gaps.items():
            for gap in gaps:
                gaps_by_severity[gap.severity] = gaps_by_severity.get(gap.severity, 0) + 1
                measure_id = gap.measure_id
                if measure_id not in gaps_by_measure:
                    gaps_by_measure[measure_id] = {"measure_name": gap.measure_name, "count": 0}
                gaps_by_measure[measure_id]["count"] += 1
        
        # Create system report
        system_report = {
            "report_generated": datetime.now().isoformat(),
            "system_overview": {
                "total_personas_generated": personas_summary.get("total_personas", 0),
                "measures_covered": personas_summary.get("measures_covered", 0),
                "patients_analyzed": len(patient_gaps),
                "total_care_gaps_identified": total_gaps
            },
            "persona_statistics": personas_summary.get("compliance_breakdown", {}),
            "care_gap_analysis": {
                "gaps_by_severity": gaps_by_severity,
                "gaps_by_measure": gaps_by_measure,
                "patients_with_gaps": len([p for p, g in patient_gaps.items() if g]),
                "average_gaps_per_patient": total_gaps / len(patient_gaps) if patient_gaps else 0
            },
            "system_performance": {
                "personas_directory": self.personas_dir,
                "reports_directory": self.reports_dir,
                "neo4j_integration": self.neo4j_manager is not None,
                "analyzer_initialized": self.analyzer is not None
            }
        }
        
        # Save system report
        system_report_file = os.path.join(self.reports_dir, "system_report.json")
        with open(system_report_file, 'w', encoding='utf-8') as f:
            json.dump(system_report, f, indent=2, ensure_ascii=False)
        
        print("System Report Generated!")
        print(f"Total personas: {system_report['system_overview']['total_personas_generated']}")
        print(f"Measures covered: {system_report['system_overview']['measures_covered']}")
        print(f"Patients analyzed: {system_report['system_overview']['patients_analyzed']}")
        print(f"Care gaps found: {system_report['system_overview']['total_care_gaps_identified']}")
        print(f"System report saved: {system_report_file}")
        
        return system_report
    
    def run_complete_system(self, force_regenerate: bool = False, use_neo4j: bool = True):
        """Run the complete golden reference persona system"""
        print("HEDIS GOLDEN REFERENCE PERSONA SYSTEM")
        print("=" * 60)
        print(f"Started at: {datetime.now().isoformat()}")
        print(f"Base directory: {self.base_dir}")
        
        try:
            # Step 1: Generate personas
            personas = self.generate_personas(force_regenerate)
            
            # Step 2: Load to Neo4j (optional)
            if use_neo4j:
                self.load_personas_to_neo4j()
            
            # Step 3: Initialize analyzer
            self.initialize_analyzer()
            
            # Step 4: Create sample patients
            sample_patients = self.create_sample_patients()
            
            # Step 5: Analyze patients
            patient_gaps = self.analyze_patients(sample_patients)
            
            # Step 6: Generate system report
            system_report = self.generate_system_report(patient_gaps)
            
            print("\n" + "=" * 60)
            print("SYSTEM EXECUTION COMPLETED SUCCESSFULLY!")
            print("=" * 60)
            print(f"Completed at: {datetime.now().isoformat()}")
            print(f"\nKey Results:")
            print(f"- Generated {system_report['system_overview']['total_personas_generated']} personas")
            print(f"- Covered {system_report['system_overview']['measures_covered']} HEDIS measures")
            print(f"- Analyzed {system_report['system_overview']['patients_analyzed']} patients")
            print(f"- Identified {system_report['system_overview']['total_care_gaps_identified']} care gaps")
            print(f"\nOutput Directories:")
            print(f"- Personas: {self.personas_dir}")
            print(f"- Reports: {self.reports_dir}")
            print(f"- Patient Data: {self.data_dir}")
            
            return system_report
            
        except Exception as e:
            print(f"\nSYSTEM ERROR: {e}")
            import traceback
            traceback.print_exc()
            return None
        
        finally:
            # Cleanup
            if self.neo4j_manager:
                self.neo4j_manager.close()
    
    def cleanup(self):
        """Cleanup resources"""
        if self.neo4j_manager:
            self.neo4j_manager.close()

def main():
    """Main entry point with command line arguments"""
    parser = argparse.ArgumentParser(description="HEDIS Golden Reference Persona System")
    parser.add_argument("--force-regenerate", action="store_true", 
                       help="Force regeneration of personas even if they exist")
    parser.add_argument("--no-neo4j", action="store_true", 
                       help="Skip Neo4j integration")
    parser.add_argument("--base-dir", type=str, 
                       help="Base directory for the system (default: current directory)")
    
    args = parser.parse_args()
    
    # Initialize system
    system = GoldenReferenceSystem(args.base_dir)
    
    try:
        # Run complete system
        result = system.run_complete_system(
            force_regenerate=args.force_regenerate,
            use_neo4j=not args.no_neo4j
        )
        
        if result:
            print("\nGolden Reference Persona System executed successfully!")
            print("You can now use the generated personas for precise care gap analysis.")
        else:
            print("\n❌ System execution failed. Check the error messages above.")
            sys.exit(1)
    
    finally:
        system.cleanup()

if __name__ == "__main__":
    main()