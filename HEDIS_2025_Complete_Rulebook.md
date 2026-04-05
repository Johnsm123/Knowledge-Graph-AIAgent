# HEDIS 2025 Complete Rulebook
## For Neo4j Knowledge Graph — Care Gap Detection System
### Based on NCQA Technical Specifications MY2025 (Medicaid)

---

## HOW TO USE THIS RULEBOOK

For every new member added to the system:

**Parameters required from member at intake:**
- `member_id` · `first_name` · `last_name`
- `date_of_birth` (drives ALL age rules)
- `gender` / `sex_assigned_at_birth` (drives gender-specific measure eligibility)
- `enrollment_start_date` · `enrollment_end_date` (active = NULL)
- `insurance_type` (Medicaid / Medicare / Commercial)
- `plan_id`
- `pcp_id`
- `diagnoses[]` → each: `icd10_code`, `description`, `date`, `status` (active/resolved)
- `procedures[]` → each: `cpt_code`, `hcpcs_code`, `date`, `modifier`, `place_of_service`
- `lab_results[]` → each: `loinc_code`, `result_value`, `result_unit`, `result_date`
- `medications[]` → each: `ndc_code`, `drug_name`, `start_date`, `end_date`, `dose`
- `vaccinations[]` → each: `cpt_code`, `vaccine_name`, `date`

**Global required exclusions (apply to ALL measures):**
- Member in hospice care (any claim with Z51.5, G9054, M1017) → EXCLUDE ALL
- Member deceased during measurement year → EXCLUDE ALL
- Member enrolled in I-SNP (Medicare, age 66+) → EXCLUDE ALL
- Member long-term in institution (LTI flag) → EXCLUDE ALL

---

# PART 1 — PREVENTIVE CARE MEASURES

---

## MEASURE 1: Adults' Access to Preventive/Ambulatory Health Services (AAP)

### Eligibility
- **Age:** 20 years and older as of December 31 of measurement year
- **Gender:** Any
- **Insurance:** Medicaid / Medicare
- **Enrollment:** Must be enrolled during measurement year

### What qualifies (numerator)
Member had at least ONE of the following during the measurement year:

| Type | CPT Codes | HCPCS | ICD-10 |
|---|---|---|---|
| Ambulatory visits | 99202–99205, 99211–99215, 99242–99245, 99304–99310, 99318, 99324–99328, 99334–99337, 99341, 99345, 99347–99350, 99381–99387, 99391–99397, 99401–99404, 99411, 99412, 99429, 99483, 92002, 92004, 92012, 92014, 99315, 99316 | G0402, G0438, G0439, G0463, T1015, S0620, S0621 | Z00.00, Z00.01, Z00.121, Z00.129, Z00.3, Z00.5, Z00.8, Z02.0–Z02.6, Z02.71, Z02.79, Z02.81–Z02.84, Z02.89, Z02.9, Z76.1, Z76.2 |
| Telephone visits | 98966–98968, 99441–99443 | | |
| E-visit / virtual check-ins | 98970–98972, 98980, 98981, 99421–99423, 99457, 99458 | G0071, G2010, G2012, G2250–G2252 | |

### Exclusions
- All global required exclusions apply
- No measure-specific exclusions

### Care Gap = OPEN if
Member had ZERO qualifying visits in the measurement year.

### Age Stratifications Reported
- 20–44 years · 45–64 years · 65+ years · Total

### Neo4j Rule Properties
```
Measure.id = "AAP"
CareGapRule.min_age = 20
CareGapRule.max_age = 999
CareGapRule.applicable_gender = NULL (any)
CareGapRule.lookback_months = 12
CareGapRule.rule_type = "ANY_ONE_OF"
```

---

## MEASURE 2: Adult Immunization Status (AIS-E)

### Eligibility
- **Age:** 19 years and older
- **Gender:** Any
- **Insurance:** Medicaid

### What qualifies — 5 vaccines all required

#### Influenza (1 dose per measurement year)
| CPT |
|---|
| 90653, 90654, 90656, 90658, 90660, 90661, 90662, 90672, 90673, 90674, 90682, 90686, 90688, 90689, 90694, 90756 |

#### Tdap (1 dose ever in lifetime)
| CPT |
|---|
| 90714, 90715 |

#### Hepatitis B (complete series)
| CPT |
|---|
| 90739, 90740, 90743, 90744, 90746, 90747, 90748, 90759 |

#### Herpes Zoster (1 dose)
| CPT |
|---|
| 90750 |

#### Pneumococcal (1 dose)
| CPT | HCPCS |
|---|---|
| 90670, 90671, 90677, 90732 | G0009 |

### Exclusions
- All global required exclusions
- Members with a documented contraindication for a specific vaccine → exclude from that specific vaccine's rate

### Care Gap = OPEN if
Any of the 5 vaccines is missing or out of date.

### Neo4j Rule Properties
```
Measure.id = "AIS_E"
CareGapRule.min_age = 19
CareGapRule.max_age = 999
CareGapRule.applicable_gender = NULL
CareGapRule.rule_type = "ALL_REQUIRED" (5 sub-rules)
Sub-rule: Influenza → lookback_months = 12
Sub-rule: Tdap → lookback_months = lifetime
Sub-rule: HepB → complete series
Sub-rule: Zoster → lookback_months = lifetime
Sub-rule: Pneumo → lookback_months = lifetime
```

---

## MEASURE 3: Colorectal Cancer Screening (COL-E) ★ ECDS

### Eligibility
- **Age:** 45–75 as of December 31 of measurement year
- **Gender:** Any
- **Insurance:** Medicaid / Medicare

### What qualifies — ANY ONE of the following

| Screening Type | CPT | HCPCS | Lookback Window |
|---|---|---|---|
| Colonoscopy | 44388–44392, 44394, 44401–44408, 45378–45382, 45384–45386, 45388–45393, 45398 | G0105, G0121 | 10 years (120 months) |
| CT colonography | 74261–74263 | | 5 years (60 months) |
| FIT-DNA (Cologuard) | 81528 | G0464 | 3 years (36 months) |
| Flexible sigmoidoscopy | 45330–45335, 45337–45342, 45346, 45347, 45349–45350 | G0104 | 5 years (60 months) |
| FOBT (guaiac / FIT) | 82270, 82274 | G0328 | 12 months |

### Exclusions — CRITICAL

| Exclusion Reason | CPT | ICD-10 | Action |
|---|---|---|---|
| History of colorectal cancer | | C18.0–C18.9, C19, C20, C21.2, C21.8, C78.5, Z85.038, Z85.048 | EXCLUDE |
| Total colectomy | 44150–44153, 44155–44158, 44210–44212 | 0DTE0ZZ, 0DTE4ZZ, 0DTE8ZZ, 0DTE7ZZ | EXCLUDE |
| Frailty + advanced illness (age 66+) | | | EXCLUDE |
| Medicare I-SNP age 66+ | | | EXCLUDE |
| Global hospice / deceased | | Z51.5 | EXCLUDE |

### Care Gap = OPEN if
No qualifying colorectal screening found within the applicable lookback window for any screening type.

### Neo4j Rule Properties
```
Measure.id = "COL_E"
CareGapRule.min_age = 45
CareGapRule.max_age = 75
CareGapRule.applicable_gender = NULL
CareGapRule.rule_type = "ANY_ONE_OF"
ExclusionCondition.codes = [colorectal_cancer_ICD, colectomy_CPT]
```

---

## MEASURE 4: Breast Cancer Screening (BCS-E) ★ ECDS

### Eligibility
- **Age:** 52–74 (denominator), measure targets 50–74
- **Gender:** Female (sex assigned at birth = Female)
- **Insurance:** Medicaid / Medicare
- **Measurement window:** October 1 TWO years before MY through December 31 of MY

### What qualifies (numerator)

| Description | CPT |
|---|---|
| Mammography (any type) | 77061, 77062, 77063, 77065, 77066, 77067 |

### Exclusions — CRITICAL (must check ALL before flagging gap)

| Exclusion Reason | CPT | Modifier | HCPCS | ICD-10 | Action |
|---|---|---|---|---|---|
| Bilateral mastectomy (procedure) | | | | 0HTV0ZZ | EXCLUDE — skip mammogram |
| History of bilateral mastectomy | | | | Z90.13 | EXCLUDE — skip mammogram |
| Unilateral mastectomy with bilateral modifier | 19180, 19200, 19220, 19240, 19303–19307 | 50 | | | EXCLUDE |
| Unilateral mastectomy with left/right modifier | 19180, 19200, 19220, 19240, 19303–19307 | LT or RT | | | EXCLUDE (check BOTH sides) |
| Left AND right unilateral mastectomy | | | | 0HTU0ZZ, 0HTT0ZZ | EXCLUDE |
| Absence of both breasts | | | | Z90.11, Z90.12 | EXCLUDE |
| Gender-affirming chest surgery (MUST have BOTH: CPT + ICD) | 19318 | | | F64.1, F64.2, F64.8, Z87.890 | EXCLUDE — requires BOTH codes |
| Palliative care | | | G9054, M1017 | Z51.5 | EXCLUDE |
| Frailty + advanced illness (age 66+) | | | | | EXCLUDE |
| Hospice / deceased | | | | | EXCLUDE |

### IMPORTANT GENDER DYSPHORIA EXCLUSION RULE
The gender-affirming surgery exclusion requires BOTH:
1. CPT 19318 (reduction mammaplasty) AND
2. At least one of: F64.1, F64.2, F64.8, Z87.890 (gender dysphoria diagnosis)
Neither alone is sufficient — BOTH must be present.

### Care Gap = OPEN if
No mammogram found between October 1 two years before MY and December 31 of MY, and no valid exclusion applies.

### Neo4j Rule Properties
```
Measure.id = "BCS_E"
CareGapRule.min_age = 52
CareGapRule.max_age = 74
CareGapRule.applicable_gender = "F"
CareGapRule.lookback_months = 27  (Oct 1 two years prior to Dec 31 of MY)
CareGapRule.rule_type = "REQUIRED"
ExclusionCondition[1] = bilateral_mastectomy → ICD: 0HTV0ZZ, Z90.13
ExclusionCondition[2] = unilateral_bilateral_modifier → CPT+modifier
ExclusionCondition[3] = both_unilateral → ICD: 0HTU0ZZ+0HTT0ZZ
ExclusionCondition[4] = absence_both_breasts → ICD: Z90.11+Z90.12
ExclusionCondition[5] = gender_affirming → REQUIRES CPT 19318 AND F64.x/Z87.890
ExclusionCondition[6] = palliative → HCPCS: G9054/M1017, ICD: Z51.5
```

---

## MEASURE 5: Cervical Cancer Screening (CCS-E) ★ ECDS

### Eligibility
- **Age:** 21–64 as of December 31 of measurement year
- **Sex assigned at birth:** Female
- **Insurance:** Medicaid

### What qualifies — Age-dependent rules

| Age Group | Test Required | CPT | HCPCS | Frequency |
|---|---|---|---|---|
| Ages 21–64 | Cervical cytology (Pap) | 88141–88143, 88147, 88148, 88150, 88152–88154, 88153, 88164–88167, 88174, 88175 | G0123, G0124, G0141, G0143–G0145, G0147, G0148, P3000, P3001, Q0091 | Every 3 years |
| Ages 30–64 | hrHPV testing alone OR co-test with cytology | 87624, 87625 | G0476 | Every 5 years |

### Exclusions

| Exclusion Reason | CPT | ICD-10 | Action |
|---|---|---|---|
| Hysterectomy without residual cervix | 51925, 56308, 57530, 57531, 57540, 57545, 57550, 57555, 57556, 58150, 58152, 58200, 58210, 58240, 58260, 58262, 58263, 58267, 58270, 58275, 58280, 58285, 58290–58294, 58548, 58550, 58552–58554, 58570–58573, 58575, 58951, 58953, 58954, 58956, 59135 | Q51.5, Z90.710, Z90.712, 0UTC0ZZ, 0UTC4ZZ, 0UTC7ZZ, 0UTC8ZZ | EXCLUDE |
| Cervical agenesis or acquired absence of cervix | | Q51.5, Z90.712 | EXCLUDE |
| Sex assigned at birth = Male | LOINC 76689-9 = LA2-8 | | EXCLUDE |
| Global exclusions (hospice, deceased) | | | EXCLUDE |

### Care Gap = OPEN if
- Age 21–64: No cervical cytology in last 3 years AND no hrHPV (if 30–64) in last 5 years

### Neo4j Rule Properties
```
Measure.id = "CCS_E"
CareGapRule.min_age = 21
CareGapRule.max_age = 64
CareGapRule.applicable_gender = "F"  (sex assigned at birth)
Sub-rule[1]: cytology → lookback_months = 36 (all ages 21–64)
Sub-rule[2]: hrHPV → lookback_months = 60 (ages 30–64 only)
ExclusionCondition: hysterectomy_no_cervix, cervical_agenesis, male_birth_sex
```

---

## MEASURE 6: Chlamydia Screening (CHL)

### Eligibility
- **Age:** 16–24
- **Sex assigned at birth:** Female (sexually active)
- **Insurance:** Medicaid

### What qualifies
| Description | CPT |
|---|---|
| Chlamydia test | 87110, 87270, 87320, 87490, 87491, 87492, 87810 |

### Exclusions
- Hysterectomy without residual cervix
- Cervical agenesis / acquired absence of cervix
- Sex assigned at birth = Male
- Global exclusions

### Care Gap = OPEN if
No chlamydia test in measurement year.

### Neo4j Rule Properties
```
Measure.id = "CHL"
CareGapRule.min_age = 16
CareGapRule.max_age = 24
CareGapRule.applicable_gender = "F"
CareGapRule.lookback_months = 12
```

---

# PART 2 — KEEPING KIDS HEALTHY

---

## MEASURE 7: Child and Adolescent Well-Care Visits (WCV)

### Eligibility
- **Age:** 3–21 as of December 31 of measurement year
- **Gender:** Any

### What qualifies
| Description | CPT | HCPCS | ICD-10 |
|---|---|---|---|
| Well-care visit | 99382–99385, 99391–99395 | G0438, G0439, S0302, S0610, S0612, S0613 | Z00.00, Z00.01, Z00.110, Z00.111, Z00.121, Z00.129, Z00.2, Z00.3, Z02.5, Z76.1, Z76.2, Z01.411, Z01.419 |

### What counts
At least 1 comprehensive well-care visit with PCP or OB/GYN during measurement year.

### Exclusions
- Global required exclusions only

### Care Gap = OPEN if
No qualifying well-care visit in measurement year.

### Neo4j Rule Properties
```
Measure.id = "WCV"
CareGapRule.min_age = 3
CareGapRule.max_age = 21
CareGapRule.lookback_months = 12
CareGapRule.rule_type = "REQUIRED"
```

---

## MEASURE 8: Childhood Immunization Status (CIS-E) ★ ECDS

### Eligibility
- **Age:** Children who turn 2 during measurement year
- **Insurance:** Medicaid

### Combination 10 — ALL required by 2nd birthday

| Vaccine | CPT | HCPCS | ICD-10 (disease history) |
|---|---|---|---|
| DTaP (4 doses) | 90697, 90698, 90700, 90723 | | |
| HiB (3 doses) | 90644, 90647, 90648, 90697, 90698, 90748 | | |
| HepB (3 doses) | 90697, 90723, 90740, 90744, 90747, 90748 | G0010 | B16.0, B16.1, B16.2, B16.9, B17.0, B18.0, B18.1, B19.10, B19.11 |
| IPV (3 doses) | 90697, 90698, 90713, 90723 | | |
| MMR (1 dose) | 90707, 90710 | | B05.x, B26.x, B06.x |
| PCV (4 doses) | 90670 | G0009 | |
| VZV (1 dose) | 90710, 90716 | | B01.x, B02.x |
| HepA (1 dose) | 90633 | | B15.0, B15.9 |
| Rotavirus (2 or 3 doses) | 90680, 90681 | | |
| Influenza (2 doses) | 90655, 90657, 90660, 90661, 90672, 90674, 90685–90689, 90756 | | |

### Exclusions
- Members with contraindication to specific vaccine → exclude from that vaccine's rate
- Contraindication must be documented before 2nd birthday
- Global exclusions apply

### Care Gap = OPEN if
Any of the Combination 10 vaccines is missing before 2nd birthday.

---

## MEASURE 9: Immunizations for Adolescents (IMA-E) ★ ECDS

### Eligibility
- **Age:** Members who turn 13 during measurement year

### Combo 1 and Combo 2 — Required by 13th birthday

| Vaccine | CPT | Timing |
|---|---|---|
| Meningococcal (MenACWY or MenABCWY) | 90619, 90623, 90733, 90734 | 11th–13th birthday |
| Tdap | 90715 | 10th–13th birthday |
| HPV (2 doses, ≥146 days apart OR 3 doses) | 90649, 90650, 90651 | 9th–13th birthday |

### Exclusions
- Hospice
- Anaphylactic reaction to specific vaccine on or before 13th birthday
- Tdap: encephalopathy with vaccine adverse-effect code
- Global exclusions

---

## MEASURE 10: Lead Screening in Children (LSC)

### Eligibility
- **Age:** Children age 2 (tested at 12 months, 24 months, or up to 72 months if not yet done)

### What qualifies
| Description | CPT |
|---|---|
| Lead blood test (capillary or venous) | 83655 |

### Care Gap = OPEN if
No lead test by 2nd birthday (or documented by age 72 months if no prior test).

---

## MEASURE 11: Weight Assessment and Counseling — Children/Adolescents (WCC)

### Eligibility
- **Age:** 3–17 as of December 31 of measurement year
- Must have had outpatient visit with PCP or OB/GYN during measurement year

### Three sub-rates required

| Component | CPT | HCPCS | ICD-10 |
|---|---|---|---|
| BMI percentile documentation | | | Z68.51–Z68.54 |
| Nutrition counseling | 97802–97804 | G0270, G0271, G0447, S9449, S9452, S9470 | Z71.3 |
| Physical activity counseling | | G0447, S9451 | Z02.5, Z71.82 |

### Note
Telephone, e-visit, and virtual check-ins count for nutrition and physical activity counseling.

---

## MEASURE 12: Well-Child Visits in First 30 Months (W30)

### Eligibility
- Medicaid children turning 15 or 30 months during measurement year

### Two Rates

| Rate | Population | Required visits |
|---|---|---|
| Rate 1: First 15 months | Children turning 15 months | 6 or more well-child visits |
| Rate 2: Ages 15–30 months | Children turning 30 months | 2 or more well-child visits |

### What qualifies (Well-Care Visit)
| CPT | HCPCS | ICD-10 |
|---|---|---|
| 99381, 99382, 99383, 99384, 99385, 99391, 99392, 99393, 99394, 99395, 99461 | G0438, G0439, S0302, S0610, S0612, S0613 | Z00.00, Z00.01, Z00.110, Z00.111, Z00.121, Z00.129, Z00.2, Z00.3, Z01.411, Z01.419, Z02.5, Z02.84, Z76.1, Z76.2 |

---

# PART 3 — PREGNANT MEMBERS

---

## MEASURE 13: Prenatal and Postpartum Care (PPC)

### Eligibility
- Members with live births between October 8 of prior year and October 7 of measurement year

### Two Rates

#### Rate 1: Timeliness of Prenatal Care
First prenatal visit in first trimester, or on enrollment date, or within 42 days of enrollment.

| Description | CPT | CPT-CAT-II | HCPCS | ICD-10 |
|---|---|---|---|---|
| Standalone prenatal visit | 99500 | 0500F, 0501F, 0502F | H1000–H1004 | |
| Prenatal + pregnancy diagnosis | 99202–99205, 99211–99215, 99242–99245, 99483 | | G0463, T1015 | (pregnancy diagnosis codes) |
| Prenatal bundle | 59400, 59425, 59426, 59510, 59610, 59618 | | H1005 | |
| Telephone | 98966–98968, 99441–99443 | | | |
| E-visit / telehealth | 98970–98972, 98980, 98981, 99421–99423, 99457, 99458 | | G0071, G2010, G2012, G2250–G2252 | |

#### Rate 2: Postpartum Care
Visit on or between day 7 and day 84 after delivery.

| Description | CPT | HCPCS | ICD-10 |
|---|---|---|---|
| Postpartum visit | 57170, 99501, 58300, 59430, 0503F | G0101 | |
| Postpartum care encounter | | | Z01.411, Z01.419, Z01.42, Z30.430, Z39.1, Z39.2 |
| Cervical cytology | 88141–88143, 88147, 88148, 88150, 88152, 88153, 88164–88167, 88174, 88175 | G0123, G0124, G0141, G0143–G0148, P3000, P3001, Q0091 | |
| Postpartum bundle | 59400, 59410, 59510, 59515, 59610, 59614, 59618, 59622 | | |
| Telephone / telehealth | 98966–98968, 99441–99443 | | |
| E-visit | 98970–98972, 98980, 98981, 99421–99423, 99457, 99458 | G0071, G2010, G2012, G2250–G2252 | |

---

## MEASURE 14: Prenatal Immunization Status (PRS-E)

### Eligibility
- Members with live births January 1 – December 31 of measurement year

### Both vaccines required

| Vaccine | CPT |
|---|---|
| Tdap | 90715 |
| Influenza (adult) | 90686, 90688, 90630, 90682 |

---

# PART 4 — LIVING WITH CHRONIC CONDITIONS

---

## MEASURE 15: Cardiac Rehabilitation (CRE)

### Eligibility
- **Age:** 18+ as of qualifying cardiac event
- Qualifying cardiac event: July 1 prior year – June 30 of measurement year
- Most recent cardiac event date is used

### Qualifying Event Codes

| Event | CPT | HCPCS | ICD-10 |
|---|---|---|---|
| Myocardial infarction (MI) | | | I21.01, I21.02, I21.09, I21.11, I21.19, I21.21, I21.29, I21.3, I21.4, I21.9, I21.A1, I21.A9, I22.0–I22.2, I22.8, I22.9, I23.0–I23.8, I25.2 |
| CABG | 33510–33519, 33521–33523, 33530, 33533–33536 | S2205–S2209 | |
| Heart transplant | 33927, 33928, 33935, 33945 | | |
| Heart valve repair/replacement | 33361–33369, 33390, 33391, 33404–33406, 33410–33420, 33422, 33425–33427, 33430, 33440, 33460, 33463–33465, 33468, 33470, 33471, 33474–33478 | | |
| PCI | 92920, 92924, 92928, 92933, 92937, 92941, 92943 | C9600, C9602, C9604, C9606, C9607 | |

### Cardiac Rehabilitation Service Codes
| CPT | HCPCS |
|---|---|
| 93797, 93798 | G0422, G0423, S9472 |

### Four Rates Reported

| Rate | Sessions Required | Timeframe |
|---|---|---|
| Initiation | 2+ sessions | Within 30 days of event |
| Engagement 1 | 12+ sessions | Within 90 days |
| Engagement 2 | 24+ sessions | Within 180 days |
| Achievement | 36+ sessions | Within 180 days |

### Exclusions
- Global exclusions (hospice, deceased)
- Additional cardiac discharges within 180 days of qualifying event
- Palliative care: G9054, M1017, Z51.5
- Medicare I-SNP, LTI, age 66+
- Frailty + advanced illness (ages 66–80)
- Frailty alone (age 81+)

---

## MEASURE 16: Controlling Blood Pressure (CBP)

### Eligibility
- **Age:** 18–85 with hypertension (ICD I10)
- Must have at least 2 outpatient HTN visits between Jan 1 of prior year and June 30 of measurement year

### What qualifies — BP adequately controlled
BP reading < 140/90 mmHg. Remote measurements (digital device) are acceptable. Member-reported documented in chart counts.

| Description | CPT-CAT-II | ICD-10 |
|---|---|---|
| Essential hypertension | | I10 |
| Systolic < 130 | 3074F | |
| Systolic 130–139 | 3075F | |
| Systolic ≥ 140 | 3077F | |
| Diastolic < 80 | 3078F | |
| Diastolic 80–89 | 3079F | |
| Diastolic ≥ 90 | 3080F | |

### Visit Types Accepted
In-person · Telephone · Telehealth

### Exclusions
- Global exclusions
- Frailty + advanced illness (ages 66–80)
- Frailty alone (age 81+ with 2 indicators)
- Active pregnancy diagnosis
- ESRD, kidney transplant, total nephrectomy, or dialysis

### Care Gap = OPEN if
Most recent BP reading ≥ 140/90 mmHg, or no BP reading in measurement year.

### Neo4j Rule Properties
```
Measure.id = "CBP"
CareGapRule.min_age = 18
CareGapRule.max_age = 85
CareGapRule.trigger_icd = "I10"  (hypertension required)
CareGapRule.value_threshold = "< 140/90"
CareGapRule.lookback_months = 12
ExclusionCondition: ESRD (N18.6), dialysis, pregnancy, frailty
```

---

## MEASURE 17: Persistence of Beta-Blocker Treatment After Heart Attack (PBH)

### Eligibility
- **Age:** 18+ as of December 31 of measurement year
- Hospitalized and discharged July 1 of prior year – June 30 of measurement year for AMI

### Qualifying Event Codes
| Description | ICD-10 |
|---|---|
| Acute MI (AMI) | I21.01, I21.02, I21.09, I21.11, I21.19, I21.21, I21.29, I21.3, I21.4 |

### What qualifies
Persistent beta-blocker treatment for 6 months after discharge. No specific codes — based on pharmacy claim continuity.

### Exclusions
- Global exclusions
- Frailty + advanced illness (66–80), frailty (81+)
- Any of:
  - Asthma
  - COPD
  - Obstructive chronic bronchitis
  - Chronic respiratory conditions (fumes/vapors)
  - Hypotension, heart block > 1 degree, sinus bradycardia
  - Medication history indicating asthma
  - Intolerance or allergy to beta-blocker therapy

---

## MEASURE 18: Pharmacotherapy Management of COPD Exacerbation (PCE)

### Eligibility
- **Age:** 40+ as of January 1 of measurement year
- Had acute inpatient discharge or ED visit for COPD between January 1 – November 30 of measurement year

### What qualifies — BOTH within specified windows
1. Systemic corticosteroid dispensed OR active prescription within **14 days** of event
2. Bronchodilator dispensed OR active prescription within **30 days** of event

*No specific CPT codes for numerator — based on pharmacy claims.*

### Exclusions
- Global required exclusions only

---

## MEASURE 19: Plan All-Cause Readmission (PCR)

### Eligibility
- Medicaid: ages 18–64 as of January 1 of measurement year
- Medicare: ages 18+ as of January 1 of measurement year
- Acute inpatient discharges January 1 – December 1 of measurement year

### What is measured
Unplanned acute readmission within 30 days of discharge.

*Lower rate = better performance. No codes — calculation-based.*

---

# PART 5 — DIABETES MANAGEMENT

---

## MEASURE 20: Blood Pressure Control for Patients with Diabetes (BPD)

### Eligibility
- **Age:** 18–75 with diabetes (Type 1 or Type 2)
- Diagnosis: ICD E08–E13 (diabetes)
- As of December 31 of measurement year

### What qualifies
BP reading < 140/90 mmHg. Remote/digital device measurements acceptable. CPT-CAT-II codes:

| BP Reading | CPT-CAT-II |
|---|---|
| Systolic < 130 | 3074F |
| Systolic 130–139 | 3075F |
| Systolic ≥ 140 | 3077F |
| Diastolic < 80 | 3078F |
| Diastolic 80–89 | 3079F |
| Diastolic ≥ 90 | 3080F |

### Exclusions
- Global exclusions
- Optional: Polycystic ovarian syndrome, gestational diabetes, steroid-induced diabetes

### Neo4j Rule Properties
```
Measure.id = "BPD"
CareGapRule.trigger_icd = "E08–E13"
CareGapRule.min_age = 18
CareGapRule.max_age = 75
CareGapRule.value_rule = "BP < 140/90"
```

---

## MEASURE 21: Eye Exam for Patients with Diabetes (EED)

### Eligibility
- **Age:** 18–75 with diabetes (Type 1 or Type 2)
- Administrative reporting only

### What qualifies

| Description | CPT | CPT-CAT-II | HCPCS |
|---|---|---|---|
| Retinal eye exams | 92002, 92004, 92012, 92014, 92018, 92019, 92134, 92201, 92202, 92230, 92235, 92240, 92250, 92260, 99203–99205, 99213–99215, 99242–99245, 98980, 98981 | | S0620, S0621, S3000 |
| Diabetic retinal screening negative prior year | | 3072F | |
| Retinal imaging | 92227, 92228 | | |
| Eye exam — with retinopathy evidence | | 2022F, 2024F, 2026F | |
| Eye exam — without retinopathy evidence | | 2023F, 2025F, 2033F | |

### Exclusions (Unilateral eye enucleation combined = bilateral)
| Description | CPT | ICD-10 | Modifier |
|---|---|---|---|
| Unilateral enucleation + bilateral modifier | 65091, 65093, 65101, 65103, 65105, 65110, 65112, 65114 | | 50 |
| Left eye enucleation | | 08T1XZZ | |
| Right eye enucleation | | 08T0XZZ | |

### Care Gap = OPEN if
No qualifying eye exam in measurement year (or negative screen from prior year documented).

### Neo4j Rule Properties
```
Measure.id = "EED"
CareGapRule.trigger_icd = "E08–E13"
CareGapRule.min_age = 18
CareGapRule.max_age = 75
CareGapRule.lookback_months = 12
```

---

## MEASURE 22: Glycemic Status Assessment for Patients with Diabetes (GSD)

### Eligibility
- **Age:** 18–75 with diabetes
- As of December 31 of measurement year

### What qualifies — HbA1c test performed

| Description | CPT | CPT-CAT-II |
|---|---|---|
| HbA1c test | 83036, 83037 | |
| HbA1c < 7.0% | | 3044F |
| HbA1c 7.0%–7.9% | | 3051F |
| HbA1c 8.0%–8.9% | | 3052F |
| HbA1c < 9.0% (any controlled) | | 3046F |

### Two rates reported
- HbA1c control (< 8.0%) — higher = better
- HbA1c poor control (> 9.0%) — lower = better

**Note: Member is NOT in numerator if HbA1c test was NOT performed.**

### Exclusions
- Global exclusions
- Optional: Polycystic ovarian syndrome, gestational diabetes, steroid-induced diabetes

### Care Gap = OPEN if
No HbA1c test in measurement year, OR most recent HbA1c > 9.0%.

### Neo4j Rule Properties
```
Measure.id = "GSD"
CareGapRule.trigger_icd = "E08–E13"
CareGapRule.min_age = 18
CareGapRule.max_age = 75
CareGapRule.lookback_months = 12
CareGapRule.value_rule = "HbA1c result required"
CareGapRule.threshold_poor_control = 9.0
```

---

## MEASURE 23: Kidney Health Evaluation for Patients with Diabetes (KED)

### Eligibility
- **Age:** 18–85 with diabetes (Type 1 and Type 2)
- As of December 31 of measurement year

### What qualifies — BOTH required in same year

| Test | CPT |
|---|---|
| eGFR | 80047, 80048, 80050, 80053, 80069, 82565 |
| Quantitative urine albumin | 82043 |
| Urine creatinine | 82570 |

**Rule:** Urine albumin AND urine creatinine must be within 4 days of each other, PLUS eGFR.

### Exclusions

| Exclusion | CPT | HCPCS | ICD-10 |
|---|---|---|---|
| ESRD | | | N18.5, N18.6, Z99.2 |
| Dialysis | 90935, 90937, 90945, 90947, 90997, 90999, 99512 | G0257, S9339 | |
| Palliative care | | | Z51.5 |
| Global exclusions | | | |

### Care Gap = OPEN if
Missing eGFR OR missing urine albumin/creatinine pair within 4 days.

### Neo4j Rule Properties
```
Measure.id = "KED"
CareGapRule.trigger_icd = "E08–E13"
CareGapRule.min_age = 18
CareGapRule.max_age = 85
CareGapRule.lookback_months = 12
CareGapRule.rule_type = "ALL_REQUIRED" (eGFR + albumin + creatinine within 4 days)
ExclusionCondition: ESRD (N18.5, N18.6, Z99.2), dialysis CPTs
```

---

## MEASURE 24: Statin Therapy for Patients with Diabetes (SPD)

### Eligibility
- **Age:** 40–75 as of December 31 of measurement year
- With diabetes, WITHOUT clinical ASCVD
- Insurance: Medicaid

### Two Rates

| Rate | Description |
|---|---|
| Received Statin Therapy | At least 1 statin (any intensity) dispensed during measurement year |
| Statin Adherence 80% | Remained on statin for ≥ 80% of treatment period |

*No specific CPT codes for numerator — based on pharmacy claims for any statin.*

### Exclusions
- Global exclusions
- Myalgia, myositis, myopathy, or rhabdomyolysis
- Palliative care during measurement year
- Cardiovascular disease, pregnancy, cirrhosis, ESRD, dialysis
- In vitro fertilization, or clomiphene dispensed in measurement year or prior year
- Frailty + advanced illness (age 66+)

### Neo4j Rule Properties
```
Measure.id = "SPD"
CareGapRule.trigger_icd = "E08–E13"
CareGapRule.min_age = 40
CareGapRule.max_age = 75
CareGapRule.rule_type = "MEDICATION_REQUIRED"
CareGapRule.medication_class = "statin"
ExclusionCondition: myalgia, ASCVD present, ESRD, dialysis
```

---

## MEASURE 25: Statin Therapy for Patients with Cardiovascular Disease (SPC)

### Eligibility
- **Males:** Ages 21–75
- **Females:** Ages 40–75
- With clinical ASCVD (atherosclerotic cardiovascular disease)

### Two Rates
| Rate | Description |
|---|---|
| Received Statin Therapy | At least 1 high- or moderate-intensity statin dispensed |
| Statin Adherence 80% | Remained on statin ≥ 80% of treatment period |

*Based on pharmacy claims — no CPT codes.*

### Exclusions
- Myalgia, myositis, myopathy, rhabdomyolysis, palliative care
- Cardiovascular disease, pregnancy, cirrhosis, ESRD, dialysis
- Clomiphene dispensed in measurement year or prior year
- Frailty + advanced illness (age 66+)

---

# PART 6 — BEHAVIORAL HEALTH

---

## MEASURE 26: Cardiovascular Monitoring for People with Cardiovascular Disease and Schizophrenia (SMC)

### Eligibility
- **Age:** 18–64
- Diagnosis: Schizophrenia AND heart disease

### Schizophrenia ICD-10 Codes
F20.0, F20.1, F20.2, F20.3, F20.5, F20.81, F20.89, F20.9, F25.0, F25.1, F25.8, F25.9

### What qualifies — LDL-C test

| CPT | CPT-CAT-II |
|---|---|
| 80061, 83700, 83701, 83704, 83721 | 3048F, 3049F, 3050F |

### Care Gap = OPEN if
No LDL-C test in measurement year.

---

## MEASURE 27: Diabetes Monitoring for Patients with Diabetes and Schizophrenia (SMD)

### Eligibility
- **Age:** 18–64
- Diagnosis: Schizophrenia OR schizoaffective disorder AND diabetes

### What qualifies — BOTH tests required

| Test | CPT | CPT-CAT-II |
|---|---|---|
| HbA1c test | 83036, 83037 | 3044F, 3046F, 3051F, 3052F |
| LDL-C test | 80061, 83700, 83701, 83704, 83721 | 3048F–3050F |

---

## MEASURE 28: Diabetes Screening for People with Schizophrenia or Bipolar Disorder on Antipsychotics (SSD)

### Eligibility
- **Age:** 18–64
- Diagnosis: Schizophrenia, schizoaffective disorder, or bipolar disorder
- Dispensed an antipsychotic medication during measurement year

### What qualifies — Diabetes test

| Test | CPT | CPT-CAT-II |
|---|---|---|
| HbA1c | 83036, 83037 | 3044F, 3046F, 3051F, 3052F |
| Glucose | 80047, 80048, 80050, 80053, 80069, 82947, 82950, 82951 | |

---

## MEASURE 29: Follow-Up After ED Visit for Substance Use Disorder (FUA)

### Eligibility
- **Age:** 13+ with principal diagnosis of SUD or drug overdose in ED

### SUD Diagnosis Codes
F10.xx–F16.xx, F18.xx–F19.xx, T40.xx–T43.xx, T51.xx

### Two Rates
- Follow-up within 7 days (8 total days including discharge day)
- Follow-up within 30 days (31 total days)

### What qualifies for follow-up

| Type | CPT | HCPCS | POS |
|---|---|---|---|
| Outpatient visit with SUD diagnosis | 90791, 90792, 90832–90840, 90845, 90847, 90849, 90853, 90875, 90876, 99221–99223, 99231–99233, 99238, 99239, 99251–99255 | | 03,05,07,09,11–20,22,33,49,50,71,72 |
| BH outpatient | 98960–98962, 99078, 99202–99205, 99211–99215, 99241–99245, 99341–99350, 99381–99387, 99391–99397, 99401–99404, 99411, 99412, 99483, 99492–99494 | G0176, G0409, G0463, H0002, H0004, H0031, H0034, H0036–H0040, H2000, H2010–H2020, T1015 | |
| Telephone / telehealth | 98966–98968, 99441–99443 | | 02 |
| E-visit | 98970–98972, 99421–99423, 99444, 99457, 99458, 98980, 98981 | G0071, G2010, G2012, G2250–G2252 | |
| SUD service / counseling | 99408, 99409 | G0396, G0397, G0443, H0001, H0005, H0007, H0015, H0016, H0022, H0047, H0050, H2035, H2036, T1006, T1012 | |
| AOD medication treatment | | G2067–G2070, G2072, G2073, H0020, H0033, J0570–J0578, J2315, Q9991–Q9992, S0109 | |
| Peer support services (with SUD dx) | | G0140, G0177, H0024, H0025, H0038–H0040, H0046, H2014, H2023, S9445, T1012, T1016 | |

---

## MEASURE 30: Follow-Up After ED Visit for Mental Illness (FUM)

### Eligibility
- **Age:** 6+ with principal diagnosis of mental illness in ED

### Mental Illness Diagnosis (abbreviated — full list in Appendix A)
F20.x, F21–F29, F30.x–F34.x, F39, F40.x–F43.x, F44.89, F53.x, F60.x–F63.x, F68.x, F84.x, F90.x–F94.x

### Self-Harm Diagnosis Codes
X71–X83, T36–T65, T71, R45.851

### Two Rates
- Follow-up within 7 days
- Follow-up within 30 days

### What qualifies for follow-up
Same outpatient / BH outpatient / telehealth visit types as FUA above, with mental illness diagnosis (see HCPCS/CPT tables in document section FUM).

---

## MEASURE 31: Substance Use Disorder Follow-Up After High-Intensity Care (FUI)

### Eligibility
- **Age:** 13+ with acute inpatient hospitalization, residential treatment, or detoxification for SUD

### Three Age Stratifications
13–17 · 18–64 · 65+ · Total

### Two Rates
- Follow-up within 7 days
- Follow-up within 30 days (do NOT count discharge date)

### SUD Diagnosis
ICD-10: F10.xx–F16.xx, F18.xx–F19.xx

### What qualifies
Same outpatient / BH outpatient / telephone / online assessment codes as FUA above.

---

## MEASURE 32: Follow-Up After Hospitalization for Mental Illness (FUH)

### Eligibility
- **Age:** 6+ hospitalized for mental illness or self-harm

### Two Rates
- Follow-up within 7 days
- Follow-up within 30 days

### Qualifying Provider Types
- MD/DO/APN/PA specializing in Psychiatry
- RN certified as Psychiatric Nurse or Mental Health Clinical Nurse Specialist
- Licensed Psychologist / Therapist / Counselor (LPC, LCPC) / Social Worker (LCSW)
- Certified Community Behavioral Health Center/Clinic

---

## MEASURE 33: Follow-Up Care for Children Prescribed ADHD Medication (ADD-E)

### Eligibility
- **Age:** 6–12 as of Index Prescription Start Date (IPSD)
- Newly prescribed ADHD medication

### Two Rates

| Rate | Description | Timeframe |
|---|---|---|
| Initiation Phase | 1 follow-up with prescriber | Within 30 days of IPSD |
| C&M Phase | Remained on medication 210+ days AND 2+ additional follow-up visits | Within 270 days after initiation phase end |

### What qualifies for follow-up
In-person, telephone, or telehealth:

| Type | CPT | HCPCS | POS |
|---|---|---|---|
| Outpatient | 90791, 90792, 90832–90840, 90845, 90847, 90849, 90853, 90875, 90876, 99221–99223, 99231–99233, 99238, 99239, 99251–99255 | | 03,05,07,09,11–20,22,33,49,50,71,72 |
| BH Outpatient | 98960–98962, 99078, 99202–99205, 99211–99215, 99241–99245, 99341–99350, 99381–99387, 99391–99397, 99401–99404, 99411, 99412, 99483 | G0155, G0176, G0177, G0409, G0463, H0002, H0004, H0031, H0034, H0036–H0040, H2000, H2010–H2020, T1015 | |
| Telehealth / telephone | 98966–98968, 99441–99443 | | 02 |

---

## MEASURE 34: Initiation and Engagement of AOD Treatment (IET)

### Eligibility
- **Age:** 13+ (Medicaid and Medicare)
- New episode of alcohol or other drug (AOD) abuse or dependence

### Two Rates

| Rate | Description | Timeframe |
|---|---|---|
| Initiation | Started AOD treatment | Within 14 days of diagnosis |
| Engagement | 2+ additional treatment services | Within 34 days of initiation visit |

### SUD Diagnosis Codes
F10.xx–F16.xx, F18.xx–F19.xx

### What qualifies for treatment
| Type | CPT | HCPCS |
|---|---|---|
| Telephone / telehealth | 98966–98968, 99441–99443 | |
| Online assessment | 98969–98972, 99421–99423, 99444, 99458 | G2010, G2012 |
| AOD medication | 98970–98972, 99421, 99422, 99423, 99458 | H0020, H0033, J0570–J0575, J2315, Q9991, Q9992, S0109 |

### Exclusions
Members in hospice are excluded.

---

## MEASURE 35: Metabolic Monitoring for Children on Antipsychotics (APM)

### Eligibility
- **Age:** 1–17 (Medicaid)
- Had 2+ antipsychotic prescriptions during measurement year

### Three Rates — metabolic testing required

| Test | CPT | CPT-CAT-II |
|---|---|---|
| HbA1c | 83036, 83037 | 3044F, 3046F, 3051F, 3052F |
| Glucose | 80047, 80048, 80050, 80053, 80069, 82947, 82950, 82951 | |
| LDL-C | 80061, 83700, 83701, 83704, 83721 | 3048F, 3049F, 3050F |

| Rate | Description |
|---|---|
| Rate 1 | Blood glucose OR HbA1c test |
| Rate 2 | Cholesterol OR LDL-C test |
| Rate 3 | Blood glucose AND cholesterol test |

---

## MEASURE 36: Pharmacotherapy for Opioid Use Disorder (POD)

### Eligibility
- **Age:** 16+ (report: 16–64, 65+, Total)
- Diagnosis of OUD (opioid use disorder)
- Intake Period: July 1 of prior year – June 30 of measurement year
- Must have negative medication history (no OUD pharmacotherapy) 31+ days before new dispensing

### What qualifies — OUD pharmacotherapy for 180+ days

| Type | Medication | Days Supply |
|---|---|---|
| Antagonist | Naltrexone (injectable) | 31 days per fill |
| Partial agonist | Buprenorphine (sublingual tablet) | 1 day per fill |
| Partial agonist | Buprenorphine (sublingual weekly) | 7 days per fill |
| Partial agonist | Buprenorphine (injection) | 31 days per fill |
| Partial agonist | Buprenorphine (implant) | 180 days per fill |
| Partial agonist | Buprenorphine/naloxone (film/tablet) | 1 day per fill |
| Agonist | Methadone (oral — via OTP medical claim) | 1 or 7 days per fill |

**Note:** Methadone pharmacy claims = pain treatment, NOT OUD. Only medical claims from OTP qualify.

### Exclusions
- Global required exclusions

---

# PART 7 — MEMBER INTAKE PARAMETERS REQUIRED FOR CARE GAP DETECTION

Based on the complete rulebook above, here is the definitive list of ALL parameters needed from a member at intake to run care gap analysis:

## Section A — Identity and Enrollment (always required)

| Parameter | Data Type | Why Needed |
|---|---|---|
| member_id | String | Unique identifier |
| first_name | String | Display |
| last_name | String | Display |
| date_of_birth | Date | Age calculation for ALL measures |
| sex_assigned_at_birth | Enum (M/F/Other) | BCS, CCS, CHL eligibility |
| gender_identity | String | Gender dysphoria exclusion context |
| enrollment_start_date | Date | Enrollment continuity check |
| enrollment_end_date | Date (NULL=active) | Active member check |
| insurance_type | Enum | Medicaid / Medicare / Commercial |
| plan_id | String | Health plan association |
| pcp_id | String | Primary care linkage |
| lti_flag | Boolean | Long-term institution exclusion |
| isnp_flag | Boolean | Medicare I-SNP exclusion |
| deceased_date | Date (NULL=alive) | Global exclusion |

## Section B — Diagnoses (one record per diagnosis)

| Parameter | Data Type | Why Needed |
|---|---|---|
| icd10_code | String | Measure trigger + exclusion matching |
| icd_version | String (ICD-10/ICD-11) | Code system |
| description | String | Human-readable |
| diagnosis_date | Date | Timing for historical exclusions |
| status | Enum (Active/Resolved) | Active conditions trigger measures |
| encounter_type | String | Context |

**Critical ICD codes to flag:**
- E08–E13 → diabetes → triggers BPD, EED, GSD, KED, SPD, SMD, SSD
- I10 → hypertension → triggers CBP
- I21.x → MI → triggers CRE, PBH
- F20.x, F25.x → schizophrenia → triggers SMC, SMD, SSD
- Z51.5 → palliative/hospice → global exclusion
- N18.5, N18.6 → ESRD → exclusion for CBP, KED, SPD
- Z90.13 → bilateral mastectomy history → BCS exclusion
- Z90.11, Z90.12 → absence of breasts → BCS exclusion
- Z90.710, Z90.712 → hysterectomy → CCS, CHL exclusion
- F64.1, F64.2, F64.8, Z87.890 → gender dysphoria → BCS exclusion (with CPT 19318)
- F10.xx–F19.xx → SUD → FUA, FUI, IET triggers
- 0HTV0ZZ → bilateral mastectomy procedure → BCS exclusion
- 0UTC0ZZ–0UTC8ZZ → hysterectomy procedure → CCS exclusion

## Section C — Procedures (one record per procedure)

| Parameter | Data Type | Why Needed |
|---|---|---|
| cpt_code | String | Measure satisfaction + exclusion |
| hcpcs_code | String | Alternative to CPT for some measures |
| procedure_date | Date | Measurement window check |
| modifier | String (50/LT/RT/1P etc.) | BCS mastectomy exclusion |
| place_of_service | String | Some measures require specific POS |
| quantity | Integer | Count-based measures |
| provider_id | String | Follow-up visit qualification |
| provider_specialty | String | FUH qualified provider check |

**Critical CPT codes to track:**
- 77061–77067 → mammogram → satisfies BCS
- 45378–45398 → colonoscopy → satisfies COL
- 83036, 83037 → HbA1c → satisfies GSD, SMD, SSD, APM
- 92002–92260 → eye exam → satisfies EED
- 80043, 82570 → kidney labs → satisfies KED
- 19180, 19303–19307 → mastectomy → BCS exclusion
- 19318 → gender-affirming chest surgery → BCS exclusion (if +F64.x)
- 93797, 93798 → cardiac rehab → satisfies CRE

## Section D — Lab Results (one record per lab)

| Parameter | Data Type | Why Needed |
|---|---|---|
| loinc_code | String | Lab type identification |
| result_value | Decimal | Value-based rules (HbA1c, BP) |
| result_unit | String | Unit context |
| result_date | Date | Measurement window + recency |
| normal_range | String | Pass/fail context |
| ordering_provider | String | Chain of care |

**Critical LOINC codes:**
- 4548-4 → HbA1c → GSD value check
- 76689-9 → sex assigned at birth (LA2-8 = Male) → CCS, CHL exclusion
- 13457-7 → LDL-C → SMC, SPC
- 2160-0 → creatinine → KED
- 1754-1 → albumin urine → KED

## Section E — Medications (one record per active medication)

| Parameter | Data Type | Why Needed |
|---|---|---|
| ndc_code | String | Drug identification |
| drug_name | String | Human-readable |
| drug_class | String | Statin / antipsychotic / beta-blocker / OUD |
| start_date | Date | Adherence calculation |
| end_date | Date (NULL=ongoing) | Continuity check |
| days_supply | Integer | Adherence % calculation |
| dose | String | Clinical context |
| prescriber_id | String | Follow-up linkage |

**Critical medication classes:**
- Statins (any) → SPD, SPC
- Antipsychotics → SSD, APM triggers
- Beta-blockers → PBH adherence
- OUD pharmacotherapy (buprenorphine, naltrexone, methadone-OTP) → POD
- ADHD medications → ADD-E trigger

## Section F — Vaccinations

| Parameter | Data Type | Why Needed |
|---|---|---|
| vaccine_cpt | String | Vaccine identification |
| vaccine_name | String | Human-readable |
| vaccine_date | Date | Recency + series completion |
| contraindication | Boolean | AIS, CIS exclusion per vaccine |

---

# PART 8 — QUICK REFERENCE: EXCLUSION MASTER TABLE

| Exclusion Code | Type | Affects | Action |
|---|---|---|---|
| Z51.5 | ICD | ALL measures | EXCLUDE ALL |
| G9054, M1017 | HCPCS | ALL measures | EXCLUDE ALL |
| Deceased flag | System | ALL measures | EXCLUDE ALL |
| LTI flag | System | ALL measures (Medicare 66+) | EXCLUDE |
| I-SNP flag | System | ALL measures (Medicare 66+) | EXCLUDE |
| Z90.13 | ICD | BCS only | Skip mammogram |
| 0HTV0ZZ | ICD (procedure) | BCS only | Skip mammogram |
| Z90.11 + Z90.12 | ICD (both) | BCS only | Skip mammogram |
| 0HTU0ZZ + 0HTT0ZZ | ICD (both) | BCS only | Skip mammogram |
| 19180–19307 + modifier 50 | CPT+modifier | BCS only | Skip mammogram |
| 19318 + F64.x | CPT+ICD (BOTH required) | BCS only | Skip mammogram |
| Z90.710, Z90.712 | ICD | CCS, CHL | Skip cervical screening |
| 0UTC0ZZ–0UTC8ZZ | ICD | CCS, CHL | Skip cervical screening |
| Q51.5 | ICD | CCS, CHL | Skip cervical screening |
| Sex = Male at birth | LOINC 76689-9=LA2-8 | CCS, CHL, BCS | Skip gender-specific |
| N18.5, N18.6, Z99.2 | ICD | KED, CBP, SPD | Exclude from measure |
| Dialysis CPTs | CPT | KED, CBP | Exclude |
| C18.x–C20, C21.x | ICD | COL | Exclude (colorectal cancer hx) |
| 44150–44212 | CPT | COL | Exclude (colectomy) |
| E08–E13 (frailty+illness 66+) | Clinical | BPD, KED, SPD, EED | Optional exclusion |

---

# PART 9 — MEASUREMENT YEAR AND TIMING REFERENCE

| Measure | Lookback Period | Key Date Anchor |
|---|---|---|
| AAP | 12 months | Jan 1 – Dec 31 MY |
| AIS-E (Influenza) | 12 months | MY |
| AIS-E (other vaccines) | Lifetime | Ever |
| BCS-E | 27 months | Oct 1 two years prior – Dec 31 MY |
| CCS-E (cytology) | 36 months | 3 years prior – Dec 31 MY |
| CCS-E (hrHPV) | 60 months | 5 years prior – Dec 31 MY |
| CHL | 12 months | Jan 1 – Dec 31 MY |
| COL-E (FOBT) | 12 months | MY |
| COL-E (sigmoidoscopy) | 60 months | 5 years prior |
| COL-E (colonoscopy) | 120 months | 10 years prior |
| COL-E (CT colonography) | 60 months | 5 years prior |
| COL-E (FIT-DNA) | 36 months | 3 years prior |
| EED | 12 months | Jan 1 – Dec 31 MY |
| GSD (HbA1c) | 12 months | Jan 1 – Dec 31 MY |
| KED | 12 months | Jan 1 – Dec 31 MY |
| CBP (BP reading) | 12 months | Jan 1 – Dec 31 MY |
| CRE (sessions) | 30/90/180 days | From qualifying event |
| PBH | 6 months | From hospital discharge |
| FUA, FUM, FUI, FUH | 7 days / 30 days | From ED/discharge date |
| ADD-E Initiation | 30 days | From IPSD |
| ADD-E C&M | 270 days | After initiation phase |
| IET Initiation | 14 days | From diagnosis |
| IET Engagement | 34 days | From initiation visit |
| POD | 180 days | From OUD dispensing event |
| PPC Prenatal | 1st trimester / 42 days | From enrollment or pregnancy |
| PPC Postpartum | Days 7–84 | From delivery date |

---

*Document Version: HEDIS MY2025 | Source: NCQA Technical Specifications + CountyCare Medicaid Reference Guide + Anthem BCS-E Tip Sheet*
*Use this rulebook to populate Neo4j AuraDB Measure nodes, CareGapRule nodes, CPTCode nodes, ICDCode nodes, and ExclusionCondition nodes as described in the project architecture.*
