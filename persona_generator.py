"""
persona_generator.py
Reads a measure_config.json and uses Azure OpenAI (GPT-4o) to generate
all ideal clinical personas → saves to <measure_id>_personas.json
"""

import os, json, sys
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")


def generate_personas(config: dict) -> list:
    gender        = config.get("eligible_gender", "Any")
    is_gendered   = gender not in ("Any", "any", None, "")
    gc_codes      = [g["code"] for g in config.get("gender_criteria", [])] if is_gendered else ["ANY"]
    ab_codes      = [b["code"] for b in config.get("age_bands", [])]
    excl_names    = list(config.get("exclusion_codes", {}).keys())
    n_gc          = len(gc_codes)   # 3 for gendered measures, 1 for Any
    n_ab          = len(ab_codes)

    ab2_only      = set(config.get("ab2_only_exclusions", ["frailty_advanced_illness", "institutional_snp_or_ltc_66plus"]))
    excl_ab1      = [e for e in excl_names if e not in ab2_only]
    excl_ab2      = excl_names

    not_eligible  = n_gc * n_ab
    compliant     = n_gc * n_ab
    open_gap      = n_gc * n_ab
    excl_ab1_cnt  = n_gc * len(excl_ab1)
    excl_ab2_cnt  = n_gc * len(excl_ab2)
    excluded      = excl_ab1_cnt + excl_ab2_cnt
    total         = not_eligible + compliant + open_gap + excluded

    gender_instruction = (
        f"- Gender is ANY — do NOT use GC codes, set gender_criteria_code=null for all personas"
        if not is_gendered else
        f"- Every GC code must appear in every combination: {gc_codes}"
    )

    prompt = f"""
You are a HEDIS clinical measure expert.

Generate exactly {total} ideal clinical personas for the measure below.
Each persona = ONE unique combination of patient attributes.

EXACT BREAKDOWN REQUIRED:
- NOT_ELIGIBLE : {n_gc} GC x {n_ab} AB = {not_eligible}  (is_enrolled=false, no exclusion, no service)
- COMPLIANT    : {n_gc} GC x {n_ab} AB = {compliant}  (is_enrolled=true, has_compliance_service=true, no exclusion)
- OPEN_GAP     : {n_gc} GC x {n_ab} AB = {open_gap}  (is_enrolled=true, has_compliance_service=false, no exclusion)
- EXCLUDED AB1 : {n_gc} GC x {len(excl_ab1)} exclusions = {excl_ab1_cnt}  exclusions: {excl_ab1}
- EXCLUDED AB2 : {n_gc} GC x {len(excl_ab2)} exclusions = {excl_ab2_cnt}  exclusions: {excl_ab2}

KEY RULES:
- ONE exclusion per persona — never combine multiple exclusions
- frailty_advanced_illness and institutional_snp_or_ltc_66plus are AB2 ONLY (age 66+)
- persona_id format: {config['measure_id']}-P001 ... {config['measure_id']}-P{str(total).zfill(3)}
{gender_instruction}
- Every AB code must appear: {ab_codes}
- Do NOT skip any combination
- Total must be exactly {total}

Return ONLY a valid JSON array of persona objects with these fields:
{{
  "persona_id": "string",
  "measure": "{config['measure_id']}",
  "gender_criteria_code": "GC1 | GC2 | GC3 | null",
  "gender_criteria_description": "string or null",
  "age_band_code": "AB1 | AB2",
  "age_band_range": "string",
  "is_enrolled": true | false,
  "has_compliance_service": true | false,
  "has_any_exclusion": true | false,
  "exclusion_reason": "string or null",
  "care_gap_status": "OPEN_GAP | COMPLIANT | EXCLUDED | NOT_ELIGIBLE",
  "description": "one line plain English description"
}}

MEASURE CONFIGURATION:
{json.dumps(config, indent=2)}

Return ONLY the JSON array. Total must be exactly {total} personas.
"""
    print(f"  Expected : {total} total personas")
    print(f"  NOT_ELIGIBLE : {not_eligible} | COMPLIANT : {compliant} | OPEN_GAP : {open_gap} | EXCLUDED : {excluded} (AB1:{excl_ab1_cnt} + AB2:{excl_ab2_cnt})")

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def main():
    if len(sys.argv) < 2:
        print("Usage: python persona_generator.py <path_to_measure_config.json>")
        print("Example: python persona_generator.py measures/col_e_config.json")
        sys.exit(1)

    config_path = sys.argv[1]
    if not os.path.exists(config_path):
        print(f"File not found: {config_path}")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    print(f"Generating personas for: {config['measure_id']} — {config['measure_name']}")
    print("Sending to Azure OpenAI...")

    personas = generate_personas(config)

    out_path = os.path.join(
        os.path.dirname(config_path),
        f"{config['measure_id'].lower().replace('-','_')}_personas.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(personas, f, indent=2)

    # summary
    from collections import Counter
    status_counts = Counter(p["care_gap_status"] for p in personas)

    print(f"\nPersonas saved to: {out_path}")
    print(f"  Total personas : {len(personas)}")
    for status, count in status_counts.items():
        print(f"  {status:<20}: {count}")


if __name__ == "__main__":
    main()
