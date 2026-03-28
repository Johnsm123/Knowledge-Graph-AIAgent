"""
Initialize medical knowledge graph with sample data
"""
import logging
from src.neo4j_connection import get_knowledge_graph
from src.kg_schema import INITIAL_DATA, SCHEMA_CONSTRAINTS, SCHEMA_INDEXES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def initialize_knowledge_graph():
    """Initialize Neo4j knowledge graph with schema and sample data"""
    
    kg = get_knowledge_graph()
    
    try:
        # Create constraints
        logger.info("Creating database constraints...")
        constraint_queries = SCHEMA_CONSTRAINTS.strip().split('\n')
        for query in constraint_queries:
            if query.strip().startswith("CREATE"):
                try:
                    kg.run_query(query)
                    logger.info(f"Created constraint: {query[:50]}...")
                except Exception as e:
                    logger.warning(f"Constraint already exists or error: {str(e)}")
        
        # Create indexes
        logger.info("Creating database indexes...")
        index_queries = SCHEMA_INDEXES.strip().split('\n')
        for query in index_queries:
            if query.strip().startswith("CREATE"):
                try:
                    kg.run_query(query)
                    logger.info(f"Created index: {query[:50]}...")
                except Exception as e:
                    logger.warning(f"Index already exists or error: {str(e)}")
        
        # Initialize medical conditions
        logger.info("Initializing medical conditions...")
        for condition in INITIAL_DATA["conditions"]:
            kg.create_medical_condition(
                condition_id=condition["condition_id"],
                name=condition["name"],
                severity=condition["severity"],
                description=condition["description"]
            )
        
        # Initialize symptoms
        logger.info("Initializing symptoms...")
        for symptom in INITIAL_DATA["symptoms"]:
            query = """
            CREATE (s:Symptom {
                symptom_id: $symptom_id,
                name: $name,
                description: $description,
                created_at: datetime()
            })
            RETURN s
            """
            kg.execute_write(query, symptom)
        
        # Initialize medications
        logger.info("Initializing medications...")
        for medication in INITIAL_DATA["medications"]:
            query = """
            CREATE (m:Medication {
                medication_id: $medication_id,
                name: $name,
                dosage: $dosage,
                description: $description,
                created_at: datetime()
            })
            RETURN m
            """
            kg.execute_write(query, medication)
        
        # Initialize risk factors
        logger.info("Initializing risk factors...")
        for risk_factor in INITIAL_DATA["risk_factors"]:
            query = """
            CREATE (r:RiskFactor {
                risk_factor_id: $risk_factor_id,
                name: $name,
                description: $description,
                created_at: datetime()
            })
            RETURN r
            """
            kg.execute_write(query, risk_factor)
        
        # Initialize preventions
        logger.info("Initializing preventions...")
        for prevention in INITIAL_DATA["preventions"]:
            query = """
            CREATE (p:Prevention {
                prevention_id: $prevention_id,
                name: $name,
                description: $description,
                created_at: datetime()
            })
            RETURN p
            """
            kg.execute_write(query, prevention)
        
        # Create relationships between conditions and symptoms
        logger.info("Creating condition-symptom relationships...")
        relationships = [
            ("COND001", "SYM001", "commonly presents with"),
            ("COND001", "SYM004", "commonly presents with"),
            ("COND002", "SYM002", "may cause"),
            ("COND003", "SYM003", "causes"),
            ("COND004", "SYM002", "primary symptom"),
        ]
        
        for condition_id, symptom_id, rel_type in relationships:
            query = """
            MATCH (c:Condition {condition_id: $condition_id})
            MATCH (s:Symptom {symptom_id: $symptom_id})
            CREATE (c)-[r:PRESENTS_WITH {type: $rel_type}]->(s)
            RETURN r
            """
            try:
                kg.execute_write(query, {
                    "condition_id": condition_id,
                    "symptom_id": symptom_id,
                    "rel_type": rel_type
                })
            except Exception as e:
                logger.warning(f"Relationship might already exist: {str(e)}")
        
        logger.info("Knowledge graph initialization completed successfully!")
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
