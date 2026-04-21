"""
pipeline.py — Full Auto Pipeline
Drop a PDF/TXT → LLM extracts rules → LLM generates personas → loads into Neo4j

Usage:
  python pipeline.py measures/HWhole.pdf
  python pipeline.py measures/bcs_e.txt
"""

import os, json, sys
from collections import Counter
from dotenv import load_dotenv
from openai import AzureOpenAI
from neo4j import GraphDatabase

load_dotenv()

# ── Clients ──────────────────────────────────────────────────────────────────
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

NEO4J_URI  = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USERNAME")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD")
NEO4J_DB   = os.getenv("NEO4J_DATABASE")

BATCH_SIZE = 500

# ── Step 1: Read file ─────────────────────────────────────────────────────────
def read_input(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            print("pdfplumber not installed. Run: pip install pdfplumber")
            sys.exit(1)
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        return "\n".join(pages)
    elif ext in (".txt", ".md"):
        with open(file_path, encoding="utf-8") as f:
            return f.read()
    else:
        print(f"Unsupported file type: {ext}")
        sys.exit(1)


# ── Step 2: Detect all measures ───────────────────────────────────────────────
def detect_measures(text: str) -> list:
    prompt = f"""
You are a HEDIS clinical measure expert.
Read the text below and return ONLY a valid JSON array of all HEDIS measure IDs found.
Example: ["BCS-E", "COL-E", "AAP", "CBP"]
Return ONLY the JSON array, no explanation.

TEXT:
{text[:5000]}
"""
    raw = _llm(prompt)
    return json.loads(raw)


# ── Step 3: Extract rules for one measure ────────────────────────────────────
SCHEMA = """
{
  "measure_id": "string",
  "measure_name": "string",
  "eligible_age_min": number,
  "eligible_age_max": number,
  "eligible_gender": "Female | Male | Any",
  "measurement_year": number,
  "lookback_years": number,
  "lookback_start_month": number,
  "lookback_start_day": number,
  "compliance_codes": {
    "CPT": [], "LOINC": [], "HCPCS": []
  },
  "exclusion_codes": {
    "exclusion_reason_name": {
      "CPT": [], "ICD10CM": [], "ICD10PCS": [], "HCPCS": [], "note": ""
    }
  },
  "ab2_only_exclusions": [],
  "age_bands": [
    {"code": "AB1", "min": number, "max": number},
    {"code": "AB2", "min": number, "max": number}
  ],
  "gender_criteria": [
    {"code": "GC1", "description": "AdministrativeGender=Female"},
    {"code": "GC2", "description": "SexAssignedAtBirth=Female"},
    {"code": "GC3", "description": "SexParamClinicalUse=Female"}
  ],
  "gap_statuses": ["OPEN_GAP", "COMPLIANT", "EXCLUDED", "NOT_ELIGIBLE"]
}
"""

def extract_config(text: str, measure_id: str) -> dict:
    prompt = f"""
You are a HEDIS clinical measure expert.
From the text below, extract rules ONLY for measure: {measure_id}
Return ONLY valid JSON matching this exact structure:
{SCHEMA}

RULES:
- Extract every exclusion as a separate named entry
- If exclusion only applies to age 66+, add to ab2_only_exclusions
- If no codes for an exclusion, use the "note" field
- eligible_age_min/max from DENOMINATOR age range
- gender_criteria: only include GC1/GC2/GC3 if measure is Female-specific, else return []
- measurement_year = use current year if not stated
Return ONLY the JSON.

TEXT:
{text[:30000]}
"""
    return json.loads(_llm(prompt))


# ── Step 4: Generate personas ─────────────────────────────────────────────────
def generate_personas(config: dict) -> list:
    gender      = config.get("eligible_gender", "Any")
    is_gendered = gender not in ("Any", "any", None, "")
    gc_codes    = [g["code"] for g in config.get("gender_criteria", [])] if is_gendered else ["ANY"]
    ab_codes    = [b["code"] for b in config.get("age_bands", [])]
    excl_names  = list(config.get("exclusion_codes", {}).keys())
    n_gc        = len(gc_codes)
    n_ab        = len(ab_codes)

    ab2_only     = set(config.get("ab2_only_exclusions", ["frailty_advanced_illness", "institutional_snp_or_ltc_66plus"]))
    excl_ab1     = [e for e in excl_names if e not in ab2_only]
    excl_ab2     = excl_names

    not_eligible = n_gc * n_ab
    compliant    = n_gc * n_ab
    open_gap     = n_gc * n_ab
    excl_ab1_cnt = n_gc * len(excl_ab1)
    excl_ab2_cnt = n_gc * len(excl_ab2)
    total        = not_eligible + compliant + open_gap + excl_ab1_cnt + excl_ab2_cnt

    gender_rule = (
        "- Gender is ANY — set gender_criteria_code=null for all personas"
        if not is_gendered else
        f"- Every GC code must appear in every combination: {gc_codes}"
    )

    print(f"    Expected : {total} personas  "
          f"(NOT_ELIGIBLE:{not_eligible} COMPLIANT:{compliant} "
          f"OPEN_GAP:{open_gap} EXCLUDED:{excl_ab1_cnt + excl_ab2_cnt})")

    prompt = f"""
You are a HEDIS clinical measure expert.
Generate exactly {total} clinical personas for measure {config['measure_id']}.

BREAKDOWN:
- NOT_ELIGIBLE : {n_gc} x {n_ab} = {not_eligible}  (is_enrolled=false)
- COMPLIANT    : {n_gc} x {n_ab} = {compliant}  (is_enrolled=true, has_compliance_service=true)
- OPEN_GAP     : {n_gc} x {n_ab} = {open_gap}  (is_enrolled=true, has_compliance_service=false)
- EXCLUDED AB1 : {n_gc} x {len(excl_ab1)} = {excl_ab1_cnt}  exclusions: {excl_ab1}
- EXCLUDED AB2 : {n_gc} x {len(excl_ab2)} = {excl_ab2_cnt}  exclusions: {excl_ab2}

RULES:
- ONE exclusion per persona
- persona_id format: {config['measure_id']}-P001 to {config['measure_id']}-P{str(total).zfill(3)}
{gender_rule}
- Every AB code must appear: {ab_codes}
- Total must be exactly {total}

Return ONLY a JSON array with fields:
persona_id, measure, gender_criteria_code, gender_criteria_description,
age_band_code, age_band_range, is_enrolled, has_compliance_service,
has_any_exclusion, exclusion_reason, care_gap_status, description

MEASURE CONFIG:
{json.dumps(config, indent=2)}
"""
    return json.loads(_llm(prompt))


# ── Step 5: Load into Neo4j ───────────────────────────────────────────────────
def load_to_neo4j(driver, config: dict, personas: list):
    measure_id = config["measure_id"]
    with driver.session(database=NEO4J_DB) as session:
        # Constraints
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Persona) REQUIRE p.persona_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:Measure) REQUIRE m.measure_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:ComplianceCode) REQUIRE c.code IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:ExclusionCode) REQUIRE e.code IS UNIQUE")

        # Measure node
        session.run("""
            MERGE (m:Measure {measure_id: $mid})
            SET m.name             = $name,
                m.eligible_age_min = $min_age,
                m.eligible_age_max = $max_age,
                m.eligible_gender  = $gender,
                m.lookback_years   = $lookback,
                m.measurement_year = $year
        """, mid=measure_id,
             name=config.get("measure_name"),
             min_age=config.get("eligible_age_min"),
             max_age=config.get("eligible_age_max"),
             gender=config.get("eligible_gender"),
             lookback=config.get("lookback_years"),
             year=config.get("measurement_year"))

        # Compliance codes
        for code_type, codes in config.get("compliance_codes", {}).items():
            for code in codes:
                if not code:
                    continue
                session.run("""
                    MERGE (c:ComplianceCode {code: $code})
                    SET c.type = $type, c.measure = $mid
                    WITH c MATCH (m:Measure {measure_id: $mid})
                    MERGE (m)-[:HAS_COMPLIANCE_CODE]->(c)
                """, code=code, type=code_type, mid=measure_id)

        # Exclusion codes
        for excl_name, code_map in config.get("exclusion_codes", {}).items():
            for code_type, codes in code_map.items():
                if code_type == "note" or not codes:
                    continue
                for code in codes:
                    if not code:
                        continue
                    session.run("""
                        MERGE (e:ExclusionCode {code: $code})
                        SET e.type = $type, e.exclusion_reason = $reason, e.measure = $mid
                        WITH e MATCH (m:Measure {measure_id: $mid})
                        MERGE (m)-[:HAS_EXCLUSION_CODE]->(e)
                    """, code=code, type=code_type, reason=excl_name, mid=measure_id)

        # Clear old personas for this measure
        session.run("MATCH (p:Persona {measure: $mid}) DETACH DELETE p", mid=measure_id)

        # Load personas in batches
        total = len(personas)
        for i in range(0, total, BATCH_SIZE):
            batch = personas[i:i + BATCH_SIZE]
            session.run("""
                UNWIND $batch AS p
                MERGE (node:Persona {persona_id: p.persona_id})
                SET node += p
                WITH node, p
                MATCH (m:Measure {measure_id: p.measure})
                MERGE (node)-[:BELONGS_TO_MEASURE]->(m)
            """, batch=batch)

        # Summary
        result = session.run("""
            MATCH (p:Persona {measure: $mid})
            RETURN p.care_gap_status AS status, COUNT(p) AS count
            ORDER BY status
        """, mid=measure_id)

        counts = {r["status"]: r["count"] for r in result}
        print(f"    Neo4j loaded {sum(counts.values())} personas:")
        for status, count in counts.items():
            print(f"      {status:<20}: {count}")


# ── LLM helper ────────────────────────────────────────────────────────────────
def _llm(prompt: str) -> str:
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
    return raw.strip()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py measures/HWhole.pdf")
        print("       python pipeline.py measures/bcs_e.txt")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)

    out_dir = os.path.dirname(file_path) or "measures"

    # ── Read ──────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Reading: {file_path}")
    text = read_input(file_path)
    print(f"Extracted {len(text):,} characters")

    # ── Detect measures ───────────────────────────────────────────────────────
    print("\nDetecting measures...")
    measure_ids = detect_measures(text)
    print(f"Found {len(measure_ids)} measure(s): {measure_ids}")

    # ── Connect Neo4j (verify once) ──────────────────────────────────────────
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
        print("Neo4j connected.")
    finally:
        driver.close()

    results = []

    for mid in measure_ids:
        print(f"\n{'─'*60}")
        print(f"[{mid}] Step 1/3 — Extracting rules...")
        try:
            config = extract_config(text, mid)
            config_path = os.path.join(out_dir, f"{mid.lower().replace('-','_')}_config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"    Config saved: {config_path}")

            print(f"[{mid}] Step 2/3 — Generating personas...")
            personas = generate_personas(config)
            # Force measure field to measure_id — LLM sometimes writes the full name
            for p in personas:
                p["measure"] = mid
            personas_path = os.path.join(out_dir, f"{mid.lower().replace('-','_')}_personas.json")
            with open(personas_path, "w", encoding="utf-8") as f:
                json.dump(personas, f, indent=2)
            print(f"    Personas saved: {personas_path} ({len(personas)} total)")

            print(f"[{mid}] Step 3/3 — Loading into Neo4j...")
            # Fresh Neo4j connection per measure to avoid timeout on long LLM calls
            neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
            try:
                neo4j_driver.verify_connectivity()
                load_to_neo4j(neo4j_driver, config, personas)
            finally:
                neo4j_driver.close()

            results.append({"measure": mid, "personas": len(personas), "status": "✓ SUCCESS"})

        except Exception as e:
            print(f"    ✗ FAILED: {e}")
            results.append({"measure": mid, "personas": 0, "status": f"✗ FAILED: {e}"})

    # ── Final summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("PIPELINE COMPLETE")
    print(f"{'='*60}")
    for r in results:
        print(f"  {r['status']}  {r['measure']:<10} — {r['personas']} personas loaded")


if __name__ == "__main__":
    main()
