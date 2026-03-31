"""
HEDIS Golden Reference Data - Comprehensive Clinical Guidelines
This module contains authoritative HEDIS measure definitions with:
- Detailed eligibility criteria and age stratifications
- Complete code sets (CPT, HCPCS, ICD-10, LOINC)
- Required and optional exclusions
- Clinical documentation guidelines
- Best practices and measure tips
"""

HEDIS_MEASURES = {
    "BCS": {
        "measure_id": "BCS",
        "name": "Breast Cancer Screening",
        "description": "The percentage of members who were screened for breast cancer with a mammogram",
        "age_range": "42-74",
        "min_age": 42,
        "max_age": 74,
        "lookback_months": 24,
        "lookback_description": "October 1 two years prior to measurement year through December 31 of measurement year",
        "gender_requirement": "Female",
        "product_lines": ["Advantage MD", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "October 1, two years prior through December 31 of measurement year",
        
        "numerator_criteria": "One or more mammograms (bilateral or unilateral) during measurement period",
        "denominator_criteria": "Women 42-74 years recommended for routine breast cancer screening",
        
        "codes": {
            "mammography_cpt": ["77061", "77062", "77063", "77065", "77066", "77067"],
            "mammography_loinc": ["86463-7", "72139-9", "91519-9", "91522-3", "72142-3", "72138-1", 
                                  "91518-1", "91521-5", "72141-5", "72137-3", "91517-3", "91520-7", 
                                  "72140-7", "86462-9", "103892-6", "38090-7", "26346-7", "48475-8"]
        },
        
        "exclusions": {
            "required": [
                {
                    "type": "bilateral_mastectomy",
                    "description": "Bilateral mastectomy anytime in member's history",
                    "icd10": ["Z90.13"],
                    "icd10pcs": ["0HTV0ZZ"],
                    "criteria": "Documentation must indicate mastectomy on both left and right side"
                },
                {
                    "type": "unilateral_mastectomy_both_sides",
                    "description": "Unilateral mastectomy on both left and right sides",
                    "cpt": ["19180", "19200", "19220", "19240", "19303", "19304", "19305", "19306", "19307"],
                    "modifiers": ["50", "LT", "RT"],
                    "icd10": ["Z90.11", "Z90.12"],
                    "icd10pcs": ["0HTU0ZZ", "0HTT0ZZ"]
                },
                {
                    "type": "gender_affirming_surgery",
                    "description": "Gender-affirming chest surgery with gender dysphoria diagnosis",
                    "cpt": ["19318"],
                    "icd10": ["F64.1", "F64.2", "F64.8", "F64.9", "Z87.890"]
                },
                {
                    "type": "hospice",
                    "description": "Hospice or using hospice services during measurement year"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year",
                    "hcpcs": ["G9054", "M1017"],
                    "icd10": ["Z51.5"]
                },
                {
                    "type": "deceased",
                    "description": "Members who died during measurement year"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term in institution"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66+ with frailty AND advanced illness"
                }
            ]
        },
        
        "clinical_guidelines": {
            "acceptable": [
                "Bilateral or unilateral mammogram performed during measurement period",
                "Documentation 'mammogram completed' with date",
                "Member reported services recorded and dated in legal health record",
                "Types: Screening, Diagnostic, Film, Digital, or Digital Breast Tomosynthesis (3D)",
                "Result not required if type and date documented in medical history"
            ],
            "not_acceptable": [
                "Biopsies, Breast Ultrasounds or MRIs alone",
                "CAD (Computer-Aided Detection) without actual mammogram"
            ]
        },
        
        "best_practices": [
            "Educate female patients about importance of screening at least every other year",
            "Provide list of mammography facilities and mobile units",
            "Document date of last screening mammogram at annual visit",
            "Document bilateral or unilateral mastectomies",
            "Scan mammography report into medical record",
            "Contact patients by phone, email, text",
            "Display posters in waiting/examination rooms",
            "Add ticklers to EMR for advanced illness and frailty exclusions"
        ]
    },
    
    "COL": {
        "measure_id": "COL",
        "name": "Colorectal Cancer Screening",
        "description": "The percentage of members who had appropriate screening for colorectal cancer",
        "age_range": "45-75",
        "min_age": 45,
        "max_age": 75,
        "gender_requirement": "Any",
        "product_lines": ["Advantage MD", "D-SNP", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement period and year prior",
        
        "screening_options": [
            {
                "type": "colonoscopy",
                "lookback_months": 120,
                "description": "Colonoscopy during MY or 9 years prior"
            },
            {
                "type": "flexible_sigmoidoscopy",
                "lookback_months": 48,
                "description": "Flexible sigmoidoscopy during MY or 4 years prior"
            },
            {
                "type": "ct_colonography",
                "lookback_months": 48,
                "description": "CT colonography during MY or 4 years prior"
            },
            {
                "type": "fit_dna",
                "lookback_months": 24,
                "description": "FIT-DNA test (Cologuard) during MY or 2 years prior"
            },
            {
                "type": "fobt",
                "lookback_months": 12,
                "description": "Fecal occult blood test during MY"
            }
        ],
        
        "codes": {
            "colonoscopy_cpt": ["44388", "44389", "44390", "44391", "44392", "44394", 
                                "44401", "44402", "44403", "44404", "44405", "44406", "44407", "44408",
                                "45378", "45379", "45380", "45381", "45382", "45384", "45385", "45386",
                                "45388", "45389", "45390", "45391", "45392", "45393", "45398"],
            "colonoscopy_hcpcs": ["G0105", "G0121"],
            
            "flexible_sigmoidoscopy_cpt": ["45330", "45331", "45332", "45333", "45334", "45335",
                                            "45337", "45338", "45340", "45341", "45342", "45346",
                                            "45347", "45349", "45350"],
            "flexible_sigmoidoscopy_hcpcs": ["G0104"],
            
            "ct_colonography_cpt": ["74261", "74262", "74263"],
            
            "fit_dna_cpt": ["81528", "0464U"],
            
            "fobt_guaiac_cpt": ["82270"],
            "fobt_fit_cpt": ["82274"],
            "fobt_fit_hcpcs": ["G0328"]
        },
        
        "exclusions": {
            "required": [
                {
                    "type": "colorectal_cancer",
                    "description": "History of colorectal cancer",
                    "icd10": ["C18.0", "C18.1", "C18.2", "C18.3", "C18.4", "C18.5", "C18.6", 
                             "C18.7", "C18.8", "C18.9", "C19", "C20", "C21.2", "C21.8", 
                             "C78.5", "Z85.038", "Z85.048"]
                },
                {
                    "type": "total_colectomy",
                    "description": "Total colectomy (partial or hemicolectomies do not count)",
                    "cpt": ["44150", "44151", "44152", "44153", "44155", "44156", "44157", "44158",
                           "44210", "44211", "44212"],
                    "icd10pcs": ["0DTE0ZZ", "0DTE4ZZ", "0DTE7ZZ", "0DTE8ZZ"],
                    "hcpcs": ["G0328"]
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Members who died during measurement year"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66+ with frailty AND advanced illness"
                }
            ]
        },
        
        "clinical_guidelines": {
            "acceptable": [
                "Inpatient or outpatient procedures",
                "Member reported services recorded and dated in legal health record",
                "Documentation 'Colon Cancer Screening Done in 2025' counts as FOBT",
                "Colonoscopy/sigmoidoscopy reports indicating complete exam",
                "Scope advanced to cecum = colonoscopy",
                "Scope advanced to sigmoid colon = flexible sigmoidoscopy",
                "FIT test: any number of samples returned meets criteria",
                "gFOBT: 3 or more samples required (if unspecified, assume correct number)"
            ],
            "not_acceptable": [
                "Tests performed in office or from digital rectal exam (DRE)",
                "CT scan of abdomen/pelvis (not same as CT colonography)",
                "Unclear documentation 'COL' or 'COLON 20XX' without test type",
                "Poor bowel prep or incomplete exam without scope advancement documentation",
                "gFOBT with only 1-2 samples returned"
            ]
        },
        
        "best_practices": [
            "Best practice to have actual screening test and result",
            "Include date of service and place of service if known",
            "Member refusal does not make them ineligible",
            "Educate about importance of early detection",
            "Have FIT kits available with return instructions",
            "Update member's history annually with type and date of screening",
            "Document history of total colectomy or colon cancer"
        ]
    },
    
    "CCS": {
        "measure_id": "CCS",
        "name": "Cervical Cancer Screening",
        "description": "The percentage of members screened for cervical cancer with age-appropriate cervical cytology and/or hrHPV testing",
        "age_range": "21-64",
        "min_age": 21,
        "max_age": 64,
        "gender_requirement": "Female",
        "product_lines": ["EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement year and 2 years prior (Commercial); Measurement year only (Medicaid)",
        
        "screening_options": [
            {
                "type": "cervical_cytology",
                "age_range": "24-64",
                "lookback_months": 36,
                "description": "Cervical cytology every 3 years (requires 21+ on test date)"
            },
            {
                "type": "hrhpv_testing",
                "age_range": "30-64",
                "lookback_months": 60,
                "description": "hrHPV testing every 5 years (requires 30+ on test date)"
            },
            {
                "type": "cotesting",
                "age_range": "30-64",
                "lookback_months": 60,
                "description": "Cervical cytology/hrHPV co-testing every 5 years (requires 30+ on test date)"
            }
        ],
        
        "codes": {
            "cervical_cytology_cpt": ["88141", "88142", "88143", "88147", "88148", "88150", 
                                      "88152", "88153", "88164", "88165", "88166", "88167", 
                                      "88174", "88175"],
            "cervical_cytology_hcpcs": ["G0123", "G0124", "G0141", "G0143", "G0144", "G0145", 
                                        "G0147", "G0148", "P3000", "P3001"],
            "cervical_cytology_loinc": ["104866-9", "10524-7", "18500-9", "19762-4", "19765-7", 
                                        "19766-5", "19774-9", "33717-0", "47527-7", "47528-5"],
            
            "hrhpv_cpt": ["87624", "87625", "87626", "0502U"],
            "hrhpv_hcpcs": ["G0476"],
            "hrhpv_loinc": ["104132-6", "104170-6", "104752-1", "104766-1", "104783-6", 
                           "21440-3", "30167-1", "38372-9", "59263-4", "59264-2", "59420-0"]
        },
        
        "exclusions": {
            "required": [
                {
                    "type": "hysterectomy_no_cervix",
                    "description": "Hysterectomy with no residual cervix",
                    "cpt": ["57530", "57531", "57540", "57545", "57550", "57555", "57556",
                           "58150", "58152", "58200", "58210", "58240", "58260", "58262",
                           "58263", "58267", "58270", "58275", "58280", "58285",
                           "58290", "58291", "58292", "58293", "58294", "58548", "58550",
                           "58552", "58553", "58554", "58570", "58571", "58572", "58573",
                           "58575", "58951", "58953", "58954", "59856", "59135"],
                    "icd10": ["Q51.5", "Z90.710", "Z90.712"],
                    "icd10pcs": ["0UTC0ZZ", "0UTC4ZZ", "0UTC7ZZ", "0UTC8ZZ"]
                },
                {
                    "type": "sex_assigned_male",
                    "description": "Members with sex assigned male at birth",
                    "loinc_code": "76689-9",
                    "loinc_value": "LA2-8"
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Members who died during measurement year"
                }
            ]
        },
        
        "clinical_guidelines": {
            "acceptable": [
                "Member reported information with date and result documented by care provider",
                "Generic 'HPV test' counts as hrHPV test",
                "Lab results with 'no endocervical cells' if valid result reported",
                "Lab test wording 'Ecto/Endo/Vaginal Pool: liquid based'",
                "Any cervical cancer screening with collection and microscopic analysis",
                "Documentation 'Pap Smear/hrHPV done Jan 20XX-negative' with date",
                "Health Maintenance section if test date and result noted",
                "Documentation of 'vaginal Pap smear' with hysterectomy documentation",
                "Documentation of 'complete', 'total', or 'radical' hysterectomy"
            ],
            "not_acceptable": [
                "Biopsies or inadequate sample/no cervical cells",
                "Biopsies are diagnostic, not screening",
                "Referral to OB/GYN alone",
                "hrHPV DNA reflex test ordered but not performed",
                "Documentation of hysterectomy alone (doesn't indicate cervix removed)",
                "Supracervical hysterectomy (cervix remains intact)"
            ]
        },
        
        "best_practices": [
            "All tests require date and result",
            "Request results for tests performed by another provider",
            "Complete test during well woman visit, sick visits, UTI or STD screening",
            "Review and document surgical and preventive screening history",
            "Use correct diagnosis and procedure codes",
            "Applies to all with cervix regardless of sexual history or HPV vaccination",
            "Transgender patients with cervix need regular pap tests"
        ]
    },
    
    "CDC-HbA1c": {
        "measure_id": "CDC-HbA1c",
        "name": "Diabetes Care - HbA1c Testing",
        "description": "The percentage of members with diabetes who had HbA1c testing during measurement year",
        "age_range": "18-75",
        "min_age": 18,
        "max_age": 75,
        "lookback_months": 12,
        "gender_requirement": "Any",
        "diagnosis_requirement": "Type 1 or Type 2 Diabetes (ICD-10 E10.x, E11.x, E13.x)",
        "product_lines": ["All"],
        
        "numerator_criteria": "One or more HbA1c tests during measurement year",
        "denominator_criteria": "Members 18-75 with diabetes diagnosis",
        
        "performance_levels": [
            {
                "level": "HbA1c Control (<8.0%)",
                "description": "Percentage with HbA1c <8.0%",
                "better_performance": "Higher rate"
            },
            {
                "level": "HbA1c Poor Control (>9.0%)",
                "description": "Percentage with HbA1c >9.0%",
                "better_performance": "Lower rate"
            }
        ],
        
        "codes": {
            "hba1c_cpt": ["83036", "83037"],
            "hba1c_cat2": {
                "less_than_7": "3044F",
                "7_to_8": "3051F",
                "8_to_9": "3052F",
                "less_than_9": "3046F"
            },
            "diabetes_icd10": ["E10.9", "E11.9", "E13.9"],
            "diabetes_with_complications": ["E10.x", "E11.x", "E13.x"]
        },
        
        "exclusions": {
            "required": [
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Members who died during measurement year"
                }
            ],
            "optional": [
                {
                    "type": "polycystic_ovarian_syndrome",
                    "description": "Diagnosis during measurement year"
                },
                {
                    "type": "gestational_diabetes",
                    "description": "Diagnosis during measurement year"
                },
                {
                    "type": "steroid_induced_diabetes",
                    "description": "Diagnosis during measurement year"
                }
            ]
        },
        
        "clinical_guidelines": {
            "acceptable": [
                "HbA1c lab test with result during measurement year",
                "Remote measurements by any digital device",
                "Member reported HbA1c documented in medical record"
            ],
            "not_acceptable": [
                "Missing result",
                "Test ordered but not performed"
            ]
        },
        
        "best_practices": [
            "Order HbA1c test at least annually for all diabetic patients",
            "Document test results in structured format",
            "Use CPT Category II codes for performance tracking",
            "Review trends over time for diabetes management",
            "Coordinate with endocrinology for poor control cases"
        ]
    }
}


def get_measure_definition(measure_id: str):
    """Get complete measure definition by ID"""
    return HEDIS_MEASURES.get(measure_id)


def get_all_measures():
    """Get all HEDIS measure definitions"""
    return HEDIS_MEASURES


def get_measure_codes(measure_id: str, code_type: str = None):
    """
    Get codes for a specific measure
    code_type: 'cpt', 'hcpcs', 'icd10', 'loinc', or None for all
    """
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return {}
    
    codes = measure.get("codes", {})
    if code_type:
        return {k: v for k, v in codes.items() if code_type.lower() in k.lower()}
    return codes


def get_measure_exclusions(measure_id: str):
    """Get exclusion criteria for a specific measure"""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return {}
    return measure.get("exclusions", {})


def get_clinical_guidelines(measure_id: str):
    """Get clinical documentation guidelines for a specific measure"""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return {}
    return measure.get("clinical_guidelines", {})


def get_best_practices(measure_id: str):
    """Get best practices for a specific measure"""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return []
    return measure.get("best_practices", [])
