# Golden Reference Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         HEDIS GOLDEN REFERENCE SYSTEM                        │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: SOURCE DATA (Python Dictionary)                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  hedis_golden_reference.py                                                   │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ HEDIS_MEASURES = {                                                  │    │
│  │   "BCS": {                                                          │    │
│  │     "measure_id": "BCS",                                            │    │
│  │     "name": "Breast Cancer Screening",                              │    │
│  │     "age_range": "42-74", "gender": "Female",                       │    │
│  │     "codes": {                                                      │    │
│  │       "mammography_cpt": ["77061", "77062", ...],                   │    │
│  │       "mammography_loinc": ["86463-7", ...]                         │    │
│  │     },                                                              │    │
│  │     "exclusions": {                                                 │    │
│  │       "required": [                                                 │    │
│  │         {"type": "bilateral_mastectomy", "icd10": ["Z90.13"], ...} │    │
│  │       ]                                                             │    │
│  │     },                                                              │    │
│  │     "clinical_guidelines": {                                        │    │
│  │       "acceptable": [...], "not_acceptable": [...]                  │    │
│  │     },                                                              │    │
│  │     "best_practices": [...]                                         │    │
│  │   },                                                                │    │
│  │   "COL": {...}, "CCS": {...}, "CDC-HbA1c": {...}                   │    │
│  │ }                                                                   │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
                          care_gap_data_loader.py
                    merge_quality_measure_comprehensive()
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: NEO4J GRAPH DATABASE (Structured Nodes & Relationships)            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      QualityMeasure (4 nodes)                         │  │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────┐                 │  │
│  │  │  BCS   │  │  COL   │  │  CCS   │  │ CDC-HbA1c  │                 │  │
│  │  └───┬────┘  └───┬────┘  └───┬────┘  └─────┬──────┘                 │  │
│  │      │           │           │              │                         │  │
│  └──────┼───────────┼───────────┼──────────────┼─────────────────────────┘  │
│         │           │           │              │                            │
│    ┌────┴────┬──────┴─────┬─────┴────┬─────────┴────┐                      │
│    │         │            │          │              │                      │
│    ↓         ↓            ↓          ↓              ↓                      │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ REQUIRES_CODES                                                       │  │
│  │ ┌──────────────────────────────────────────────────────────────┐    │  │
│  │ │ CodeSet (20 nodes)                                            │    │  │
│  │ │ • BCS_mammography_cpt: [77061, 77062, 77063, ...]            │    │  │
│  │ │ • BCS_mammography_loinc: [86463-7, 72139-9, ...]             │    │  │
│  │ │ • COL_colonoscopy_cpt: [44388, 44389, ..., 45398]            │    │  │
│  │ │ • COL_flexible_sigmoidoscopy_cpt: [45330, ..., 45350]        │    │  │
│  │ │ • COL_fobt_fit_cpt: [82274]                                  │    │  │
│  │ │ • CCS_cervical_cytology_cpt: [88141, 88142, ...]             │    │  │
│  │ │ • CCS_hrhpv_cpt: [87624, 87625, 87626, 0502U]                │    │  │
│  │ │ • CDC_hba1c_cpt: [83036, 83037]                              │    │  │
│  │ └──────────────────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ HAS_EXCLUSION                                                        │  │
│  │ ┌──────────────────────────────────────────────────────────────┐    │  │
│  │ │ ExclusionCriteria (26 nodes)                                  │    │  │
│  │ │ • BCS_bilateral_mastectomy_required                           │    │  │
│  │ │   - icd10: [Z90.13], icd10pcs: [0HTV0ZZ]                      │    │  │
│  │ │ • BCS_unilateral_mastectomy_both_sides_required               │    │  │
│  │ │   - cpt: [19180, 19200, ...], modifiers: [50, LT, RT]         │    │  │
│  │ │ • COL_colorectal_cancer_required                              │    │  │
│  │ │   - icd10: [C18.0-C18.9, C19, C20, ...]                       │    │  │
│  │ │ • COL_total_colectomy_required                                │    │  │
│  │ │   - cpt: [44150-44158, 44210-44212]                           │    │  │
│  │ │ • CCS_hysterectomy_no_cervix_required                         │    │  │
│  │ │   - cpt: [57530, 57531, ...], icd10: [Q51.5, Z90.710, ...]    │    │  │
│  │ │ • All measures: hospice, palliative_care, deceased, frailty   │    │  │
│  │ └──────────────────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ FOLLOWS_GUIDELINE                                                    │  │
│  │ ┌──────────────────────────────────────────────────────────────┐    │  │
│  │ │ ClinicalGuideline (4 nodes)                                   │    │  │
│  │ │ • BCS_clinical_guidelines                                     │    │  │
│  │ │   - acceptable: ["Bilateral/unilateral mammogram", ...]       │    │  │
│  │ │   - not_acceptable: ["Biopsies, Ultrasounds", ...]            │    │  │
│  │ │ • COL_clinical_guidelines                                     │    │  │
│  │ │   - acceptable: ["Inpatient/outpatient procedures", ...]      │    │  │
│  │ │   - not_acceptable: ["Office DRE", "CT abdomen", ...]         │    │  │
│  │ └──────────────────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ HAS_BEST_PRACTICES                                                   │  │
│  │ ┌──────────────────────────────────────────────────────────────┐    │  │
│  │ │ BestPractices (4 nodes)                                       │    │  │
│  │ │ • BCS_best_practices                                          │    │  │
│  │ │   - ["Educate about screening", "Provide facility list", ...] │    │  │
│  │ │ • COL_best_practices                                          │    │  │
│  │ │   - ["Have FIT kits available", "Update history annually", ...]│    │  │
│  │ └──────────────────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ HAS_SCREENING_OPTION                                                 │  │
│  │ ┌──────────────────────────────────────────────────────────────┐    │  │
│  │ │ ScreeningOption (8 nodes)                                     │    │  │
│  │ │ • COL_colonoscopy: 120 months lookback                        │    │  │
│  │ │ • COL_flexible_sigmoidoscopy: 48 months lookback              │    │  │
│  │ │ • COL_ct_colonography: 48 months lookback                     │    │  │
│  │ │ • COL_fit_dna: 24 months lookback                             │    │  │
│  │ │ • COL_fobt: 12 months lookback                                │    │  │
│  │ │ • CCS_cervical_cytology: 36 months lookback                   │    │  │
│  │ │ • CCS_hrhpv_testing: 60 months lookback                       │    │  │
│  │ │ • CCS_cotesting: 60 months lookback                           │    │  │
│  │ └──────────────────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
                          care_gap_neo4j.py (Query Functions)
                    get_measure_comprehensive(measure_id)
                    check_member_exclusions(member_id, measure_id)
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: AI AGENTS (AutoGen SelectorGroupChat)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ care_gap_validator                                                  │    │
│  │ ┌────────────────────────────────────────────────────────────────┐ │    │
│  │ │ 1. Get measure definition from golden reference                 │ │    │
│  │ │    measure = get_measure_comprehensive("BCS")                   │ │    │
│  │ │                                                                  │ │    │
│  │ │ 2. Check member eligibility (age, gender, diagnosis)            │ │    │
│  │ │    if age < measure['min_age'] or age > measure['max_age']:     │ │    │
│  │ │        return "Not eligible"                                    │ │    │
│  │ │                                                                  │ │    │
│  │ │ 3. Check exclusions from golden reference                       │ │    │
│  │ │    exclusions = check_member_exclusions(member_id, "BCS")       │ │    │
│  │ │    if exclusions:                                               │ │    │
│  │ │        return f"Excluded: {exclusions[0]['description']}"       │ │    │
│  │ │                                                                  │ │    │
│  │ │ 4. Get required codes from golden reference                     │ │    │
│  │ │    required_codes = measure['code_sets']['mammography_cpt']     │ │    │
│  │ │                                                                  │ │    │
│  │ │ 5. Check member's claims against required codes                 │ │    │
│  │ │    claims = get_member_claims_cpt_codes(member_id)              │ │    │
│  │ │    if any(claim['cpt_code'] in required_codes):                 │ │    │
│  │ │        return "GAP CLOSED"                                      │ │    │
│  │ │    else:                                                        │ │    │
│  │ │        return f"GAP OPEN - Needs: {required_codes}"             │ │    │
│  │ └────────────────────────────────────────────────────────────────┘ │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ outreach_advisor                                                    │    │
│  │ ┌────────────────────────────────────────────────────────────────┐ │    │
│  │ │ 1. Get best practices from golden reference                     │ │    │
│  │ │    measure = get_measure_comprehensive("BCS")                   │ │    │
│  │ │    best_practices = measure['best_practices']                   │ │    │
│  │ │                                                                  │ │    │
│  │ │ 2. Generate outreach plan based on best practices               │ │    │
│  │ │    for practice in best_practices:                              │ │    │
│  │ │        outreach_plan.append(practice)                           │ │    │
│  │ │                                                                  │ │    │
│  │ │ 3. Prioritize by lookback urgency                               │ │    │
│  │ │    if lookback_months < 12: priority = "URGENT"                 │ │    │
│  │ │                                                                  │ │    │
│  │ │ 4. Provide specific talking points                              │ │    │
│  │ │    "Member needs mammogram. Required CPT: 77061-77067"          │ │    │
│  │ │    "Refer to in-network radiology facility"                     │ │    │
│  │ └────────────────────────────────────────────────────────────────┘ │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ benefit_checker                                                     │    │
│  │ ┌────────────────────────────────────────────────────────────────┐ │    │
│  │ │ 1. Get measure eligibility rules from golden reference          │ │    │
│  │ │    measure = get_measure_comprehensive("BCS")                   │ │    │
│  │ │    age_range = measure['age_range']                             │ │    │
│  │ │    gender = measure['gender_requirement']                       │ │    │
│  │ │                                                                  │ │    │
│  │ │ 2. Check member's plan coverage                                 │ │    │
│  │ │    plan = get_member_profile(member_id)['plan_id']              │ │    │
│  │ │    if plan.preventive_covered:                                  │ │    │
│  │ │        return "$0 copay for preventive screening"               │ │    │
│  │ │                                                                  │ │    │
│  │ │ 3. Confirm service is covered                                   │ │    │
│  │ │    "Mammogram (CPT 77067) is covered under preventive care"     │ │    │
│  │ └────────────────────────────────────────────────────────────────┘ │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: OUTPUT (Validation Results + Actionable Guidance)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  {                                                                           │
│    "member_id": "M0011",                                                     │
│    "member_name": "Quinn Iyer",                                              │
│    "age": 42,                                                                │
│    "gender": "F",                                                            │
│    "applicable_measures": ["BCS", "CCS"],                                    │
│    "compliant_measures": [],                                                 │
│    "open_gaps_detected": ["BCS", "CCS"],                                     │
│    "agent_responses": {                                                      │
│      "care_gap_validator": "Member M0011 has 2 open gaps: BCS and CCS. \    │
│                             BCS requires mammogram (CPT 77061-77067) \       │
│                             within 24 months. Last mammogram was 10/2023 \   │
│                             which is outside lookback window.",              │
│      "outreach_advisor": "Priority: URGENT. Contact member by phone. \       │
│                           Talking points: 'You're due for your annual \      │
│                           mammogram. We can help schedule at an in-network \ │
│                           facility with $0 copay.' Provide list of \         │
│                           radiology centers.",                               │
│      "benefit_checker": "Mammogram (CPT 77067) is covered as preventive \    │
│                          care under plan PL-001. Member cost: $0 copay, \    │
│                          $0 deductible. Service is fully covered."           │
│    }                                                                         │
│  }                                                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

KEY BENEFITS:
✅ Single source of truth for HEDIS rules
✅ Agents always reference authoritative guidelines
✅ Validation decisions are traceable
✅ Easy to update (change Python dict, reload Neo4j)
✅ Supports complex measures with multiple screening options
✅ Provides actionable guidance based on best practices
```
