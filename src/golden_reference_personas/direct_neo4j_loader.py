#!/usr/bin/env python3
"""
Direct Neo4j Aura Loader for HEDIS Personas
Loads personas directly into Neo4j Aura database
"""

import json
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

class DirectNeo4jLoader:
    def __init__(self):
        self.uri = os.getenv('NEO4J_URI')
        self.username = os.getenv('NEO4J_USERNAME')
        self.password = os.getenv('NEO4J_PASSWORD')
        
        print(f"Connecting to: {self.uri}")
        print(f"Username: {self.username}")
        
        self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
    
    def close(self):
        self.driver.close()
    
    def clear_database(self):
        """Clear all existing data"""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            print("Database cleared")
    
    def create_constraints(self):
        """Create necessary constraints"""
        with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT persona_unique IF NOT EXISTS FOR (p:Persona) REQUIRE p.persona_id IS UNIQUE",
                "CREATE CONSTRAINT measure_unique IF NOT EXISTS FOR (m:Measure) REQUIRE m.measure_id IS UNIQUE",
                "CREATE CONSTRAINT patient_unique IF NOT EXISTS FOR (p:Patient) REQUIRE p.node_id IS UNIQUE"
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                    print(f"Created constraint: {constraint.split()[2]}")
                except Exception as e:
                    print(f"Constraint note: {e}")
    
    def load_personas_from_files(self):
        """Load all personas from JSON files"""
        personas_dir = "generated_personas"
        
        if not os.path.exists(personas_dir):
            print(f"Directory not found: {personas_dir}")
            return
        
        total_loaded = 0
        
        for filename in os.listdir(personas_dir):
            if filename.endswith('_personas.json'):
                filepath = os.path.join(personas_dir, filename)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    personas = data.get('personas', [])
                    
                    for persona in personas:
                        self.create_persona_graph(persona)
                        total_loaded += 1
                    
                    print(f"Loaded {len(personas)} personas from {filename}")
        
        print(f"Total personas loaded: {total_loaded}")
    
    def create_persona_graph(self, persona):
        """Create a complete persona graph"""
        with self.driver.session() as session:
            # Create measure node
            session.run("""
                MERGE (m:Measure {measure_id: $measure_id})
                SET m.measure_name = $measure_name
            """, 
            measure_id=persona['measure_id'],
            measure_name=persona['measure_name'])
            
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
            
            # Create nodes for this persona
            for node in persona.get('nodes', []):
                self.create_node(session, node, persona['persona_id'])
            
            # Create relationships
            for rel in persona.get('relationships', []):
                self.create_relationship(session, rel, persona['persona_id'])
            
            # Link persona to measure
            session.run("""
                MATCH (p:Persona {persona_id: $persona_id})
                MATCH (m:Measure {measure_id: $measure_id})
                MERGE (p)-[:BELONGS_TO_MEASURE]->(m)
            """,
            persona_id=persona['persona_id'],
            measure_id=persona['measure_id'])
    
    def create_node(self, session, node, persona_id):
        """Create individual nodes"""
        node_type = node['type'].title()
        props = node.get('properties', {})
        
        if node_type == 'Patient':
            session.run(f"""
                CREATE (n:{node_type} {{
                    node_id: $node_id,
                    persona_id: $persona_id,
                    age: $age,
                    gender: $gender,
                    product_line: $product_line,
                    enrollment_status: $enrollment_status,
                    continuous_enrollment: $continuous_enrollment
                }})
            """,
            node_id=node['id'],
            persona_id=persona_id,
            age=props.get('age', 0),
            gender=props.get('gender', ''),
            product_line=props.get('product_line', ''),
            enrollment_status=props.get('enrollment_status', ''),
            continuous_enrollment=props.get('continuous_enrollment', False))
            
        elif node_type == 'Condition':
            session.run(f"""
                CREATE (n:{node_type} {{
                    node_id: $node_id,
                    persona_id: $persona_id,
                    condition_name: $condition_name,
                    icd10_codes: $icd10_codes,
                    diagnosis_date: $diagnosis_date,
                    active: $active
                }})
            """,
            node_id=node['id'],
            persona_id=persona_id,
            condition_name=props.get('condition_name', ''),
            icd10_codes=props.get('icd10_codes', []),
            diagnosis_date=props.get('diagnosis_date', ''),
            active=props.get('active', True))
            
        elif node_type == 'Procedure':
            session.run(f"""
                CREATE (n:{node_type} {{
                    node_id: $node_id,
                    persona_id: $persona_id,
                    procedure_type: $procedure_type,
                    cpt_codes: $cpt_codes,
                    procedure_date: $procedure_date,
                    completed: $completed,
                    result: $result
                }})
            """,
            node_id=node['id'],
            persona_id=persona_id,
            procedure_type=props.get('procedure_type', ''),
            cpt_codes=props.get('cpt_codes', []),
            procedure_date=props.get('procedure_date', ''),
            completed=props.get('completed', False),
            result=props.get('result', ''))
            
        elif node_type == 'Medication':
            session.run(f"""
                CREATE (n:{node_type} {{
                    node_id: $node_id,
                    persona_id: $persona_id,
                    medication_class: $medication_class,
                    prescribed_date: $prescribed_date,
                    adherence_rate: $adherence_rate,
                    active: $active
                }})
            """,
            node_id=node['id'],
            persona_id=persona_id,
            medication_class=props.get('medication_class', ''),
            prescribed_date=props.get('prescribed_date', ''),
            adherence_rate=props.get('adherence_rate', 0.0),
            active=props.get('active', True))
            
        elif node_type == 'Exclusion':
            session.run(f"""
                CREATE (n:{node_type} {{
                    node_id: $node_id,
                    persona_id: $persona_id,
                    exclusion_type: $exclusion_type,
                    exclusion_description: $exclusion_description,
                    icd10_codes: $icd10_codes,
                    cpt_codes: $cpt_codes,
                    exclusion_date: $exclusion_date,
                    active: $active
                }})
            """,
            node_id=node['id'],
            persona_id=persona_id,
            exclusion_type=props.get('exclusion_type', ''),
            exclusion_description=props.get('exclusion_description', ''),
            icd10_codes=props.get('icd10_codes', []),
            cpt_codes=props.get('cpt_codes', []),
            exclusion_date=props.get('exclusion_date', ''),
            active=props.get('active', True))
    
    def create_relationship(self, session, rel, persona_id):
        """Create relationships between nodes"""
        try:
            session.run("""
                MATCH (source {node_id: $source_id, persona_id: $persona_id})
                MATCH (target {node_id: $target_id, persona_id: $persona_id})
                CREATE (source)-[r:RELATED {
                    relationship_type: $rel_type,
                    strength: $strength,
                    relevance: $relevance
                }]->(target)
            """,
            source_id=rel['source_id'],
            target_id=rel['target_id'],
            persona_id=persona_id,
            rel_type=rel['relationship_type'],
            strength=rel.get('properties', {}).get('strength', 'medium'),
            relevance=rel.get('properties', {}).get('relevance', 'medium'))
        except Exception as e:
            # Skip relationship creation errors
            pass
    
    def get_statistics(self):
        """Get database statistics"""
        with self.driver.session() as session:
            # Count nodes by type
            result = session.run("MATCH (n) RETURN labels(n)[0] as node_type, count(n) as count ORDER BY count DESC")
            node_stats = {record['node_type']: record['count'] for record in result}
            
            # Count relationships
            result = session.run("MATCH ()-[r]->() RETURN count(r) as total_relationships")
            rel_count = result.single()['total_relationships']
            
            # Count personas by measure
            result = session.run("""
                MATCH (p:Persona)-[:BELONGS_TO_MEASURE]->(m:Measure)
                RETURN m.measure_id as measure, count(p) as personas
                ORDER BY personas DESC
            """)
            measure_stats = {record['measure']: record['personas'] for record in result}
            
            return {
                'nodes': node_stats,
                'relationships': rel_count,
                'measures': measure_stats
            }

def main():
    loader = DirectNeo4jLoader()
    
    try:
        print("HEDIS PERSONAS - DIRECT NEO4J AURA LOADER")
        print("=" * 50)
        
        # Clear existing data
        print("Clearing existing data...")
        loader.clear_database()
        
        # Create constraints
        print("Creating constraints...")
        loader.create_constraints()
        
        # Load personas
        print("Loading personas...")
        loader.load_personas_from_files()
        
        # Get statistics
        print("\nDatabase Statistics:")
        stats = loader.get_statistics()
        
        print(f"Nodes by type:")
        for node_type, count in stats['nodes'].items():
            print(f"  {node_type}: {count}")
        
        print(f"Total relationships: {stats['relationships']}")
        
        print(f"Personas by measure:")
        for measure, count in stats['measures'].items():
            print(f"  {measure}: {count}")
        
        print("\nSuccess! All personas loaded into Neo4j Aura database.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        loader.close()

if __name__ == "__main__":
    main()