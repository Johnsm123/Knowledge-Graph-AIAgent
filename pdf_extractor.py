"""
pdf_extractor.py
Reads a HEDIS measure document (PDF or TXT) — single or multi-measure —
and uses Azure OpenAI to extract structured measure rules.
Saves one config JSON per measure found.

Usage:
  python pdf_extractor.py measures/bcs_e.pdf        ← single measure PDF
  python pdf_extractor.py measures/HWhole.pdf       ← multi-measure PDF
  python pdf_extractor.py measures/bcs_e.txt        ← plain text file
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


def read_input(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            print("pdfplumber not installed. Run: pip install pdfplumber")
            sys.exit(1)
        text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text.append(t)
        return "\n".join(text)

    elif ext in (".txt", ".md"):
        with open(file_path, encoding="utf-8") as f:
            return f.read()

    else:
        print(f"Unsupported file type: {ext}. Use .pdf or .txt")
        sys.exit(1)


def detect_measures(text: str) -> list[str]:
    """Ask LLM to identify all measure IDs present in the document."""
    prompt = f"""
You are a HEDIS clinical measure expert.

Read the text below and return ONLY a valid JSON array of all HEDIS measure IDs found.
Example: ["BCS-E", "COL-E", "AAP", "CBP"]

Return ONLY the JSON array, no explanation.

TEXT:
{text[:5000]}
"""
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


SINGLE_MEASURE_SCHEMA = """
{
  "measure_id": "string (e.g. BCS-E, COL-E, AAP)",
  "measure_name": "string",
  "eligible_age_min": number,
  "eligible_age_max": number,
  "eligible_gender": "Female | Male | Any",
  "measurement_year": number,
  "lookback_years": number,
  "lookback_start_month": number,
  "lookback_start_day": number,
  "compliance_codes": {
    "CPT":   ["list of CPT codes if mentioned"],
    "LOINC": ["list if any"],
    "HCPCS": ["list if any"]
  },
  "exclusion_codes": {
    "exclusion_reason_name": {
      "CPT":      ["codes if any"],
      "ICD10CM":  ["codes if any"],
      "ICD10PCS": ["codes if any"],
      "HCPCS":    ["codes if any"],
      "note":     "plain English description if no codes available"
    }
  },
  "ab2_only_exclusions": ["exclusion names that only apply to age 66+"],
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


def extract_single_measure(text: str, measure_id: str) -> dict:
    """Extract rules for ONE specific measure from the full document text."""
    prompt = f"""
You are a HEDIS clinical measure expert.

From the text below, extract rules ONLY for measure: {measure_id}
Return ONLY valid JSON matching this exact structure:
{SINGLE_MEASURE_SCHEMA}

IMPORTANT:
- Extract every exclusion as a separate named entry in exclusion_codes
- If exclusion only applies to age 66+, add to ab2_only_exclusions
- If no codes listed for an exclusion, use the "note" field
- eligible_age_min/max come from the DENOMINATOR age range
- lookback_years = how many years back the compliance window goes
- measurement_year = use current year if not explicitly stated
- gender_criteria: only include GC1/GC2/GC3 if measure is gender-specific (Female), else return []

Return ONLY the JSON, no explanation.

FULL DOCUMENT TEXT:
{text[:30000]}
"""
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


def extract_measure_config(text: str) -> dict:
    """Legacy single-measure extraction (kept for backward compatibility)."""
    return extract_single_measure(text, "the measure described")


def save_and_print(config: dict, out_dir: str) -> str:
    out_path = os.path.join(out_dir, f"{config['measure_id'].lower().replace('-','_')}_config.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"  ✓ Saved        : {out_path}")
    print(f"    Measure      : {config['measure_id']} — {config['measure_name']}")
    print(f"    Age range    : {config['eligible_age_min']}–{config['eligible_age_max']}")
    print(f"    Gender       : {config['eligible_gender']}")
    print(f"    Lookback     : {config['lookback_years']} year(s)")
    print(f"    CPT codes    : {config['compliance_codes'].get('CPT', [])}")
    print(f"    Exclusions   : {list(config['exclusion_codes'].keys())}")
    return out_path


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python pdf_extractor.py measures/bcs_e.pdf")
        print("  python pdf_extractor.py measures/HWhole.pdf   ← multi-measure")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)

    print(f"Reading: {file_path}")
    text = read_input(file_path)
    print(f"Extracted {len(text)} characters")
    out_dir = os.path.dirname(file_path) or "measures"

    # Step 1: detect all measures in the document
    print("\nDetecting measures in document...")
    measure_ids = detect_measures(text)
    print(f"Found {len(measure_ids)} measure(s): {measure_ids}")

    saved_configs = []

    if len(measure_ids) == 1:
        # single measure — extract directly
        print(f"\nExtracting rules for: {measure_ids[0]}")
        config = extract_single_measure(text, measure_ids[0])
        out_path = save_and_print(config, out_dir)
        saved_configs.append(out_path)
    else:
        # multi-measure — extract each one separately
        for mid in measure_ids:
            print(f"\nExtracting rules for: {mid}...")
            try:
                config = extract_single_measure(text, mid)
                out_path = save_and_print(config, out_dir)
                saved_configs.append(out_path)
            except Exception as e:
                print(f"  ✗ Failed for {mid}: {e}")

    print(f"\n{'='*50}")
    print(f"Extracted {len(saved_configs)} measure config(s).")
    print("\nNext steps — run in order for each config:")
    for path in saved_configs:
        measure_id = os.path.basename(path).replace("_config.json", "")
        personas_path = path.replace("_config.json", "_personas.json")
        print(f"\n  # {measure_id.upper()}")
        print(f"  python persona_generator.py {path}")
        print(f"  python load_personas_to_neo4j.py {personas_path}")


if __name__ == "__main__":
    main()
