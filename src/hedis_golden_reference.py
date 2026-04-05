"""
HEDIS Golden Reference — 2025 NCQA Technical Specifications
Source documents:
  1. 2025-HEDIS-Coding-Guide_3.28.25.pdf  (Medicaid Reference Guide)
  2. 2025-hedis-quality-measures-tip-sheet.pdf  (Quality Measures Toolkit)
  3. MULTI-BC-CR-075425-24-CPN74734-Breast-Cancer-Screening-(BCS-E)-2025-CR_FINAL.pdf

Approach 2 — Rules as Graph:
  Each measure is a node in Neo4j.  When a new patient arrives, run them through
  the rulebook — check eligibility, exclusions, and required codes.

Measures included:
  BCS-E   Breast Cancer Screening
  COL-E   Colorectal Cancer Screening
  CCS-E   Cervical Cancer Screening
  GSD     Glycemic Status Assessment for Patients with Diabetes (HbA1c)
  EED     Eye Exam for Patients with Diabetes
  KED     Kidney Health Evaluation for Patients with Diabetes
  BPD     Blood Pressure Control for Patients with Diabetes
"""

HEDIS_MEASURES = {

    # ─────────────────────────────────────────────────────────────────────────
    # BCS-E  |  Breast Cancer Screening
    # Source: Coding Guide p.8-9 + Tip Sheet p.48-51 + BCS-E flyer
    # ─────────────────────────────────────────────────────────────────────────
    "BCS": {
        "measure_id": "BCS",
        "name": "Breast Cancer Screening",
        "primary_cpt": "77067",        # Bilateral screening mammogram (preferred)
        "primary_icd10": "Z12.31",     # Encounter for screening mammogram
        "description": (
            "Women 52–74 who had a mammogram to screen for breast cancer on or between "
            "October 1 two years prior to the measurement year and December 31 of the "
            "measurement year. To close this gap the member needs a bilateral or unilateral "
            "screening mammogram: CPT 77067 (bilateral, preferred), 77061-77066. "
            "Refer to an In-Network Radiology or Imaging Center."
        ),
        "age_range": "52-74 Female",
        "min_age": 52,
        "max_age": 74,
        "gender_requirement": "Female",
        "lookback_months": 24,
        "lookback_description": "October 1 two years prior through December 31 of measurement year",
        "product_lines": ["Advantage MD", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "October 1 two years prior through December 31 of measurement year",
        "numerator_criteria": "One or more mammograms (bilateral or unilateral) during measurement period",
        "denominator_criteria": "Women 42–74 recommended for routine breast cancer screening",

        "codes": {
            "mammography_cpt": [
                "77061", "77062", "77063", "77065", "77066", "77067"
            ],
            "mammography_loinc": [
                "86463-7", "72139-9", "91519-9", "91522-3", "72142-3", "72138-1",
                "91518-1", "91521-5", "72141-5", "72137-3", "91517-3", "91520-7",
                "72140-7", "86462-9", "103892-6", "38090-7", "26346-7", "48475-8",
                "26349-1", "46351-3", "26287-3", "37554-3", "37543-6", "37006-4",
                "37016-3", "26175-0", "48492-3", "46335-6", "37552-7", "37029-6",
                "37038-7", "36626-0", "38071-7", "42415-0", "37052-8", "36642-7",
                "38091-5", "26347-5", "69150-1", "26350-9", "26289-9", "37005-6",
                "38854-6", "37017-1", "26176-8", "103885-0", "46336-4", "37553-5",
                "37030-4", "38855-3", "36627-8", "38072-5", "42416-8", "37053-6",
                "37768-9", "26348-3", "69259-0", "26351-7", "26291-5", "37773-9",
                "37769-7", "37775-4", "26177-6", "103886-8", "46337-2", "38807-4",
                "37770-5", "37771-3", "37774-7", "38820-7", "37772-1", "46350-5",
                "46356-2", "46338-0", "46339-8", "46380-2", "69251-7"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "bilateral_mastectomy",
                    "description": "History of bilateral mastectomy (ICD Z90.13) or bilateral procedure",
                    "icd10": ["Z90.13"],
                    "icd10pcs": ["0HTV0ZZ"],
                    "criteria": "Documentation must indicate mastectomy on both left and right side"
                },
                {
                    "type": "unilateral_mastectomy_bilateral",
                    "description": "Unilateral mastectomy with bilateral modifier (both sides)",
                    "cpt": ["19180", "19200", "19220", "19240", "19303", "19304", "19305", "19306", "19307"],
                    "modifiers": ["50", "LT", "RT"],
                    "icd10": ["Z90.11", "Z90.12"],
                    "icd10pcs": ["0HTU0ZZ", "0HTT0ZZ"],
                    "criteria": "Two unilateral mastectomies must be 14+ days apart if left/right not specified"
                },
                {
                    "type": "gender_affirming_chest_surgery",
                    "description": "Gender-affirming chest surgery with gender dysphoria diagnosis",
                    "cpt": ["19318"],
                    "icd10": ["F64.1", "F64.2", "F64.8", "F64.9", "Z87.890"],
                    "criteria": "Requires BOTH CPT 19318 AND one ICD-10 code for gender dysphoria"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care encounter during measurement year",
                    "hcpcs": ["G9054", "M1017"],
                    "icd10": ["Z51.5", "Z51.89"],
                    "criteria": "Any palliative care encounter (do not include POS code 81 lab claims)"
                },
                {
                    "type": "hospice",
                    "description": "Hospice or using hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term in institution"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66+ with BOTH frailty AND advanced illness criteria"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "Bilateral or unilateral mammogram performed during measurement period",
                "Documentation 'mammogram completed' and date",
                "Types: Screening, Diagnostic, Film, Digital, Digital Breast Tomosynthesis (3D Mammogram)",
                "Member-reported services recorded and dated in legal health record",
                "Result not required if type and date documented in medical history",
                "Unilateral mammogram acceptable if documentation of unilateral mastectomy present"
            ],
            "not_acceptable": [
                "Biopsies, Breast Ultrasounds or MRIs alone",
                "CAD (Computer-Aided Detection) alone without actual mammogram"
            ]
        },

        "best_practices": [
            "Educate female patients about importance of screening at least every other year",
            "Provide list of mammography facilities and mobile mammography units",
            "Document date of last screening mammogram at annual visit",
            "Document bilateral or unilateral mastectomies (ICD Z90.13 for bilateral absence)",
            "Scan mammography report into the medical record",
            "Contact patients by phone, email, text to schedule overdue screenings",
            "Display posters in waiting/examination rooms",
            "Add EMR ticklers for advanced illness and frailty exclusions"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # COL-E  |  Colorectal Cancer Screening
    # Source: Coding Guide p.7-8 + Tip Sheet p.71-74
    # ─────────────────────────────────────────────────────────────────────────
    "COL": {
        "measure_id": "COL",
        "name": "Colorectal Cancer Screening",
        "primary_cpt": "45378",        # Colonoscopy (gold standard)
        "primary_icd10": "Z12.11",     # Encounter for screening for malignant neoplasm of colon
        "description": (
            "Members 45–75 who received one or more screenings for colorectal cancer. "
            "Multiple acceptable screening types with different lookback windows. "
            "Preferred: Colonoscopy (valid 10 years); Alternative: FIT/FOBT home kit (valid 1 year). "
            "Refer to In-Network Gastroenterology. Outreach: ask preference and schedule accordingly."
        ),
        "age_range": "45-75",
        "min_age": 45,
        "max_age": 75,
        "gender_requirement": "Any",
        "lookback_months": 120,   # max lookback (colonoscopy); per-option checked by screening_options
        "lookback_description": "Colonoscopy: 10 years | Flex sig / CT colonography: 5 years | FIT-DNA: 3 years | FOBT: 1 year",
        "product_lines": ["Advantage MD", "D-SNP", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement period and year prior",
        "numerator_criteria": "One or more appropriate colorectal cancer screenings within required lookback",
        "denominator_criteria": "Members 45–75 as of December 31 of measurement year",

        # Multiple screening options — each with its own lookback
        "screening_options": [
            {
                "type": "colonoscopy",
                "lookback_months": 120,
                "description": "Colonoscopy during MY or 9 years prior",
                "cpt": [
                    "44388", "44389", "44390", "44391", "44392", "44394",
                    "44401", "44402", "44403", "44404", "44405", "44406", "44407", "44408",
                    "45378", "45379", "45380", "45381", "45382", "45384", "45385", "45386",
                    "45388", "45389", "45390", "45391", "45392", "45393", "45398"
                ],
                "hcpcs": ["G0105", "G0121"]
            },
            {
                "type": "flexible_sigmoidoscopy",
                "lookback_months": 60,
                "description": "Flexible sigmoidoscopy during MY or 5 years prior",
                "cpt": [
                    "45330", "45331", "45332", "45333", "45334", "45335",
                    "45337", "45338", "45340", "45341", "45342",
                    "45346", "45347", "45349", "45350"
                ],
                "hcpcs": ["G0104"]
            },
            {
                "type": "ct_colonography",
                "lookback_months": 60,
                "description": "CT colonography (virtual colonoscopy) during MY or 5 years prior",
                "cpt": ["74261", "74262", "74263"]
            },
            {
                "type": "fit_dna",
                "lookback_months": 36,
                "description": "FIT-DNA (Cologuard) during MY or 3 years prior",
                "cpt": ["81528"],
                "hcpcs": ["G0464"]
            },
            {
                "type": "fobt",
                "lookback_months": 12,
                "description": "Fecal occult blood test (gFOBT or FIT/iFOBT) during MY only",
                "cpt": ["82270", "82274"],
                "hcpcs": ["G0328"],
                "loinc": [
                    "104738-0", "12503-9", "12504-7", "14563-1", "14564-9", "14565-6",
                    "2335-8", "27396-1", "27401-9", "27925-7", "27926-5", "29771-3",
                    "56490-6", "56491-4", "57905-2", "58453-2", "80372-6"
                ]
            }
        ],

        # Flat codes for backward-compat gap detection (union of all options)
        "codes": {
            "colonoscopy_cpt": [
                "44388", "44389", "44390", "44391", "44392", "44394",
                "44401", "44402", "44403", "44404", "44405", "44406", "44407", "44408",
                "45378", "45379", "45380", "45381", "45382", "45384", "45385", "45386",
                "45388", "45389", "45390", "45391", "45392", "45393", "45398"
            ],
            "colonoscopy_hcpcs": ["G0105", "G0121"],
            "flexible_sigmoidoscopy_cpt": [
                "45330", "45331", "45332", "45333", "45334", "45335",
                "45337", "45338", "45340", "45341", "45342",
                "45346", "45347", "45349", "45350"
            ],
            "flexible_sigmoidoscopy_hcpcs": ["G0104"],
            "ct_colonography_cpt": ["74261", "74262", "74263"],
            "fit_dna_cpt": ["81528"],
            "fit_dna_hcpcs": ["G0464"],
            "fobt_cpt": ["82270", "82274"],
            "fobt_hcpcs": ["G0328"]
        },

        "exclusions": {
            "required": [
                {
                    "type": "colorectal_cancer",
                    "description": "History of colorectal cancer (cancer of small intestine does not count)",
                    "icd10": [
                        "C18.0", "C18.1", "C18.2", "C18.3", "C18.4", "C18.5", "C18.6",
                        "C18.7", "C18.8", "C18.9", "C19", "C20", "C21.2", "C21.8",
                        "C78.5", "Z85.038", "Z85.048"
                    ]
                },
                {
                    "type": "total_colectomy",
                    "description": "Total colectomy (partial or hemicolectomies do NOT count)",
                    "cpt": [
                        "44150", "44151", "44152", "44153", "44155", "44156",
                        "44157", "44158", "44210", "44211", "44212"
                    ],
                    "icd10pcs": ["0DTE0ZZ", "0DTE4ZZ", "0DTE7ZZ", "0DTE8ZZ"]
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66+ with BOTH frailty AND advanced illness"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "Inpatient or outpatient procedures",
                "Member reported services recorded, dated, maintained in legal health record",
                "Best practice: have actual screening test AND result",
                "Result not required if documentation includes type and date of screening",
                "Documentation 'Colon Cancer Screening Done in 2025' without type = counts as FOBT only",
                "FIT: any number of samples returned meets criteria",
                "gFOBT: 3+ samples required; if not specified, assume correct number returned",
                "Scope advanced to cecum = colonoscopy; to sigmoid colon = flexible sigmoidoscopy",
                "Colonoscopy/sigmoidoscopy report with documentation of complete exam"
            ],
            "not_acceptable": [
                "Tests performed in office or from digital rectal exam (DRE)",
                "CT scan of abdomen/pelvis (NOT same as CT colonography)",
                "Unclear documentation 'COL' or 'COLON 20XX' without test type specified",
                "Poor bowel prep or incomplete exam without scope advancement documentation",
                "gFOBT with only 1–2 samples returned"
            ]
        },

        "best_practices": [
            "Best practice to have actual screening test and result",
            "Include date and place of service when known",
            "Member refusal does not make them ineligible",
            "Educate about importance of early detection; offer alternative if colonoscopy refused",
            "Have FIT kits available with return instructions",
            "Update member history annually with type and date of colon cancer screening",
            "Document history of total colectomy or colon cancer",
            "Note: sDNA with FIT (Cologuard) and FIT test are NOT the same"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CCS-E  |  Cervical Cancer Screening
    # Source: Coding Guide p.9-10 + Tip Sheet p.59-62
    # ─────────────────────────────────────────────────────────────────────────
    "CCS": {
        "measure_id": "CCS",
        "name": "Cervical Cancer Screening",
        "primary_cpt": "88175",        # Cervical cytology, liquid-based (ThinPrep, preferred)
        "primary_icd10": "Z12.4",      # Encounter for screening for malignant neoplasm of cervix
        "description": (
            "Female members 21–64 screened for cervical cancer with age-appropriate cervical "
            "cytology and/or hrHPV testing. Ages 24–64: Pap smear every 3 years. "
            "Ages 30–64: hrHPV testing every 5 years (or co-testing). "
            "Refer to In-Network OB/GYN or Women's Health clinic."
        ),
        "age_range": "21-64 Female",
        "min_age": 21,
        "max_age": 64,
        "gender_requirement": "Female",
        "lookback_months": 36,   # cervical cytology (3 years); HPV has 60-month lookback
        "lookback_description": "Cervical cytology: 3 years (age 24+) | hrHPV / co-test: 5 years (age 30+)",
        "product_lines": ["EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement year and 2 years prior (Commercial); measurement year only (Medicaid)",
        "numerator_criteria": "Cervical cytology within 3 years OR hrHPV testing within 5 years (age 30+)",
        "denominator_criteria": "Female members 21–64 as of December 31 of measurement year",

        "screening_options": [
            {
                "type": "cervical_cytology",
                "age_range": "24-64",
                "lookback_months": 36,
                "description": "Cervical cytology (Pap smear) every 3 years — member must be 21+ on test date",
                "cpt": [
                    "88141", "88142", "88143", "88147", "88148", "88150",
                    "88152", "88153", "88154", "88164", "88165", "88166", "88167",
                    "88174", "88175"
                ],
                "hcpcs": [
                    "G0123", "G0124", "G0141", "G0143", "G0144", "G0145",
                    "G0147", "G0148", "P3000", "P3001", "Q0091"
                ],
                "loinc": [
                    "104866-9", "10524-7", "18500-9", "19762-4", "19765-7",
                    "19766-5", "19774-9", "33717-0", "47527-7", "47528-5"
                ]
            },
            {
                "type": "hrhpv_testing",
                "age_range": "30-64",
                "lookback_months": 60,
                "description": "High-risk HPV testing every 5 years — member must be 30+ on test date",
                "cpt": ["87624", "87625", "87626", "0502U"],
                "hcpcs": ["G0476"],
                "loinc": [
                    "104132-6", "104170-6", "104752-1", "104766-1", "104783-6",
                    "21440-3", "30167-1", "38372-9", "59263-4", "59264-2", "59420-0",
                    "69002-4", "71431-1", "75694-0", "77379-6", "77399-4", "77400-0",
                    "82354-2", "82456-5", "82675-0", "95539-3"
                ]
            },
            {
                "type": "cotesting",
                "age_range": "30-64",
                "lookback_months": 60,
                "description": "Cervical cytology + hrHPV co-testing every 5 years — member must be 30+ on test date",
                "cpt": [
                    "87624", "87625", "87626", "0502U",
                    "88141", "88142", "88143", "88147", "88148", "88150",
                    "88152", "88153", "88154", "88164", "88165", "88166", "88167",
                    "88174", "88175"
                ]
            }
        ],

        "codes": {
            "cervical_cytology_cpt": [
                "88141", "88142", "88143", "88147", "88148", "88150",
                "88152", "88153", "88154", "88164", "88165", "88166", "88167",
                "88174", "88175"
            ],
            "cervical_cytology_hcpcs": [
                "G0123", "G0124", "G0141", "G0143", "G0144", "G0145",
                "G0147", "G0148", "P3000", "P3001", "Q0091"
            ],
            "cervical_cytology_loinc": [
                "104866-9", "10524-7", "18500-9", "19762-4", "19765-7",
                "19766-5", "19774-9", "33717-0", "47527-7", "47528-5"
            ],
            "hrhpv_cpt": ["87624", "87625", "87626", "0502U"],
            "hrhpv_hcpcs": ["G0476"],
            "hrhpv_loinc": [
                "104132-6", "104170-6", "104752-1", "104766-1", "104783-6",
                "21440-3", "30167-1", "38372-9", "59263-4", "59264-2", "59420-0",
                "69002-4", "71431-1", "75694-0", "77379-6", "77399-4", "77400-0",
                "82354-2", "82456-5", "82675-0", "95539-3"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "hysterectomy_no_cervix",
                    "description": "Hysterectomy with no residual cervix / cervical agenesis / acquired absence of cervix",
                    "cpt": [
                        "57530", "57531", "57540", "57545", "57550", "57555", "57556",
                        "58150", "58152", "58200", "58210", "58240", "58260", "58262",
                        "58263", "58267", "58270", "58275", "58280", "58285",
                        "58290", "58291", "58292", "58293", "58294",
                        "58548", "58550", "58552", "58553", "58554",
                        "58570", "58571", "58572", "58573", "58575",
                        "58951", "58953", "58954", "58956", "59856", "59135", "51925", "56308"
                    ],
                    "icd10": ["Q51.5", "Z90.710", "Z90.712"],
                    "icd10pcs": ["0UTC0ZZ", "0UTC4ZZ", "0UTC7ZZ", "0UTC8ZZ"],
                    "criteria": (
                        "Not acceptable: hysterectomy alone (doesn't confirm cervix removed), "
                        "supracervical hysterectomy (cervix intact). "
                        "Acceptable: 'complete', 'total', 'radical' hysterectomy = implies no residual cervix."
                    )
                },
                {
                    "type": "sex_assigned_male_at_birth",
                    "description": "Members with sex assigned male at birth",
                    "loinc_code": "76689-9",
                    "loinc_value": "LA2-8",
                    "criteria": "LOINC 76689-9 (Sex Assigned at Birth) = LA2-8 (Male)"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "Member-reported information with date and result documented by care provider",
                "Generic 'HPV test' counts as hrHPV test",
                "Lab results with 'no endocervical cells' if a valid result was reported",
                "Lab test wording Ecto/Endo/Vaginal Pool: liquid based",
                "Any cervical cancer screening with collection and microscopic analysis",
                "Documentation 'Pap Smear/hrHPV done Jan 20XX-negative' with date",
                "Health Maintenance section if test date and result noted",
                "Documentation of 'vaginal Pap smear' with hysterectomy documentation",
                "Documentation of 'complete', 'total', or 'radical' hysterectomy"
            ],
            "not_acceptable": [
                "Biopsies or inadequate sample/no cervical cells present",
                "Biopsies are diagnostic — do not meet screening requirement",
                "Referral to OB/GYN alone does not meet the measure",
                "hrHPV DNA reflex test ordered but not performed",
                "Documentation of hysterectomy alone (does not confirm cervix removed)",
                "Supracervical hysterectomy — cervix remains intact"
            ]
        },

        "best_practices": [
            "All tests require date and result",
            "Request results for tests performed by another provider",
            "Complete test during well woman visit, sick visits, UTI or STD screening",
            "Review and document surgical and preventive screening history with results",
            "Use correct diagnosis and procedure codes",
            "Applies to all with cervix regardless of sexual history or HPV vaccination",
            "Transgender patients with cervix need regular pap tests"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # GSD  |  Glycemic Status Assessment for Patients with Diabetes (HbA1c)
    # Source: Coding Guide p.20-21 + Tip Sheet p.137-139
    # ─────────────────────────────────────────────────────────────────────────
    "GSD": {
        "measure_id": "GSD",
        "name": "Glycemic Status Assessment for Patients with Diabetes",
        "primary_cpt": "83036",        # HbA1c lab test (most common)
        "primary_icd10": "E11.9",      # Type 2 diabetes unspecified (default; overridden by member's actual ICD)
        "description": (
            "Members 18–75 with diabetes (types 1 and 2) whose most recent glycemic status "
            "(HbA1c or Glucose Management Indicator [GMI]) was assessed during measurement year. "
            "Target: HbA1c < 8.0% (good control). Flag: HbA1c > 9.0% (poor control — urgent follow-up). "
            "To close gap: CPT 83036 or 83037 (HbA1c lab test). "
            "Refer to In-Network Laboratory or Endocrinology."
        ),
        "age_range": "18-75",
        "min_age": 18,
        "max_age": 75,
        "gender_requirement": "Any",
        "lookback_months": 12,
        "lookback_description": "Measurement year (January 1 – December 31); use MOST RECENT result",
        "diagnosis_requirement": "Type 1 or Type 2 Diabetes (ICD-10 E08–E13)",
        "product_lines": ["Advantage MD", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": "Most recent HbA1c or GMI result during measurement year at defined threshold",
        "denominator_criteria": "Members 18–75 with diabetes (types 1 and 2)",

        "performance_levels": [
            {
                "level": "Glycemic Status < 8.0%",
                "description": "HbA1c or GMI < 8.0% — better performance = higher rate",
                "cpt_cat2": "3044F (< 7.0%), 3051F (7.0–7.9%)"
            },
            {
                "level": "Glycemic Status > 9.0%",
                "description": "HbA1c or GMI > 9.0% — better performance = LOWER rate",
                "cpt_cat2": "3046F (< 9.0% inverse), 3052F (8.0–8.9%)"
            }
        ],

        "codes": {
            "hba1c_cpt": ["83036", "83037"],
            "hba1c_loinc": ["4548-4", "17855-8", "4549-2", "17856-6", "96595-4"],
            "hba1c_result_cpt_cat2": ["3044F", "3046F", "3051F", "3052F"],
            # E08–E13 full diabetes spectrum per HEDIS MY2025 rulebook
            "diabetes_icd10": [
                "E08.9", "E08.65", "E09.9", "E09.65",
                "E10.9", "E10.65", "E10.649", "E10.641",
                "E11.9", "E11.65", "E11.649", "E11.641",
                "E12.9", "E13.9", "E13.65"
            ],
            "diabetes_type1_icd10": ["E10.9", "E10.65", "E10.649", "E10.641"],
            "diabetes_type2_icd10": ["E11.9", "E11.65", "E11.649", "E11.641"]
        },

        "exclusions": {
            "required": [
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "hospice",
                    "description": "Hospice or using hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66+ with frailty AND advanced illness"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term"
                }
            ],
            "optional": [
                {
                    "type": "polycystic_ovarian_syndrome",
                    "description": "Diagnosis of polycystic ovarian syndrome during measurement year"
                },
                {
                    "type": "gestational_diabetes",
                    "description": "Diagnosis of gestational diabetes during measurement year"
                },
                {
                    "type": "steroid_induced_diabetes",
                    "description": "Diagnosis of steroid-induced diabetes during measurement year"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "HbA1c lab test with result during measurement year",
                "Remote measurements by any digital device (CGM)",
                "Member-reported HbA1c documented in medical record",
                "Acceptable terminology: A1c, HbA1c, HgbA1c, Glycohemoglobin, Glycated hemoglobin",
                "GMI (Glucose Management Indicator) from CGM with documented date range",
                "If multiple tests performed, use MOST RECENT result closest to Dec 31",
                "Documentation must include date of test AND result together"
            ],
            "not_acceptable": [
                "HbA1c self-tested when not processed by a lab",
                "Documentation of ranges and thresholds only (e.g., '< 9.0%' without actual value)",
                "'Unknown' is not considered a result/finding",
                "Missing result",
                "Test ordered but not performed"
            ]
        },

        "best_practices": [
            "Order HbA1c test at least annually for all diabetic patients",
            "If elevated, have member repeat test prior to end of year",
            "Document test results in structured format with date AND value",
            "Use CPT Category II codes for performance tracking (3044F, 3051F, 3052F, 3046F)",
            "Schedule labs prior to patient appointments to assist with compliance",
            "Adjust therapy as indicated to improve A1c levels",
            "Educate member on A1c target and CGM goals",
            "Refer to case management for members with poor control (> 9.0%)",
            "Coordinate with endocrinology for HbA1c > 9.0%"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # EED  |  Eye Exam for Patients with Diabetes (Retinal Exam)
    # Source: Coding Guide p.20 + Tip Sheet p.99-100
    # ─────────────────────────────────────────────────────────────────────────
    "EED": {
        "measure_id": "EED",
        "name": "Eye Exam for Patients with Diabetes",
        "primary_cpt": "92014",        # Comprehensive ophthalmologic exam, established patient
        "primary_icd10": "E11.9",      # Type 2 diabetes unspecified (default; overridden by member's actual ICD)
        "description": (
            "Members 18–75 with diabetes who had a retinal or dilated eye exam by an "
            "ophthalmologist or optometrist, OR a negative retinal exam in the prior year, "
            "OR autonomous retinal imaging (point-of-care analysis) during the measurement year. "
            "To close gap: schedule annual diabetic eye exam with ophthalmologist or optometrist. "
            "CPT 92014 (comprehensive eye exam, established patient), 92134, 92228 (retinal imaging)."
        ),
        "age_range": "18-75",
        "min_age": 18,
        "max_age": 75,
        "gender_requirement": "Any",
        "lookback_months": 12,
        "lookback_description": "Measurement year; OR negative retinal exam in prior year",
        "diagnosis_requirement": "Type 1 or Type 2 Diabetes (ICD-10 E08–E13)",
        "product_lines": ["Advantage MD", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": (
            "Retinal/dilated eye exam by ophthalmologist or optometrist, OR "
            "negative retinal exam in prior year, OR autonomous retinal imaging during measurement year"
        ),
        "denominator_criteria": "Members 18–75 with diabetes as of December 31 of measurement year",
        "provider_specialty": "Ophthalmologist or Optometrist",

        "codes": {
            # Ophthalmologic exam CPT codes (ophthalmologist / optometrist)
            # General E/M codes (99213, 99214, 99203-99205 etc.) are NOT valid for EED
            "retinal_eye_exam_cpt": [
                "92002", "92004", "92012", "92014",
                "92018", "92019", "92134",
                "92201", "92202", "92230", "92235", "92240", "92250", "92260"
            ],
            "retinal_eye_exam_hcpcs": ["S0620", "S0621", "S3000"],
            "retinal_imaging_cpt": ["92227", "92228"],
            "negative_exam_prior_year_cpt_cat2": ["3072F"],
            "eye_exam_result_cpt_cat2": ["2022F", "2023F", "2024F", "2025F", "2026F", "2033F"],
            "diabetes_icd10": [
                "E08.9", "E08.65", "E09.9", "E09.65",
                "E10.9", "E10.65", "E10.649", "E10.641",
                "E11.9", "E11.65", "E11.649", "E11.641",
                "E12.9", "E13.9", "E13.65"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "Retinal or dilated eye exam by ophthalmologist or optometrist",
                "Negative retinal exam (no retinopathy) in prior year by ophthalmologist/optometrist",
                "Autonomous retinal imaging with point-of-care analysis and immediate diagnosis report",
                "Retinal imaging by qualified reading center"
            ],
            "not_acceptable": [
                "General physical exam by PCP without ophthalmology evaluation",
                "Referral to eye doctor without documented exam result",
                "Self-reported eye exam without provider documentation"
            ]
        },

        "best_practices": [
            "Provide member education on risks of diabetic eye disease",
            "Encourage annual eye exam at every diabetes-related visit",
            "Obtain eye exam reports; notate eye care provider's name and demographics if report unavailable",
            "Track retinopathy status — negative in prior year counts for this year",
            "Coordinate referrals to ophthalmology or optometry at time of diabetes diagnosis",
            "Document date, provider specialty, and result (with/without retinopathy)"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # KED  |  Kidney Health Evaluation for Patients with Diabetes
    # Source: Coding Guide p.22-23 + Tip Sheet p.143-144
    # ─────────────────────────────────────────────────────────────────────────
    "KED": {
        "measure_id": "KED",
        "name": "Kidney Health Evaluation for Patients with Diabetes",
        "primary_cpt": "82565",        # Creatinine (eGFR) — ordered first; 82570+82043 also required
        "primary_icd10": "E11.9",      # Type 2 diabetes unspecified (default; overridden by member's actual ICD)
        "description": (
            "Members 18–85 with diabetes who received BOTH an eGFR (estimated glomerular "
            "filtration rate) AND a urine albumin-creatinine ratio (uACR) during the measurement year. "
            "Both tests must be performed (may be same or different dates, within 4 days apart for uACR). "
            "To close gap: order CPT 82565 (eGFR/creatinine) AND CPT 82043 + 82570 (urine albumin + creatinine). "
            "Refer to In-Network Laboratory or Nephrology."
        ),
        "age_range": "18-85",
        "min_age": 18,
        "max_age": 85,
        "gender_requirement": "Any",
        "lookback_months": 12,
        "lookback_description": "Measurement year (both tests must occur during measurement year)",
        "diagnosis_requirement": "Type 1 or Type 2 Diabetes (ICD-10 E08–E13)",
        "product_lines": ["Advantage MD", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": (
            "BOTH: eGFR lab test AND urine albumin + urine creatinine (dates within 4 days of each other)"
        ),
        "denominator_criteria": "Members 18–85 with diabetes as of December 31 of measurement year",

        "codes": {
            "egfr_cpt": ["80047", "80048", "80050", "80053", "80069", "82565"],
            "urine_albumin_cpt": ["82043"],
            "urine_creatinine_cpt": ["82570"],
            "diabetes_icd10": [
                "E08.9", "E08.65", "E09.9", "E09.65",
                "E10.9", "E10.65", "E10.649", "E10.641",
                "E11.9", "E11.65", "E11.649", "E11.641",
                "E12.9", "E13.9", "E13.65"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "esrd",
                    "description": "End-stage renal disease (ESRD)",
                    "icd10": ["N18.5", "N18.6", "Z99.2"],
                    "criteria": "Any ESRD diagnosis in member history"
                },
                {
                    "type": "dialysis",
                    "description": "Members receiving dialysis",
                    "cpt": [
                        "90935", "90937", "90945", "90947",
                        "90997", "90999", "99512"
                    ],
                    "hcpcs": ["G0257", "S9339"]
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term"
                },
                {
                    "type": "frailty_advanced_illness_66_80",
                    "description": "Members 66–80 with frailty AND advanced illness"
                },
                {
                    "type": "frailty_81_plus",
                    "description": "Members 81+ with frailty (regardless of advanced illness)"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "eGFR and uACR on same or different dates during measurement year",
                "Quantitative urine albumin test (82043) AND urine creatinine test (82570) within 4 days",
                "eGFR panel (80047, 80048, 80050, 80053, 80069) OR individual creatinine (82565)",
                "Tests ordered by any provider type"
            ],
            "not_acceptable": [
                "eGFR alone (without uACR) — BOTH required",
                "uACR alone (without eGFR) — BOTH required",
                "Urine albumin and creatinine drawn more than 4 days apart"
            ]
        },

        "best_practices": [
            "Routinely order BOTH eGFR and uACR for all diabetic members",
            "Make sure 82043 (urine albumin) AND 82570 (urine creatinine) are ordered together",
            "Schedule labs prior to patient appointments for compliance",
            "Follow up with patients to discuss and educate on kidney health",
            "Educate on how diabetes affects kidneys and prevention strategies",
            "Control blood pressure, blood sugars, cholesterol to protect kidney function",
            "Consider ACE inhibitors or ARBs for kidney protection",
            "Avoid NSAIDs (naproxen, ibuprofen) — harmful to kidneys",
            "Coordinate with nephrologist or endocrinologist as needed"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # BPD  |  Blood Pressure Control for Patients with Diabetes
    # Source: Coding Guide p.20 + Tip Sheet p.44-48
    # ─────────────────────────────────────────────────────────────────────────
    "BPD": {
        "measure_id": "BPD",
        "name": "Blood Pressure Control for Patients with Diabetes",
        "primary_cpt": "3074F",        # BP systolic < 130 (CPT Category II — controlled BP)
        "primary_icd10": "E11.9",      # Type 2 diabetes unspecified (default; overridden by member's actual ICD)
        "description": (
            "Members 18–75 with diabetes who had blood pressure control (< 140/90 mmHg) "
            "during the measurement year. Remote measurements by any digital device are acceptable. "
            "Member-reported BP documented in the medical record is eligible. "
            "Goal: Systolic < 140 AND Diastolic < 90. "
            "Refer to In-Network PCP or Endocrinology for BP management."
        ),
        "age_range": "18-75",
        "min_age": 18,
        "max_age": 75,
        "gender_requirement": "Any",
        "lookback_months": 12,
        "lookback_description": "Measurement year",
        "diagnosis_requirement": "Type 1 or Type 2 Diabetes (ICD-10 E08–E13)",
        "product_lines": ["Advantage MD", "EHP", "Priority Partners", "USFHP"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": "Most recent BP reading during measurement year with systolic < 140 AND diastolic < 90",
        "denominator_criteria": "Members 18–75 with diabetes as of December 31 of measurement year",
        "bp_target": "< 140/90 mmHg",

        "codes": {
            "bp_systolic_controlled_cpt_cat2": ["3074F", "3075F"],   # <130, 130-139
            "bp_systolic_uncontrolled_cpt_cat2": ["3077F"],           # >=140
            "bp_diastolic_controlled_cpt_cat2": ["3078F", "3079F"],  # <80, 80-89
            "bp_diastolic_uncontrolled_cpt_cat2": ["3080F"],          # >=90
            "bp_systolic_loinc": ["8459-0", "8480-6", "8508-4", "8546-4", "8547-2", "75997-7"],
            "bp_diastolic_loinc": ["8453-3", "8462-4", "8496-2", "8514-2", "8515-9", "75995-1"],
            "diabetes_icd10": [
                "E08.9", "E08.65", "E09.9", "E09.65",
                "E10.9", "E10.65", "E10.649", "E10.641",
                "E11.9", "E11.65", "E11.649", "E11.641",
                "E12.9", "E13.9", "E13.65"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "esrd_dialysis_nephrectomy",
                    "description": "ESRD, dialysis, total or partial nephrectomy, or kidney transplant",
                    "icd10": ["N18.5", "N18.6", "Z99.2"],
                    "criteria": "Any time during member's history on or prior to last day of measurement period"
                },
                {
                    "type": "pregnancy",
                    "description": "Diagnosis of pregnancy during measurement period"
                },
                {
                    "type": "non_acute_inpatient",
                    "description": "Non-acute inpatient admission during measurement period (rehab, nursing home, inpatient mental health)"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year"
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year"
                },
                {
                    "type": "deceased",
                    "description": "Member died during measurement year"
                },
                {
                    "type": "institutional_snp",
                    "description": "Medicare members 66+ enrolled in I-SNP or living long-term"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66+ (up to 80) with frailty AND advanced illness"
                },
                {
                    "type": "frailty_81_plus",
                    "description": "Members 81+ with at least two indications of frailty"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "BP reading documented in medical record during measurement year",
                "Remote measurements by digital device (home BP monitor, etc.)",
                "Member-reported BP documented in medical record by a provider",
                "Most recent BP reading in measurement year is used",
                "Telehealth or in-person BP measurement"
            ],
            "not_acceptable": [
                "BP self-reported without provider documentation",
                "BP reading from outside the measurement year",
                "Missing systolic or diastolic value"
            ]
        },

        "best_practices": [
            "Check BP at every diabetes-related visit",
            "Use CPT-CAT II codes (3074F, 3075F, 3077F, 3078F, 3079F, 3080F) for BP documentation",
            "Remote monitoring acceptable — encourage home BP monitoring",
            "If BP elevated, adjust medications and schedule follow-up",
            "Target: Systolic < 140 AND Diastolic < 90 mmHg",
            "Coordinate with cardiology or nephrology for complex BP management",
            "Document BP with date in structured format"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # AAP  |  Adults' Access to Preventive/Ambulatory Health Services
    # Source: HEDIS MY2025 Rulebook — Measure 1
    # ─────────────────────────────────────────────────────────────────────────
    "AAP": {
        "measure_id": "AAP",
        "name": "Adults' Access to Preventive/Ambulatory Health Services",
        "primary_cpt": "99213",        # Office visit, established patient, moderate complexity
        "primary_icd10": "Z00.00",     # Encounter for general adult medical examination without abnormal findings
        "description": (
            "Members 20 and older who had at least one ambulatory or preventive care visit "
            "during the measurement year. Includes in-person, telephone, and e-visit/virtual "
            "check-in encounters. To close this gap, schedule any preventive or primary care "
            "visit with the member's PCP. CPT 99202–99215 (office/outpatient visit), "
            "99381–99397 (preventive visits)."
        ),
        "age_range": "20-999",
        "min_age": 20,
        "max_age": 999,
        "gender_requirement": "Any",
        "lookback_months": 12,
        "lookback_description": "January 1 – December 31 of measurement year",
        "diagnosis_requirement": "",
        "product_lines": ["Medicaid", "Medicare"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": "At least ONE qualifying ambulatory, preventive, telephone, or e-visit encounter during measurement year",
        "denominator_criteria": "Members 20 and older enrolled during the measurement year",
        "rule_type": "ANY_ONE_OF",

        "codes": {
            # Office / outpatient / preventive visit CPT
            "ambulatory_visit_cpt": [
                "99202", "99203", "99204", "99205",
                "99211", "99212", "99213", "99214", "99215",
                "99242", "99243", "99244", "99245",
                "99304", "99305", "99306", "99307", "99308", "99309", "99310",
                "99318",
                "99324", "99325", "99326", "99327", "99328",
                "99334", "99335", "99336", "99337",
                "99341", "99345",
                "99347", "99348", "99349", "99350",
                "99381", "99382", "99383", "99384", "99385", "99386", "99387",
                "99391", "99392", "99393", "99394", "99395", "99396", "99397",
                "99401", "99402", "99403", "99404",
                "99411", "99412", "99429", "99483",
                "92002", "92004", "92012", "92014",
                "99315", "99316"
            ],
            "ambulatory_visit_hcpcs": [
                "G0402", "G0438", "G0439", "G0463", "T1015", "S0620", "S0621"
            ],
            # Telephone visit CPT
            "telephone_visit_cpt": ["98966", "98967", "98968", "99441", "99442", "99443"],
            # E-visit / virtual check-in CPT
            "evisit_cpt": [
                "98970", "98971", "98972", "98980", "98981",
                "99421", "99422", "99423", "99457", "99458"
            ],
            "evisit_hcpcs": ["G0071", "G2010", "G2012", "G2250", "G2251", "G2252"],
            # ICD preventive visit encounter codes (Z00.x)
            "preventive_icd10": [
                "Z00.00", "Z00.01", "Z00.121", "Z00.129", "Z00.3", "Z00.5", "Z00.8",
                "Z02.0", "Z02.1", "Z02.2", "Z02.3", "Z02.4", "Z02.5", "Z02.6",
                "Z02.71", "Z02.79", "Z02.81", "Z02.82", "Z02.83", "Z02.84",
                "Z02.89", "Z02.9", "Z76.1", "Z76.2"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "hospice",
                    "description": "Member in hospice care during measurement year",
                    "hcpcs": ["G9054", "M1017"],
                    "icd10": ["Z51.5"]
                },
                {
                    "type": "deceased",
                    "description": "Member deceased during measurement year"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "In-person office visits, preventive wellness visits, telehealth, telephone, e-visits",
                "Any qualifying CPT/HCPCS code from the ambulatory, telephone, or e-visit code sets",
                "ICD-10 Z00.x preventive visit encounter codes",
                "Member-reported visits with documented date and provider"
            ],
            "not_acceptable": [
                "ED-only visits without ambulatory component",
                "Lab-only visits with no face-to-face encounter",
                "Inpatient-only encounters"
            ]
        },

        "best_practices": [
            "Encourage annual wellness visit — use G0438 (initial) or G0439 (subsequent) for Medicare",
            "Any preventive or illness-related outpatient visit qualifies",
            "Engage members with telehealth options to reduce access barriers",
            "Flag members with zero visits in last 12 months for outreach",
            "Document encounter date and CPT/HCPCS code in structured format"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CBP  |  Controlling Blood Pressure
    # Source: HEDIS MY2025 Rulebook — Measure 16
    # Trigger: Hypertension (ICD I10)
    # ─────────────────────────────────────────────────────────────────────────
    "CBP": {
        "measure_id": "CBP",
        "name": "Controlling Blood Pressure",
        "primary_cpt": "3074F",        # BP systolic < 130 (CPT Category II — controlled BP)
        "primary_icd10": "I10",        # Essential (primary) hypertension
        "description": (
            "Members 18–85 with hypertension (ICD I10) whose most recent blood pressure "
            "reading during the measurement year was adequately controlled (< 140/90 mmHg). "
            "Remote and member-reported BP measurements are acceptable. "
            "To close gap: document a BP reading using CPT-CAT-II codes 3074F or 3075F "
            "(systolic < 140) AND 3078F or 3079F (diastolic < 90). "
            "Refer to PCP or Cardiology for blood pressure management."
        ),
        "age_range": "18-85",
        "min_age": 18,
        "max_age": 85,
        "gender_requirement": "Any",
        "lookback_months": 12,
        "lookback_description": "Measurement year — use most recent BP reading",
        "diagnosis_requirement": "Hypertension (ICD-10 I10)",
        "product_lines": ["Medicaid", "Medicare", "Commercial"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": "Most recent BP < 140/90 mmHg documented during measurement year",
        "denominator_criteria": "Members 18–85 with hypertension (ICD I10) and at least 2 outpatient HTN visits",
        "bp_target": "< 140/90 mmHg",
        "rule_type": "VALUE_BASED",

        "codes": {
            # CPT Category II — BP reading documentation
            "bp_systolic_controlled_cpt_cat2": ["3074F", "3075F"],    # systolic < 130 / 130–139
            "bp_systolic_uncontrolled_cpt_cat2": ["3077F"],            # systolic ≥ 140
            "bp_diastolic_controlled_cpt_cat2": ["3078F", "3079F"],   # diastolic < 80 / 80–89
            "bp_diastolic_uncontrolled_cpt_cat2": ["3080F"],           # diastolic ≥ 90
            # Hypertension trigger
            "hypertension_icd10": ["I10"],
            # LOINC for BP readings
            "bp_systolic_loinc": ["8459-0", "8480-6", "8508-4", "8546-4", "8547-2", "75997-7"],
            "bp_diastolic_loinc": ["8453-3", "8462-4", "8496-2", "8514-2", "8515-9", "75995-1"]
        },

        "exclusions": {
            "required": [
                {
                    "type": "esrd",
                    "description": "End-stage renal disease, dialysis, or kidney transplant",
                    "icd10": ["N18.5", "N18.6", "Z99.2"],
                    "cpt": ["90935", "90937", "90945", "90947", "90997", "90999", "99512"]
                },
                {
                    "type": "pregnancy",
                    "description": "Active pregnancy diagnosis during measurement period"
                },
                {
                    "type": "palliative_care",
                    "description": "Palliative care during measurement year",
                    "hcpcs": ["G9054", "M1017"],
                    "icd10": ["Z51.5", "Z51.89"]
                },
                {
                    "type": "hospice",
                    "description": "Hospice services during measurement year",
                    "hcpcs": ["G9054", "M1017"],
                    "icd10": ["Z51.5"]
                },
                {
                    "type": "deceased",
                    "description": "Member deceased during measurement year"
                },
                {
                    "type": "frailty_advanced_illness",
                    "description": "Members 66–80 with frailty AND advanced illness"
                },
                {
                    "type": "frailty_81_plus",
                    "description": "Members 81+ with frailty"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "In-person BP measurement documented in medical record",
                "Remote/digital device measurements (home BP monitor)",
                "Member-reported BP documented in chart by a provider",
                "Telehealth BP measurement with documented result",
                "Most recent BP reading in measurement year is used",
                "CPT-CAT-II codes (3074F, 3075F, 3077F, 3078F, 3079F, 3080F) count"
            ],
            "not_acceptable": [
                "BP self-reported without provider documentation",
                "BP reading from outside the measurement year",
                "Missing systolic or diastolic value"
            ]
        },

        "best_practices": [
            "Document BP at every visit using structured CPT-CAT-II codes",
            "Encourage home BP monitoring and telehealth BP reporting",
            "Target systolic < 140 AND diastolic < 90 mmHg",
            "Adjust antihypertensive medication if BP uncontrolled",
            "Schedule follow-up within 4 weeks for uncontrolled BP",
            "Coordinate with cardiology for resistant hypertension",
            "Educate on lifestyle factors: diet, exercise, salt restriction, weight management"
        ]
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CHL  |  Chlamydia Screening in Women
    # Source: HEDIS MY2025 Rulebook — Measure 6
    # ─────────────────────────────────────────────────────────────────────────
    "CHL": {
        "measure_id": "CHL",
        "name": "Chlamydia Screening in Women",
        "primary_cpt": "87491",        # Chlamydia trachomatis, NAAT (nucleic acid amplification, preferred)
        "primary_icd10": "Z11.8",      # Encounter for screening for other specified infectious and parasitic diseases
        "description": (
            "Female members 16–24 (sexually active) who were screened for chlamydia "
            "during the measurement year. Annual screening is recommended. "
            "To close gap: order CPT 87491 (chlamydia trachomatis, NAATs) or 87490 (culture). "
            "Refer to OB/GYN, women's health clinic, or STI testing site."
        ),
        "age_range": "16-24 Female",
        "min_age": 16,
        "max_age": 24,
        "gender_requirement": "Female",
        "lookback_months": 12,
        "lookback_description": "January 1 – December 31 of measurement year",
        "diagnosis_requirement": "",
        "product_lines": ["Medicaid"],
        "continuous_enrollment": "Measurement year",
        "numerator_criteria": "At least one chlamydia test during the measurement year",
        "denominator_criteria": "Female members 16–24 who are sexually active (Medicaid)",
        "rule_type": "REQUIRED",

        "codes": {
            "chlamydia_cpt": [
                "87110", "87270", "87320",
                "87490", "87491", "87492",
                "87810"
            ]
        },

        "exclusions": {
            "required": [
                {
                    "type": "hysterectomy_no_cervix",
                    "description": "Hysterectomy without residual cervix",
                    "cpt": [
                        "57530", "57531", "57540", "57545", "57550", "57555", "57556",
                        "58150", "58152", "58200", "58210", "58240", "58260", "58262",
                        "58263", "58267", "58270", "58275", "58280", "58285",
                        "58290", "58291", "58292", "58293", "58294",
                        "58548", "58550", "58552", "58553", "58554",
                        "58570", "58571", "58572", "58573", "58575",
                        "58951", "58953", "58954", "59135", "51925", "56308"
                    ],
                    "icd10": ["Q51.5", "Z90.710", "Z90.712"],
                    "icd10pcs": ["0UTC0ZZ", "0UTC4ZZ", "0UTC7ZZ", "0UTC8ZZ"]
                },
                {
                    "type": "sex_assigned_male_at_birth",
                    "description": "Members with sex assigned male at birth",
                    "loinc_code": "76689-9",
                    "loinc_value": "LA2-8"
                },
                {
                    "type": "hospice",
                    "description": "Hospice or palliative care during measurement year",
                    "hcpcs": ["G9054", "M1017"],
                    "icd10": ["Z51.5"]
                },
                {
                    "type": "deceased",
                    "description": "Member deceased during measurement year"
                }
            ]
        },

        "clinical_guidelines": {
            "acceptable": [
                "Any chlamydia NAAT, culture, or antigen test during measurement year",
                "Tests performed during any visit type (preventive, sick, STI screening)",
                "Lab order with result documented in medical record",
                "Combo STI panel that includes chlamydia testing"
            ],
            "not_acceptable": [
                "Gonorrhea-only test without chlamydia component",
                "Referral to lab without documented result",
                "Rapid self-test without provider documentation"
            ]
        },

        "best_practices": [
            "Screen all sexually active women under 25 annually per USPSTF Grade B",
            "Offer chlamydia test at all reproductive health visits",
            "Co-screen for gonorrhea with chlamydia",
            "Treat positive results with appropriate antibiotics; notify partners",
            "Document test date and result in structured format",
            "Telehealth order + lab visit combination is acceptable"
        ]
    }
}


# ── Public API ─────────────────────────────────────────────────────────────────

def get_measure_definition(measure_id: str) -> dict:
    """Get complete measure definition by ID."""
    return HEDIS_MEASURES.get(measure_id)


def get_all_measures() -> dict:
    """Get all HEDIS measure definitions."""
    return HEDIS_MEASURES


def get_measure_codes(measure_id: str, code_type: str = None) -> dict:
    """
    Get codes for a specific measure.
    code_type: 'cpt', 'hcpcs', 'icd10', 'loinc', or None for all
    """
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return {}
    codes = measure.get("codes", {})
    if code_type:
        return {k: v for k, v in codes.items() if code_type.lower() in k.lower()}
    return codes


def get_measure_exclusions(measure_id: str) -> dict:
    """Get exclusion criteria for a specific measure."""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return {}
    return measure.get("exclusions", {})


def get_clinical_guidelines(measure_id: str) -> dict:
    """Get clinical documentation guidelines for a specific measure."""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return {}
    return measure.get("clinical_guidelines", {})


def get_best_practices(measure_id: str) -> list:
    """Get best practices for a specific measure."""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return []
    return measure.get("best_practices", [])


def get_screening_options(measure_id: str) -> list:
    """Get screening options for measures with multiple screening paths (COL, CCS)."""
    measure = HEDIS_MEASURES.get(measure_id)
    if not measure:
        return []
    return measure.get("screening_options", [])
