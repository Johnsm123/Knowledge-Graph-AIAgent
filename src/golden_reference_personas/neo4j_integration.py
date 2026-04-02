"""
Neo4j Persona Integration
Stores and queries golden reference personas in Neo4j graph database
"""

import json
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from neo4j import GraphDatabase
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class PersonaNeo4jManager:
    """Manages personas in Neo4j graph database"""
    
    def __init__(self, uri: str = None, user: str = None, password: str = None):
        # Use environment variables if parameters not provided
        self.uri = uri or os.getenv('NEO4J_URI', 'bolt://localhost:7687')
        self.user = user or os.getenv('NEO4J_USERNAME', 'neo4j')
        self.password = password or os.getenv('NEO4J_PASSWORD', 'password')
        
        print(f"Connecting to Neo4j at: {self.uri}")
        print(f"Username: {self.user}")
        
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.create_constraints()
    
    def close(self):
        """Close the database connection"""
        self.driver.close()
    
    def create_constraints(self):
        """Create necessary constraints and indexes"""
        with self.driver.session() as session:
            # Create constraints
            constraints = [
                "CREATE CONSTRAINT persona_id IF NOT EXISTS FOR (p:Persona) REQUIRE p.persona_id IS UNIQUE",
                "CREATE CONSTRAINT patient_id IF NOT EXISTS FOR (p:Patient) REQUIRE p.patient_id IS UNIQUE",
                "CREATE CONSTRAINT condition_id IF NOT EXISTS FOR (c:Condition) REQUIRE c.condition_id IS UNIQUE",
                "CREATE CONSTRAINT procedure_id IF NOT EXISTS FOR (p:Procedure) REQUIRE p.procedure_id IS UNIQUE",
                "CREATE CONSTRAINT medication_id IF NOT EXISTS FOR (m:Medication) REQUIRE m.medication_id IS UNIQUE",
                "CREATE CONSTRAINT exclusion_id IF NOT EXISTS FOR (e:Exclusion) REQUIRE e.exclusion_id IS UNIQUE",
                "CREATE CONSTRAINT measure_id IF NOT EXISTS FOR (m:Measure) REQUIRE m.measure_id IS UNIQUE"
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    print(f"Constraint creation note: {e}")
            
            # Create indexes
            indexes = [
                "CREATE INDEX persona_measure IF NOT EXISTS FOR (p:Persona) ON (p.measure_id)",
                "CREATE INDEX patient_age IF NOT EXISTS FOR (p:Patient) ON (p.age)",
                "CREATE INDEX patient_gender IF NOT EXISTS FOR (p:Patient) ON (p.gender)",
                "CREATE INDEX condition_name IF NOT EXISTS FOR (c:Condition) ON (c.condition_name)",
                "CREATE INDEX procedure_type IF NOT EXISTS FOR (p:Procedure) ON (p.procedure_type)"
            ]
            
            for index in indexes:
                try:
                    session.run(index)
                except Exception as e:
                    print(f"Index creation note: {e}")
    
    def clear_all_personas(self):
        """Clear all persona data from the database"""
        with self.driver.session() as session:
            session.run("MATCH (n) WHERE n:Persona OR n:Patient OR n:Condition OR n:Procedure OR n:Medication OR n:Exclusion OR n:Measure DETACH DELETE n")
            print("Cleared all persona data from Neo4j")
    
    def load_personas_from_files(self, personas_dir: str):
        """Load all personas from JSON files into Neo4j"""
        if not os.path.exists(personas_dir):
            print(f"Personas directory not found: {personas_dir}")
            return
        
        total_loaded = 0
        
        for filename in os.listdir(personas_dir):
            if filename.endswith('_personas.json'):
                filepath = os.path.join(personas_dir, filename)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        personas = data.get('personas', [])
                        
                        for persona in personas:
                            self.create_persona_in_neo4j(persona)
                            total_loaded += 1
                        
                        print(f"Loaded {len(personas)} personas from {filename}")
                        
                except Exception as e:
                    print(f"Error loading {filename}: {e}")
        
        print(f"Total personas loaded into Neo4j: {total_loaded}")
    
    def create_persona_in_neo4j(self, persona: Dict):
        """Create a single persona with all its nodes and relationships in Neo4j"""
        with self.driver.session() as session:
            # Create measure node
            session.run("""
                MERGE (m:Measure {measure_id: $measure_id})
                SET m.measure_name = $measure_name,
                    m.updated_at = datetime()
            """, measure_id=persona['measure_id'], measure_name=persona['measure_name'])
            
            # Create persona node
            session.run("""
                CREATE (p:Persona {
                    persona_id: $persona_id,
                    measure_id: $measure_id,
                    measure_name: $measure_name,
                    compliance_status: $compliance_status,
                    created_at: $created_at
                })
            """, 
            persona_id=persona['persona_id'],
            measure_id=persona['measure_id'],
            measure_name=persona['measure_name'],
            compliance_status=persona['compliance_status'],
            created_at=persona['created_at'])
            
            # Create nodes
            for node in persona.get('nodes', []):
                self.create_node_in_neo4j(session, node, persona['persona_id'])
            
            # Create relationships
            for relationship in persona.get('relationships', []):
                self.create_relationship_in_neo4j(session, relationship)
            
            # Link persona to measure
            session.run("""
                MATCH (p:Persona {persona_id: $persona_id})
                MATCH (m:Measure {measure_id: $measure_id})
                MERGE (p)-[:BELONGS_TO_MEASURE]->(m)
            """, persona_id=persona['persona_id'], measure_id=persona['measure_id'])
    
    def create_node_in_neo4j(self, session, node: Dict, persona_id: str):
        """Create a node in Neo4j based on its type"""
        node_type = node['type']
        node_id = node['id']
        properties = node.get('properties', {})
        
        if node_type == 'patient':
            session.run("""
                CREATE (n:Patient {
                    patient_id: $node_id,
                    persona_id: $persona_id,
                    age: $age,
                    gender: $gender,
                    product_line: $product_line,
                    enrollment_status: $enrollment_status,
                    continuous_enrollment: $continuous_enrollment,
                    created_at: $created_at
                })
            """, node_id=node_id, persona_id=persona_id, **properties, created_at=node.get('created_at'))
            
        elif node_type == 'condition':
            session.run("""
                CREATE (n:Condition {
                    condition_id: $node_id,
                    persona_id: $persona_id,
                    condition_name: $condition_name,
                    icd10_codes: $icd10_codes,
                    diagnosis_date: $diagnosis_date,
                    active: $active,
                    created_at: $created_at
                })
            """, node_id=node_id, persona_id=persona_id, **properties, created_at=node.get('created_at'))
            
        elif node_type == 'procedure':
            session.run("""
                CREATE (n:Procedure {
                    procedure_id: $node_id,
                    persona_id: $persona_id,
                    procedure_type: $procedure_type,
                    cpt_codes: $cpt_codes,
                    procedure_date: $procedure_date,
                    completed: $completed,
                    result: $result,
                    created_at: $created_at
                })
            """, node_id=node_id, persona_id=persona_id, **properties, created_at=node.get('created_at'))
            
        elif node_type == 'medication':
            session.run("""
                CREATE (n:Medication {
                    medication_id: $node_id,
                    persona_id: $persona_id,
                    medication_class: $medication_class,
                    prescribed_date: $prescribed_date,
                    adherence_rate: $adherence_rate,
                    active: $active,
                    created_at: $created_at
                })
            """, node_id=node_id, persona_id=persona_id, **properties, created_at=node.get('created_at'))
            
        elif node_type == 'exclusion':
            session.run("""
                CREATE (n:Exclusion {
                    exclusion_id: $node_id,
                    persona_id: $persona_id,
                    exclusion_type: $exclusion_type,
                    exclusion_description: $exclusion_description,
                    icd10_codes: $icd10_codes,
                    cpt_codes: $cpt_codes,
                    exclusion_date: $exclusion_date,
                    active: $active,
                    created_at: $created_at
                })
            """, node_id=node_id, persona_id=persona_id, **properties, created_at=node.get('created_at'))
    
    def create_relationship_in_neo4j(self, session, relationship: Dict):
        """Create a relationship in Neo4j"""
        session.run("""
            MATCH (source) WHERE source.patient_id = $source_id OR source.condition_id = $source_id OR source.procedure_id = $source_id OR source.medication_id = $source_id OR source.exclusion_id = $source_id
            MATCH (target) WHERE target.patient_id = $target_id OR target.condition_id = $target_id OR target.procedure_id = $target_id OR target.medication_id = $target_id OR target.exclusion_id = $target_id
            CREATE (source)-[r:RELATIONSHIP {
                relationship_id: $relationship_id,
                relationship_type: $relationship_type,
                strength: $strength,
                relevance: $relevance,
                created_at: $created_at
            }]->(target)
        """, 
        relationship_id=relationship['id'],
        source_id=relationship['source_id'],
        target_id=relationship['target_id'],
        relationship_type=relationship['relationship_type'],
        strength=relationship.get('properties', {}).get('strength', 'medium'),
        relevance=relationship.get('properties', {}).get('relevance', 'medium'),
        created_at=relationship.get('created_at'))
    
    def find_matching_personas(self, patient_age: int, patient_gender: str, 
                             patient_conditions: List[str], measure_id: Optional[str] = None) -> List[Dict]:
        """Find personas that match patient characteristics"""
        with self.driver.session() as session:
            query = """
                MATCH (p:Persona)-[:BELONGS_TO_MEASURE]->(m:Measure)
                MATCH (p)<-[:RELATIONSHIP]-(patient:Patient)
                WHERE patient.age >= $min_age AND patient.age <= $max_age
                AND patient.gender = $gender
            """
            
            params = {
                'min_age': patient_age - 10,
                'max_age': patient_age + 10,
                'gender': patient_gender
            }
            
            if measure_id:
                query += " AND m.measure_id = $measure_id"
                params['measure_id'] = measure_id
            
            query += """
                OPTIONAL MATCH (p)<-[:RELATIONSHIP]-(c:Condition)
                RETURN p.persona_id as persona_id,
                       p.measure_id as measure_id,
                       p.measure_name as measure_name,
                       p.compliance_status as compliance_status,
                       patient.age as patient_age,
                       patient.gender as patient_gender,
                       patient.product_line as product_line,
                       collect(DISTINCT c.condition_name) as conditions
                ORDER BY abs(patient.age - $patient_age)
                LIMIT 20
            """
            
            params['patient_age'] = patient_age
            
            result = session.run(query, params)
            return [record.data() for record in result]
    
    def get_persona_details(self, persona_id: str) -> Dict:
        """Get complete details of a persona"""
        with self.driver.session() as session:
            # Get persona basic info
            persona_result = session.run("""
                MATCH (p:Persona {persona_id: $persona_id})
                RETURN p
            """, persona_id=persona_id)
            
            persona_record = persona_result.single()
            if not persona_record:
                return {}
            
            persona_data = dict(persona_record['p'])
            
            # Get all related nodes
            nodes_result = session.run("""
                MATCH (p:Persona {persona_id: $persona_id})<-[:RELATIONSHIP]-(n)
                RETURN labels(n) as node_type, properties(n) as properties
            """, persona_id=persona_id)
            
            persona_data['nodes'] = []
            for record in nodes_result:
                persona_data['nodes'].append({
                    'type': record['node_type'][0].lower(),
                    'properties': record['properties']
                })
            
            # Get relationships
            relationships_result = session.run("""
                MATCH (p:Persona {persona_id: $persona_id})<-[:RELATIONSHIP]-(source)-[r:RELATIONSHIP]->(target)
                RETURN r.relationship_type as relationship_type,
                       r.strength as strength,
                       r.relevance as relevance,
                       labels(source)[0] as source_type,
                       labels(target)[0] as target_type
            """, persona_id=persona_id)
            
            persona_data['relationships'] = []
            for record in relationships_result:
                persona_data['relationships'].append(dict(record))
            
            return persona_data
    
    def find_care_gaps_for_patient(self, patient_age: int, patient_gender: str, 
                                 patient_conditions: List[str], patient_procedures: List[str]) -> List[Dict]:
        """Find potential care gaps by comparing with compliant personas"""
        with self.driver.session() as session:
            query = """
                MATCH (p:Persona {compliance_status: 'compliant'})-[:BELONGS_TO_MEASURE]->(m:Measure)
                MATCH (p)<-[:RELATIONSHIP]-(patient:Patient)
                MATCH (p)<-[:RELATIONSHIP]-(proc:Procedure)
                WHERE patient.age >= $min_age AND patient.age <= $max_age
                AND patient.gender = $gender
                AND proc.completed = true
                RETURN DISTINCT p.persona_id as persona_id,
                       p.measure_id as measure_id,
                       p.measure_name as measure_name,
                       collect(DISTINCT proc.procedure_type) as required_procedures,
                       collect(DISTINCT proc.cpt_codes) as required_codes
                ORDER BY abs(patient.age - $patient_age)
                LIMIT 10
            """
            
            result = session.run(query, {
                'min_age': patient_age - 5,
                'max_age': patient_age + 5,
                'gender': patient_gender,
                'patient_age': patient_age
            })
            
            potential_gaps = []
            for record in result:
                # Check if patient has required procedures
                required_procedures = record['required_procedures']
                has_required = any(proc in patient_procedures for proc in required_procedures)
                
                if not has_required:
                    potential_gaps.append({
                        'persona_id': record['persona_id'],
                        'measure_id': record['measure_id'],
                        'measure_name': record['measure_name'],
                        'missing_procedures': required_procedures,
                        'required_codes': record['required_codes'],
                        'gap_type': 'missing_procedure',
                        'severity': 'high'
                    })
            
            return potential_gaps
    
    def get_measure_statistics(self) -> Dict:
        """Get statistics about personas by measure"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (p:Persona)-[:BELONGS_TO_MEASURE]->(m:Measure)
                RETURN m.measure_id as measure_id,
                       m.measure_name as measure_name,
                       count(p) as total_personas,
                       count(CASE WHEN p.compliance_status = 'compliant' THEN 1 END) as compliant,
                       count(CASE WHEN p.compliance_status = 'non_compliant' THEN 1 END) as non_compliant,
                       count(CASE WHEN p.compliance_status = 'excluded' THEN 1 END) as excluded
                ORDER BY total_personas DESC
            """)
            
            stats = {}
            for record in result:
                stats[record['measure_id']] = dict(record)
            
            return stats
    
    def export_personas_to_json(self, output_file: str):
        """Export all personas from Neo4j to JSON file"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (p:Persona)
                OPTIONAL MATCH (p)<-[:RELATIONSHIP]-(n)
                RETURN p.persona_id as persona_id,
                       p.measure_id as measure_id,
                       p.measure_name as measure_name,
                       p.compliance_status as compliance_status,
                       p.created_at as created_at,
                       collect({
                           type: labels(n)[0],
                           properties: properties(n)
                       }) as nodes
            """)
            
            personas = []
            for record in result:
                persona_data = dict(record)
                # Filter out null nodes
                persona_data['nodes'] = [n for n in persona_data['nodes'] if n['type']]
                personas.append(persona_data)
            
            export_data = {
                'export_date': datetime.now().isoformat(),
                'total_personas': len(personas),
                'personas': personas
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"Exported {len(personas)} personas to {output_file}")

def main():
    """Main function for testing Neo4j integration"""
    # Initialize Neo4j manager
    neo4j_manager = PersonaNeo4jManager()
    
    try:
        # Path to generated personas
        personas_dir = os.path.join(os.path.dirname(__file__), "generated_personas")
        
        if os.path.exists(personas_dir):
            print("Loading personas into Neo4j...")
            
            # Clear existing data
            neo4j_manager.clear_all_personas()
            
            # Load personas from files
            neo4j_manager.load_personas_from_files(personas_dir)
            
            # Get statistics
            stats = neo4j_manager.get_measure_statistics()
            print(f"\nLoaded personas for {len(stats)} measures:")
            for measure_id, stat in stats.items():
                print(f"  {measure_id}: {stat['total_personas']} personas "
                      f"(C:{stat['compliant']}, NC:{stat['non_compliant']}, E:{stat['excluded']})")
            
            # Test finding matching personas
            print(f"\nTesting persona matching...")
            matches = neo4j_manager.find_matching_personas(
                patient_age=55,
                patient_gender="Female",
                patient_conditions=["Type 2 Diabetes", "Hypertension"]
            )
            print(f"Found {len(matches)} matching personas for 55-year-old female with diabetes and hypertension")
            
            # Test care gap finding
            print(f"\nTesting care gap identification...")
            gaps = neo4j_manager.find_care_gaps_for_patient(
                patient_age=55,
                patient_gender="Female",
                patient_conditions=["Type 2 Diabetes"],
                patient_procedures=["Office Visit"]
            )
            print(f"Found {len(gaps)} potential care gaps")
            
            # Export sample
            export_file = os.path.join(personas_dir, "neo4j_export_sample.json")
            neo4j_manager.export_personas_to_json(export_file)
            
        else:
            print(f"Personas directory not found: {personas_dir}")
            print("Please run persona_generator.py first to generate personas")
    
    finally:
        neo4j_manager.close()

if __name__ == "__main__":
    main()