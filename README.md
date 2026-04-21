# HEDIS Care Gap Knowledge Graph — Project Guide

## What This Project Does

This project builds a **Neo4j knowledge graph** for multiple **HEDIS measures** using a fully **LLM-automated pipeline**.

It takes a HEDIS PDF document and:
1. Uses **Azure OpenAI** to extract clinical rules for every measure found in the PDF
2. Uses **Azure OpenAI** to generate ideal clinical **Persona nodes** for each measure
3. Loads all Measure, Persona, ComplianceCode, and ExclusionCode nodes into **Neo4j**
4. Evaluates real member/claims data against all measures via the **care gap engine**
5. Exposes a **REST API** for real-time BCS-E care gap lookups

---

## Project Structure

```
BCS_CareGap_API.postman_collection/
│
├── Scenario 2_care_gap_multi_measure_dataset.xlsx  ← Source data (Excel)
│
│── LLM Pipeline ──────────────────────────────────────────────────────────────
├── pipeline.py               ← MAIN SCRIPT — PDF/TXT → LLM → Neo4j (all measures)
├── pdf_extractor.py          ← Step 1: Extract measure rules from PDF/TXT via LLM
├── persona_generator.py      ← Step 2: Generate ideal personas via LLM from config
├── generic_graph_builder.py  ← Step 3: Load config + personas into Neo4j (any measure)
├── load_personas_to_neo4j.py ← Standalone: reload any personas JSON into Neo4j
├── validate_personas.py      ← Validate LLM-generated personas against measure config
│
│── BCS-E LLM Persona Agent ───────────────────────────────────────────────────
├── bcs_persona_agent.py      ← Dedicated LLM agent: generates 54 BCS-E personas with reasoning
├── bcs_agent_personas.json   ← 54 LLM-curated BCS-E personas (pre-generated, ready to load)
│
│── Care Gap Engine & API ─────────────────────────────────────────────────────
├── care_gap_engine.py        ← Evaluates all members against ALL measures → writes CareGap nodes
├── api.py                    ← Flask REST API — POST /care-gap/bcs
│
│── measures/ ──────────────────────────────────────────────────────────────────
│   ├── HWhole.pdf            ← Multi-measure HEDIS source document
│   ├── BCS.pdf               ← BCS-E measure document
│   ├── bcs_e.txt             ← BCS-E measure rules (plain text)
│   ├── *_config.json         ← LLM-extracted measure configs (one per measure)
│   └── *_personas.json       ← LLM-generated personas (one per measure)
│
│── Utilities ──────────────────────────────────────────────────────────────────
├── check_graph.py            ← Verify node/relationship counts in Neo4j
├── requirements.txt          ← Python dependencies
└── .env                      ← Neo4j + Azure OpenAI credentials (not committed)
```

---

## Supported Measures

All 9 measures are extracted automatically from `HWhole.pdf` by the LLM:  

| Measure | Name | Gender | Age Range |
|---|---|---|---|
| BCS-E | Breast Cancer Screening | Female | 50–74 |
| CCS-E | Cervical Cancer Screening | Female | 21–64 |
| CHL | Chlamydia Screening | Female | 16–24 |
| COL-E | Colorectal Cancer Screening | Any | 45–75 |
| AAP | Adults' Access to Preventive/Ambulatory Services | Any | 20–100 |
| AIS-E | Adult Immunization Status | Any | 19–100 |
| CIS-E | Childhood Immunization Status | Any | 0–2 |
| IMA-E | Immunizations for Adolescents | Any | 9–13 |
| WCV | Child and Adolescent Well-Care Visits | Any | 3–21 |

---

## How to Run

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `.env`
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your_password>
NEO4J_DATABASE=neo4j

AZURE_OPENAI_ENDPOINT=<your_endpoint>
AZURE_OPENAI_API_KEY=<your_key>
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_DEPLOYMENT=<your_deployment>
```

### 3. Run the pipeline (LLM extracts rules + generates personas + loads into Neo4j)
```bash
python pipeline.py measures/HWhole.pdf
```

### 4. Validate personas (optional — shows LLM followed all business rules)
```bash
python validate_personas.py measures/bcs_e_config.json measures/bcs_e_personas.json
```

### 5. Run the care gap engine (evaluates all members against all 9 measures)
```bash
python care_gap_engine.py
```

### 6. Verify the graph
```bash
python check_graph.py
```

### 7. Start the API
```bash
python api.py
```

### 8. Test the API
```bash
curl -X POST http://localhost:5000/care-gap/bcs \
  -H "Content-Type: application/json" \
  -d "{\"member_id\": \"M001\"}"
```

---

## Pipeline — What Each Step Does

### `pipeline.py` — Master Orchestrator
Runs all 3 steps automatically for every measure found in the PDF:
```
HWhole.pdf
    │
    ├─ LLM detects all measures → [BCS-E, CCS-E, COL-E, AAP, ...]
    │
    └─ For each measure:
         ├─ Step 1: pdf_extractor.py  → measures/*_config.json
         ├─ Step 2: persona_generator.py → measures/*_personas.json
         └─ Step 3: generic_graph_builder.py → Neo4j
```

### Run steps manually (optional)
```bash
# Step 1: Extract rules from PDF
python pdf_extractor.py measures/HWhole.pdf

# Step 2: Generate personas from config
python persona_generator.py measures/bcs_e_config.json

# Step 3: Validate
python validate_personas.py measures/bcs_e_config.json measures/bcs_e_personas.json

# Step 4: Load into Neo4j
python load_personas_to_neo4j.py measures/bcs_e_personas.json
```

---

## BCS-E Persona Agent (`bcs_persona_agent.py`)

A dedicated LLM agent specifically for BCS-E that generates 54 clinically reasoned personas.
Unlike the generic pipeline, each persona includes an `llm_reasoning` field explaining *why* that status was assigned.

```bash
python bcs_persona_agent.py
```

The output is saved to `bcs_agent_personas.json` and loaded into Neo4j automatically.
If you already have the JSON and don't want to call the LLM again:
```bash
python load_personas_to_neo4j.py bcs_agent_personas.json
```

**54 BCS-E Personas breakdown:**
- NOT_ELIGIBLE: 3 GC × 2 AB = 6
- EXCLUDED AB1: 3 GC × 5 exclusions = 15
- EXCLUDED AB2: 3 GC × 7 exclusions = 21
- COMPLIANT: 3 GC × 2 AB = 6
- OPEN_GAP: 3 GC × 2 AB = 6

---

## Care Gap Engine (`care_gap_engine.py`)

Evaluates every real member in Neo4j against **all 9 measures** using the configs in `measures/`.
Writes a `CareGap` node per member per measure and links each member to their matching `Persona`.

```
Member + Claims
    │
    └─ For each of 9 measures:
         ├─ Check eligibility (age, gender)
         ├─ Check exclusions (CPT/ICD codes from config)
         ├─ Check compliance (CPT codes within lookback window)
         └─ Write CareGap node → OPEN_GAP / COMPLIANT / EXCLUDED / NOT_ELIGIBLE
```

---

## REST API (`api.py`)

**Endpoint:** `POST /care-gap/bcs`

**Request:**
```json
{ "member_id": "M001" }
```

**Response:**
```json
{
  "member_id": "M001",
  "gender": "F",
  "age": 58,
  "measure": "BCS-E",
  "care_gap_status": "OPEN_GAP",
  "reason": "No mammography CPT found between 2024-10-01 and 2026-12-31",
  "recommendation": "Schedule a mammogram screening...",
  "lookback_window": { "start": "2024-10-01", "end": "2026-12-31" },
  "total_claims": 3
}
```

---

## Graph Schema

```
Measure
  └─[:HAS_COMPLIANCE_CODE]──► ComplianceCode
  └─[:HAS_EXCLUSION_CODE]───► ExclusionCode

Persona ──[:BELONGS_TO_MEASURE]──► Measure

Member ──[:HAS_PCP]──────────────► Provider
Member ──[:HAS_ENROLLMENT]───────► Enrollment ──[:UNDER_PLAN]──► BenefitPlan
Member ──[:HAS_CLAIM]────────────► Claim ──────[:SERVICED_BY]──► Provider
Member ──[:HAS_CARE_GAP]─────────► CareGap ───[:FOR_MEASURE]──► Measure
Member ──[:MATCHES_PERSONA]──────► Persona

Outreach ──[:FOR_CARE_GAP]───────► CareGap
Outreach ──[:OUTREACH_TO]────────► Member
```

---

## Key BCS-E Business Rules

| Rule | Detail |
|---|---|
| Eligible gender | Female (Administrative, Birth, or Clinical Use) |
| Eligible age | 50–74 years old |
| Compliance window | Oct 1 two years prior through Dec 31 of measurement year |
| Mammography CPT codes | 77061, 77062, 77063, 77065, 77066, 77067 |
| Exclusion: bilateral mastectomy | ICD-10-PCS: 0HTV0ZZ / ICD-10-CM: Z90.13 |
| Exclusion: unilateral mastectomy (both sides) | CPT: 19180–19307 / ICD-10-CM: Z90.11, Z90.12 / ICD-10-PCS: 0HTU0ZZ, 0HTT0ZZ |
| Exclusion: gender-affirming chest surgery | CPT: 19318 / ICD-10-CM: F64.1, F64.2, F64.8, F64.9, Z87.890 |
| Other exclusions | Hospice/palliative, frailty+advanced illness, deceased, institutional SNP/LTC (age 66+) |

---

## Care Gap Statuses

| Status | Meaning |
|---|---|
| `OPEN_GAP` | Eligible, enrolled, no exclusion, required service not found — needs outreach |
| `COMPLIANT` | Eligible, enrolled, required service found within lookback window |
| `EXCLUDED` | Meets an exclusion criterion — removed from measure denominator |
| `NOT_ELIGIBLE` | Age or gender outside measure eligibility criteria |

---

## Data Source

**`Scenario 2_care_gap_multi_measure_dataset.xlsx`** — contains these sheets:

| Sheet | Contents |
|---|---|
| Members | MemberID, Name, DOB, Gender, ZIP, EnrollmentStart, EnrollmentEnd, Member Age, PCPID |
| Providers | ProviderID, Name, Specialty, FacilityType, NetworkStatus, Location |
| Claims | ClaimID, MemberID, ProviderID, CPTCode, ICDCode, ServiceDate, Status |
| Enrolment Eligibility | MemberID, PlanID, PCPID, EffectiveFrom, EffectiveTo |
| BenefitPlan | PlanID, PreventiveServicesCovered, Copay, Deductible, EligibilityRules |
| CareMngnt_Outreach_Dashboard | OutreachID, CareGapID, MemberID, CareManagerID, Channel, Date, Status |
