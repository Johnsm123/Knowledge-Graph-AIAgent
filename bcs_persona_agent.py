"""
BCS-E Persona Agent
-------------------
LLM reads BCS-E rules and generates 54 ideal clinical personas.
One exclusion per persona — no impossible multi-exclusion combinations.
Saves to bcs_agent_personas.json and loads into Neo4j.
bcs_all_combinations.json is NOT touched.
"""

import os
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from neo4j import GraphDatabase

load_dotenv()

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")
OUTPUT_FILE = "bcs_agent_personas.json"

NEO4J_URI      = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

BCS_RULES = """
MEASURE: BCS-E (Breast Cancer Screening — ECDS)

ELIGIBILITY:
- Age: 52–74 (denominator)
- Gender: Female (sex assigned at birth = Female)
- Insurance: Medicaid / Medicare
- Measurement window: October 1 TWO years before measurement year through December 31 of measurement year

NUMERATOR — What qualifies as compliant:
- Mammography CPT codes: 77061, 77062, 77063, 77065, 77066, 77067

DIMENSIONS:
1. gender_criteria (3 values): GC1=AdministrativeGender=Female, GC2=SexAssignedAtBirth=Female, GC3=SexParamClinicalUse=Female
2. age_band (2 values): AB1=Age 52-65 (min_age=52, max_age=65), AB2=Age 66-74 (min_age=66, max_age=74)
3. is_enrolled: True / False
4. mammogram_via_cpt: True / False
5. exclusion (ONE at a time — never combine multiple exclusions):
   - bilateral_mastectomy (all age bands)
   - unilateral_mastectomy_both_sides (all age bands)
   - hospice_or_palliative (all age bands)
   - gender_affirming_chest_surgery (all age bands — requires BOTH CPT 19318 AND F64.x/Z87.890)
   - deceased (all age bands)
   - frailty_advanced_illness (AB2 ONLY — age 66+)
   - institutional_snp_or_ltc_66plus (AB2 ONLY — age 66+)

STATUS RULES (apply in order):
1. not enrolled → NOT_ELIGIBLE
2. enrolled + one valid exclusion → EXCLUDED
3. enrolled + no exclusion + mammogram_via_cpt=true → COMPLIANT
4. enrolled + no exclusion + mammogram_via_cpt=false → OPEN_GAP

IDEAL PERSONA COUNT = 54:
- NOT_ELIGIBLE : 3 GC × 2 AB = 6  (enrolled=False, no mammogram, no exclusion)
- EXCLUDED AB1 : 3 GC × 5 exclusions = 15  (enrolled=True, mammogram=False, one exclusion)
- EXCLUDED AB2 : 3 GC × 7 exclusions = 21  (enrolled=True, mammogram=False, one exclusion)
- COMPLIANT    : 3 GC × 2 AB = 6  (enrolled=True, mammogram=True, no exclusion)
- OPEN_GAP     : 3 GC × 2 AB = 6  (enrolled=True, mammogram=False, no exclusion)
"""

SYSTEM_PROMPT = """You are a clinical HEDIS measure expert for BCS-E (Breast Cancer Screening).

Generate exactly 54 ideal clinical personas following these rules:
- Each persona represents ONE distinct, realistic clinical scenario
- Only ONE exclusion per persona — never combine multiple exclusions
- frailty_advanced_illness and institutional_snp_or_ltc_66plus only apply to AB2 (age 66+)
- gender_affirming_chest_surgery requires BOTH CPT 19318 AND a gender dysphoria ICD

Each persona must have these HEDIS clinical fields:
- persona_id: sequential "BCS_P00001" to "BCS_P00054"
- measure: "BCS-E"
- gender_criteria_code: GC1/GC2/GC3
- gender_criteria_label
- age_band_code: AB1/AB2
- age_band_label
- min_age, max_age
- is_enrolled: true/false
- mammogram_via_cpt: true/false
- has_any_exclusion: true/false
- active_exclusions: array with at most ONE exclusion name, or empty []
- excl_bilateral_mastectomy: true/false
- excl_unilateral_mastectomy_both_sides: true/false
- excl_hospice_or_palliative: true/false
- excl_frailty_advanced_illness: true/false
- excl_gender_affirming_chest_surgery: true/false
- excl_deceased: true/false
- excl_institutional_snp_or_ltc_66plus: true/false
- care_gap_status: NOT_ELIGIBLE / EXCLUDED / COMPLIANT / OPEN_GAP
- llm_reasoning: one concise sentence explaining the status
- description: human-readable summary

Also generate these synthetic patient attributes, inferred from the persona's clinical context:
- Name: realistic full female name (gender-neutral for GC3)
- DOB: ISO date string consistent with age_band relative to 2025 (AB1: age 52-65, AB2: age 66-74)
- Gender: "Female" for GC1/GC2, "Non-binary" for GC3
- Email: synthetic email as firstname.lastname@example.com
- Phone: synthetic US phone number
- ZIP: realistic 5-digit US ZIP code
- InsuranceType: "Medicare" preferred for AB2, "Medicaid" or "Medicare" for AB1
- EnrollmentStart: ISO date consistent with is_enrolled
- EnrollmentEnd: null if currently enrolled, else a past ISO date
- PCPID: string from "PCP_001" to "PCP_010"
- PlanID: "PLAN_MA_001" for Medicare, "PLAN_MC_001" for Medicaid
- ChronicConditions: array of 1-3 conditions clinically plausible for this persona (bilateral_mastectomy -> ["History of Breast Cancer"], hospice -> ["Terminal Illness"], OPEN_GAP -> ["Hypertension","Type 2 Diabetes"])
- PastConditions: array inferred from exclusion (mastectomy -> ["Breast Cancer"], else [])
- CurrentConditions: array of active diagnoses consistent with ChronicConditions
- Surgeries: array inferred from exclusion (bilateral_mastectomy -> ["Bilateral Mastectomy"], else [])
- Allergies: array of 0-2 common drug allergies or ["None"]
- Medications: array of 1-3 medications consistent with ChronicConditions (hypertension -> ["Lisinopril"], cancer history -> ["Tamoxifen"])
- Immunizations: array of age-appropriate vaccines e.g. ["Influenza","Pneumococcal","Shingrix"]
- FamilyHistory: array of objects with keys {relation, condition, age_at_diagnosis (optional)}. Infer from persona context:
  - OPEN_GAP/COMPLIANT -> e.g. [{"relation":"Mother","condition":"Breast Cancer","age_at_diagnosis":55},{"relation":"Sister","condition":"Ovarian Cancer","age_at_diagnosis":48}]
  - bilateral/unilateral mastectomy -> [{"relation":"Mother","condition":"Breast Cancer","age_at_diagnosis":60}]
  - others -> []
- PriorScreenings: object with key "Mammogram" -> last date string if COMPLIANT (within Oct 2023 to Dec 2025), "None" if OPEN_GAP, "N/A" if EXCLUDED or NOT_ELIGIBLE
- HeightCm: integer between 155-175
- WeightKg: integer between 55-95 (higher for frailty personas)
- SmokingStatus: one of ["Never","Former","Current"] — hospice/frailty lean "Former" or "Current"
- AlcoholUse: one of ["None","Moderate","Heavy"] — most personas "None" or "Moderate"
- ExerciseFrequency: one of ["Sedentary","Light","Moderate","Active"] — frailty/hospice -> "Sedentary", COMPLIANT -> "Moderate" or "Active"
- DietType: one of ["Standard","Low-sodium","Diabetic","Vegetarian","Low-fat"] — infer from ChronicConditions
- SleepHoursAvg: float between 4.0-9.0
- StressLevel: one of ["Low","Moderate","High"] — OPEN_GAP/hospice -> "High", COMPLIANT -> "Low" or "Moderate"
- LifestyleNotes: one sentence summarizing lifestyle relevant to care gap status
- HospitalVisits: integer 0-5 (hospice/frailty -> higher, COMPLIANT -> 0-1)
- MissedAppointments: integer 0-4 (OPEN_GAP -> 1-4, COMPLIANT -> 0-1)
- FollowUpRequired: true if OPEN_GAP, false otherwise

Return ONLY valid JSON: { "personas": [ ... ] }
No markdown, no explanation outside the JSON."""


BATCH_INSTRUCTIONS = [
    # NOT_ELIGIBLE: 6 personas
    "Generate personas BCS_P00001 to BCS_P00006: NOT_ELIGIBLE (6) — 3 GC × 2 AB, enrolled=False, no mammogram, no exclusion.",
    # EXCLUDED AB1: 5 exclusions × 3 GC = 15, split into 3 batches of 5
    "Generate personas BCS_P00007 to BCS_P00011: EXCLUDED AB1 — GC1+GC2+GC3 with bilateral_mastectomy, then GC1+GC2 with unilateral_mastectomy_both_sides. enrolled=True, AB1.",
    "Generate personas BCS_P00012 to BCS_P00016: EXCLUDED AB1 — GC3 with unilateral_mastectomy_both_sides, GC1+GC2+GC3 with hospice_or_palliative, GC1 with gender_affirming_chest_surgery. enrolled=True, AB1.",
    "Generate personas BCS_P00017 to BCS_P00021: EXCLUDED AB1 — GC2+GC3 with gender_affirming_chest_surgery, GC1+GC2+GC3 with deceased. enrolled=True, AB1.",
    # EXCLUDED AB2: 7 exclusions × 3 GC = 21, split into 4 batches
    "Generate personas BCS_P00022 to BCS_P00027: EXCLUDED AB2 — 3 GC × bilateral_mastectomy, 3 GC × unilateral_mastectomy_both_sides. enrolled=True, AB2.",
    "Generate personas BCS_P00028 to BCS_P00033: EXCLUDED AB2 — 3 GC × hospice_or_palliative, 3 GC × gender_affirming_chest_surgery. enrolled=True, AB2.",
    "Generate personas BCS_P00034 to BCS_P00039: EXCLUDED AB2 — 3 GC × deceased, 3 GC × frailty_advanced_illness. enrolled=True, AB2.",
    "Generate personas BCS_P00040 to BCS_P00042: EXCLUDED AB2 — 3 GC × institutional_snp_or_ltc_66plus. enrolled=True, AB2.",
    # COMPLIANT: 6 personas
    "Generate personas BCS_P00043 to BCS_P00048: COMPLIANT (6) — 3 GC × 2 AB, enrolled=True, mammogram_via_cpt=True, no exclusion.",
    # OPEN_GAP: 6 personas
    "Generate personas BCS_P00049 to BCS_P00054: OPEN_GAP (6) — 3 GC × 2 AB, enrolled=True, mammogram_via_cpt=False, no exclusion.",
]


def call_llm(user_msg: str) -> list:
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"{user_msg}\n\nRules:\n{BCS_RULES}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=6000,
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        print(f"  WARNING: LLM response truncated (finish_reason=length). Raw snippet: {choice.message.content[-200:]}")
        raise ValueError("LLM response truncated — reduce batch size or max_tokens.")
    try:
        parsed = json.loads(choice.message.content)
    except json.JSONDecodeError as e:
        print(f"  ERROR: JSON parse failed. Snippet: {choice.message.content[-300:]}")
        raise e
    if isinstance(parsed, list):
        return parsed
    return next((v for v in parsed.values() if isinstance(v, list)), [])


def generate_personas() -> list:
    all_personas = []
    for i, instruction in enumerate(BATCH_INSTRUCTIONS, 1):
        print(f"Sending batch {i}/{len(BATCH_INSTRUCTIONS)} to LLM...")
        batch = call_llm(instruction)
        print(f"  Batch {i} returned {len(batch)} personas.")
        all_personas.extend(batch)
    return all_personas


def _flatten_persona(p: dict) -> dict:
    """Serialize nested/complex fields to Neo4j-compatible primitives."""
    flat = dict(p)
    # PriorScreenings: {"Mammogram": "None"} -> "None"
    ps = flat.get("PriorScreenings")
    flat["PriorScreenings"] = ps.get("Mammogram", "") if isinstance(ps, dict) else (ps or "")
    # FamilyHistory: list of dicts -> JSON string
    fh = flat.get("FamilyHistory")
    flat["FamilyHistory"] = json.dumps(fh) if isinstance(fh, list) and fh and isinstance(fh[0], dict) else fh
    return flat


def load_to_neo4j(personas: list):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        print("Neo4j connected.")
        with driver.session(database=NEO4J_DATABASE) as session:
            session.run("""
                MERGE (m:Measure {measure_id: 'BCS-E'})
                SET m.name = 'Breast Cancer Screening',
                    m.min_age = 52, m.max_age = 74,
                    m.eligible_gender = 'Female',
                    m.lookback_start = 'Oct 1 two years prior',
                    m.lookback_end = 'Dec 31 of measurement year'
            """)

            batch_size = 100
            loaded = 0
            for i in range(0, len(personas), batch_size):
                batch = [_flatten_persona(p) for p in personas[i:i + batch_size]]
                session.run("""
                    UNWIND $personas AS p
                    MERGE (n:Persona {persona_id: p.persona_id})
                    SET n += p
                    WITH n
                    MATCH (m:Measure {measure_id: 'BCS-E'})
                    MERGE (n)-[:BELONGS_TO_MEASURE]->(m)
                """, personas=batch)
                loaded += len(batch)
                print(f"  Loaded {loaded}/{len(personas)} personas...")

        print(f"Neo4j load complete. {len(personas)} Persona nodes created/updated.")
    finally:
        driver.close()


def main():
    print("BCS-E Persona Agent")
    print("=" * 40)
    print("LLM will generate 54 ideal clinical personas.")

    personas = generate_personas()

    if not personas:
        print("ERROR: LLM returned no personas.")
        return

    print(f"LLM generated {len(personas)} ideal personas.")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(personas, f, indent=2)
    print(f"Saved to: {OUTPUT_FILE}")

    print("\nLoading into Neo4j...")
    load_to_neo4j(personas)

    from collections import Counter
    status_counts = Counter(p.get("care_gap_status", "UNKNOWN") for p in personas)
    print(f"\n── Summary ──────────────────────────────")
    for status, count in sorted(status_counts.items()):
        print(f"  {status:<15} : {count}")
    print(f"  {'TOTAL':<15} : {len(personas)}")


if __name__ == "__main__":
    main()
