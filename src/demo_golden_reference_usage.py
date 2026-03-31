"""
Demonstration: How AI Agents Use Comprehensive Golden Reference

This script shows how the care gap validation agents will reference:
- Code sets (CPT, HCPCS, ICD-10, LOINC)
- Exclusion criteria
- Clinical guidelines (acceptable/not acceptable documentation)
- Best practices
- Screening options with different lookback periods

When validating a member's care gap.
"""
import sys
import logging
from src.care_gap_neo4j import (
    get_measure_comprehensive,
    check_member_exclusions,
    get_member_claims_cpt_codes,
    get_member_profile
)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def demonstrate_bcs_validation(member_id: str):
    """
    Demonstrate BCS (Breast Cancer Screening) validation using golden reference.
    Shows how agent checks codes, exclusions, and provides guidance.
    """
    logger.info("\n" + "="*80)
    logger.info(f"DEMONSTRATING BCS VALIDATION FOR MEMBER {member_id}")
    logger.info("="*80)
    
    # Step 1: Get member profile
    profile = get_member_profile(member_id)
    logger.info(f"\n📋 Member Profile:")
    logger.info(f"   Name: {profile['name']}")
    logger.info(f"   Age: {profile['age_str']}")
    logger.info(f"   Gender: {profile['gender']}")
    logger.info(f"   Plan: {profile['plan_id']}")
    logger.info(f"   PCP: {profile['pcp_name']} ({profile['pcp_specialty']})")
    
    # Step 2: Get comprehensive BCS measure definition
    bcs_measure = get_measure_comprehensive("BCS")
    logger.info(f"\n📚 Golden Reference: {bcs_measure['name']}")
    logger.info(f"   Eligibility: {bcs_measure['age_range']}, {bcs_measure['gender_requirement']}")
    logger.info(f"   Lookback Period: {bcs_measure['lookback_months']} months")
    logger.info(f"   Numerator: {bcs_measure['numerator_criteria']}")
    
    # Step 3: Show required CPT codes from golden reference
    mammo_cpt = bcs_measure['code_sets'].get('mammography_cpt', [])
    logger.info(f"\n✅ Required CPT Codes (from golden reference):")
    logger.info(f"   {', '.join(mammo_cpt)}")
    
    # Step 4: Get member's claims
    claims = get_member_claims_cpt_codes(member_id)
    logger.info(f"\n🔍 Member's Claims:")
    if claims:
        for claim in claims[:5]:  # Show first 5
            logger.info(f"   - CPT {claim['cpt_code']} on {claim['service_date']}")
    else:
        logger.info("   No claims found")
    
    # Step 5: Check exclusions
    exclusions = check_member_exclusions(member_id, "BCS")
    logger.info(f"\n🚫 Exclusion Check:")
    if exclusions:
        logger.info(f"   ❌ Member has {len(exclusions)} exclusion(s):")
        for excl in exclusions:
            logger.info(f"      - {excl['type']}: {excl['description']}")
    else:
        logger.info(f"   ✓ No exclusions - member is eligible")
    
    # Step 6: Show clinical guidelines from golden reference
    guidelines = bcs_measure['clinical_guidelines']
    logger.info(f"\n📖 Clinical Documentation Guidelines (from golden reference):")
    logger.info(f"   Acceptable Documentation:")
    for item in guidelines['acceptable'][:3]:
        logger.info(f"      ✓ {item}")
    logger.info(f"   Not Acceptable:")
    for item in guidelines['not_acceptable']:
        logger.info(f"      ✗ {item}")
    
    # Step 7: Show best practices
    best_practices = bcs_measure['best_practices']
    logger.info(f"\n💡 Best Practices for Care Manager (from golden reference):")
    for practice in best_practices[:4]:
        logger.info(f"   • {practice}")
    
    # Step 8: Validation logic (what agent will do)
    logger.info(f"\n🤖 Agent Validation Logic:")
    member_cpt_codes = [c['cpt_code'] for c in claims]
    has_mammogram = any(code in mammo_cpt for code in member_cpt_codes)
    
    if exclusions:
        logger.info(f"   ❌ GAP CLOSED - Member is excluded from measure")
    elif has_mammogram:
        logger.info(f"   ✅ GAP CLOSED - Member has qualifying mammogram")
    else:
        logger.info(f"   ⚠️  GAP OPEN - Member needs mammogram")
        logger.info(f"   📞 Recommended Action: Contact member to schedule mammogram")
        logger.info(f"   🏥 Required Service: Any of these CPT codes: {', '.join(mammo_cpt)}")


def demonstrate_col_validation(member_id: str):
    """
    Demonstrate COL (Colorectal Cancer Screening) validation.
    Shows multiple screening options with different lookback periods.
    """
    logger.info("\n" + "="*80)
    logger.info(f"DEMONSTRATING COL VALIDATION FOR MEMBER {member_id}")
    logger.info("="*80)
    
    # Get member profile
    profile = get_member_profile(member_id)
    logger.info(f"\n📋 Member: {profile['name']}, {profile['age_str']}, {profile['gender']}")
    
    # Get COL measure
    col_measure = get_measure_comprehensive("COL")
    logger.info(f"\n📚 Golden Reference: {col_measure['name']}")
    logger.info(f"   Eligibility: {col_measure['age_range']}, {col_measure['gender_requirement']}")
    
    # Show screening options (COL has multiple options)
    screening_options = col_measure['screening_options']
    logger.info(f"\n🔬 Screening Options (from golden reference):")
    for option in screening_options:
        logger.info(f"   • {option['type'].upper()}: {option['description']}")
        logger.info(f"     Lookback: {option['lookback_months']} months")
    
    # Show code sets for each option
    logger.info(f"\n✅ Required Codes by Screening Type:")
    code_sets = col_measure['code_sets']
    logger.info(f"   Colonoscopy CPT: {len(code_sets.get('colonoscopy_cpt', []))} codes")
    logger.info(f"   Flexible Sigmoidoscopy CPT: {len(code_sets.get('flexible_sigmoidoscopy_cpt', []))} codes")
    logger.info(f"   CT Colonography CPT: {len(code_sets.get('ct_colonography_cpt', []))} codes")
    logger.info(f"   FIT-DNA CPT: {len(code_sets.get('fit_dna_cpt', []))} codes")
    logger.info(f"   FOBT CPT: {len(code_sets.get('fobt_fit_cpt', []))} codes")
    
    # Show exclusions
    exclusions_list = col_measure['exclusions']
    logger.info(f"\n🚫 Exclusion Criteria (from golden reference):")
    for excl in exclusions_list[:3]:
        logger.info(f"   • {excl['type']}: {excl['description']}")
    
    # Show clinical guidelines
    guidelines = col_measure['clinical_guidelines']
    logger.info(f"\n📖 Clinical Guidelines:")
    logger.info(f"   Key Acceptable Documentation:")
    for item in guidelines['acceptable'][:3]:
        logger.info(f"      ✓ {item}")
    
    logger.info(f"\n🤖 Agent Will Check:")
    logger.info(f"   1. Member age 45-75? → Eligible")
    logger.info(f"   2. Has colorectal cancer history? → Excluded")
    logger.info(f"   3. Has total colectomy? → Excluded")
    logger.info(f"   4. Has colonoscopy in last 10 years? → Gap closed")
    logger.info(f"   5. Has sigmoidoscopy in last 5 years? → Gap closed")
    logger.info(f"   6. Has FOBT in last 1 year? → Gap closed")
    logger.info(f"   7. None of above? → Gap open, recommend screening")


def demonstrate_exclusion_validation(member_id: str):
    """
    Demonstrate how exclusion checking works with golden reference.
    """
    logger.info("\n" + "="*80)
    logger.info(f"DEMONSTRATING EXCLUSION VALIDATION FOR MEMBER {member_id}")
    logger.info("="*80)
    
    profile = get_member_profile(member_id)
    logger.info(f"\n📋 Member: {profile['name']}")
    
    measures = ["BCS", "COL", "CCS", "CDC-HbA1c"]
    
    for measure_id in measures:
        measure = get_measure_comprehensive(measure_id)
        logger.info(f"\n--- {measure['name']} ---")
        
        # Check exclusions
        exclusions = check_member_exclusions(member_id, measure_id)
        
        if exclusions:
            logger.info(f"   ❌ Member has {len(exclusions)} exclusion(s):")
            for excl in exclusions:
                logger.info(f"      • {excl['type']}")
                logger.info(f"        {excl['description']}")
                if excl.get('cpt_codes'):
                    logger.info(f"        Matched CPT: {', '.join(excl['cpt_codes'][:3])}")
                if excl.get('icd10_codes'):
                    logger.info(f"        Matched ICD-10: {', '.join(excl['icd10_codes'][:3])}")
        else:
            logger.info(f"   ✓ No exclusions - member is eligible")


if __name__ == "__main__":
    logger.info("\n" + "="*80)
    logger.info("COMPREHENSIVE GOLDEN REFERENCE DEMONSTRATION")
    logger.info("How AI Agents Use HEDIS Guidelines for Care Gap Validation")
    logger.info("="*80)
    
    # Demonstrate BCS validation for member M0011 (42F with open BCS gap)
    demonstrate_bcs_validation("M0011")
    
    # Demonstrate COL validation for member M0009 (71F)
    demonstrate_col_validation("M0009")
    
    # Demonstrate exclusion checking
    demonstrate_exclusion_validation("M0011")
    
    logger.info("\n" + "="*80)
    logger.info("✓ DEMONSTRATION COMPLETE")
    logger.info("="*80)
    logger.info("\nKey Takeaways:")
    logger.info("1. Golden reference contains ALL HEDIS rules (codes, exclusions, guidelines)")
    logger.info("2. Agents query Neo4j to get comprehensive measure definitions")
    logger.info("3. Validation logic references golden reference for:")
    logger.info("   - Required CPT/HCPCS/ICD-10/LOINC codes")
    logger.info("   - Exclusion criteria with specific codes")
    logger.info("   - Clinical documentation standards")
    logger.info("   - Best practices for care managers")
    logger.info("   - Multiple screening options with different lookback periods")
    logger.info("4. Agents provide specific, actionable guidance based on golden reference")
    logger.info("5. All validation decisions are traceable to authoritative HEDIS guidelines")
