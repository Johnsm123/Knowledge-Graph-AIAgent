"""
Test script to verify comprehensive HEDIS golden reference data loading.
Queries Neo4j to confirm all nodes and relationships are created correctly.
"""
import sys
import logging
from src.care_gap_neo4j import get_measure_comprehensive, check_member_exclusions
from src.neo4j_connection import get_knowledge_graph

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def test_measure_structure():
    """Test that comprehensive measure data is loaded correctly"""
    logger.info("\n" + "="*80)
    logger.info("TESTING COMPREHENSIVE GOLDEN REFERENCE STRUCTURE")
    logger.info("="*80)
    
    measures = ["BCS", "COL", "CCS", "CDC-HbA1c"]
    
    for measure_id in measures:
        logger.info(f"\n--- Testing {measure_id} ---")
        
        measure = get_measure_comprehensive(measure_id)
        
        if not measure:
            logger.error(f"❌ {measure_id} not found in database!")
            continue
        
        logger.info(f"✓ Measure: {measure['name']}")
        logger.info(f"  Age Range: {measure['age_range']} (min: {measure['min_age']}, max: {measure['max_age']})")
        logger.info(f"  Gender: {measure['gender_requirement']}")
        logger.info(f"  Lookback: {measure['lookback_months']} months")
        
        # Check code sets
        code_sets = measure.get("code_sets", {})
        logger.info(f"  Code Sets: {len(code_sets)} types")
        for code_type, codes in code_sets.items():
            logger.info(f"    - {code_type}: {len(codes)} codes")
        
        # Check exclusions
        exclusions = measure.get("exclusions", [])
        logger.info(f"  Exclusions: {len(exclusions)} criteria")
        for excl in exclusions[:3]:  # Show first 3
            logger.info(f"    - {excl['type']}: {excl['description']}")
        
        # Check guidelines
        guidelines = measure.get("clinical_guidelines", {})
        acceptable = guidelines.get("acceptable", [])
        not_acceptable = guidelines.get("not_acceptable", [])
        logger.info(f"  Clinical Guidelines:")
        logger.info(f"    - Acceptable: {len(acceptable)} items")
        logger.info(f"    - Not Acceptable: {len(not_acceptable)} items")
        
        # Check best practices
        best_practices = measure.get("best_practices", [])
        logger.info(f"  Best Practices: {len(best_practices)} items")
        
        # Check screening options (for COL, CCS)
        screening_options = measure.get("screening_options", [])
        if screening_options:
            logger.info(f"  Screening Options: {len(screening_options)} types")
            for opt in screening_options:
                logger.info(f"    - {opt['type']}: {opt['lookback_months']} months lookback")


def test_exclusion_checking():
    """Test exclusion checking for specific members"""
    logger.info("\n" + "="*80)
    logger.info("TESTING EXCLUSION CHECKING")
    logger.info("="*80)
    
    # Test member M0011 (42F) for BCS exclusions
    logger.info("\n--- Testing M0011 (Quinn Iyer, 42F) for BCS exclusions ---")
    exclusions = check_member_exclusions("M0011", "BCS")
    if exclusions:
        logger.info(f"  Found {len(exclusions)} exclusions:")
        for excl in exclusions:
            logger.info(f"    - {excl['type']}: {excl['description']}")
    else:
        logger.info("  ✓ No exclusions found (member is eligible)")
    
    # Test member M0002 (41M with diabetes) for CDC-HbA1c exclusions
    logger.info("\n--- Testing M0002 (Liam Patel, 41M with diabetes) for CDC-HbA1c exclusions ---")
    exclusions = check_member_exclusions("M0002", "CDC-HbA1c")
    if exclusions:
        logger.info(f"  Found {len(exclusions)} exclusions:")
        for excl in exclusions:
            logger.info(f"    - {excl['type']}: {excl['description']}")
    else:
        logger.info("  ✓ No exclusions found (member is eligible)")


def test_node_counts():
    """Test that all expected nodes are created"""
    logger.info("\n" + "="*80)
    logger.info("TESTING NODE COUNTS")
    logger.info("="*80)
    
    kg = get_knowledge_graph()
    
    # Count QualityMeasure nodes
    measures = kg.run_query("MATCH (q:QualityMeasure) RETURN count(q) as count", {})
    logger.info(f"  QualityMeasure nodes: {measures[0]['count']}")
    
    # Count CodeSet nodes
    code_sets = kg.run_query("MATCH (cs:CodeSet) RETURN count(cs) as count", {})
    logger.info(f"  CodeSet nodes: {code_sets[0]['count']}")
    
    # Count ExclusionCriteria nodes
    exclusions = kg.run_query("MATCH (e:ExclusionCriteria) RETURN count(e) as count", {})
    logger.info(f"  ExclusionCriteria nodes: {exclusions[0]['count']}")
    
    # Count ClinicalGuideline nodes
    guidelines = kg.run_query("MATCH (cg:ClinicalGuideline) RETURN count(cg) as count", {})
    logger.info(f"  ClinicalGuideline nodes: {guidelines[0]['count']}")
    
    # Count BestPractices nodes
    best_practices = kg.run_query("MATCH (bp:BestPractices) RETURN count(bp) as count", {})
    logger.info(f"  BestPractices nodes: {best_practices[0]['count']}")
    
    # Count ScreeningOption nodes
    screening_options = kg.run_query("MATCH (so:ScreeningOption) RETURN count(so) as count", {})
    logger.info(f"  ScreeningOption nodes: {screening_options[0]['count']}")
    
    # Count relationships
    requires_codes = kg.run_query("MATCH ()-[r:REQUIRES_CODES]->() RETURN count(r) as count", {})
    logger.info(f"  REQUIRES_CODES relationships: {requires_codes[0]['count']}")
    
    has_exclusion = kg.run_query("MATCH ()-[r:HAS_EXCLUSION]->() RETURN count(r) as count", {})
    logger.info(f"  HAS_EXCLUSION relationships: {has_exclusion[0]['count']}")
    
    follows_guideline = kg.run_query("MATCH ()-[r:FOLLOWS_GUIDELINE]->() RETURN count(r) as count", {})
    logger.info(f"  FOLLOWS_GUIDELINE relationships: {follows_guideline[0]['count']}")
    
    has_best_practices = kg.run_query("MATCH ()-[r:HAS_BEST_PRACTICES]->() RETURN count(r) as count", {})
    logger.info(f"  HAS_BEST_PRACTICES relationships: {has_best_practices[0]['count']}")


def test_code_retrieval():
    """Test retrieving specific code sets"""
    logger.info("\n" + "="*80)
    logger.info("TESTING CODE RETRIEVAL")
    logger.info("="*80)
    
    # Get BCS mammography codes
    logger.info("\n--- BCS Mammography CPT Codes ---")
    measure = get_measure_comprehensive("BCS")
    mammo_codes = measure["code_sets"].get("mammography_cpt", [])
    logger.info(f"  Found {len(mammo_codes)} codes: {', '.join(mammo_codes)}")
    
    # Get COL colonoscopy codes
    logger.info("\n--- COL Colonoscopy CPT Codes ---")
    measure = get_measure_comprehensive("COL")
    colo_codes = measure["code_sets"].get("colonoscopy_cpt", [])
    logger.info(f"  Found {len(colo_codes)} codes: {', '.join(colo_codes[:10])}... (showing first 10)")
    
    # Get CDC-HbA1c codes
    logger.info("\n--- CDC-HbA1c Test CPT Codes ---")
    measure = get_measure_comprehensive("CDC-HbA1c")
    hba1c_codes = measure["code_sets"].get("hba1c_cpt", [])
    logger.info(f"  Found {len(hba1c_codes)} codes: {', '.join(hba1c_codes)}")


if __name__ == "__main__":
    try:
        test_node_counts()
        test_measure_structure()
        test_code_retrieval()
        test_exclusion_checking()
        
        logger.info("\n" + "="*80)
        logger.info("✓ ALL TESTS COMPLETED")
        logger.info("="*80)
        
    except Exception as e:
        logger.error(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
