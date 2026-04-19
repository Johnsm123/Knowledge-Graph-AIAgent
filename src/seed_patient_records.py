"""
Seed realistic dummy extended-patient-record data (lifestyle, family history,
medical history) for every existing Member so the Patient Record tab and the
agent pipeline have something meaningful to render/analyze.

Deterministic: the same member_id always produces the same dummy profile,
so re-running the seeder is idempotent and diff-friendly.

Usage:
    python -m src.seed_patient_records                 # seed ALL members
    python -m src.seed_patient_records --only M0113     # one member
    python -m src.seed_patient_records --skip-existing # do not overwrite
"""
import argparse
import hashlib
from src.neo4j_connection import get_knowledge_graph
from src.care_gap_neo4j import (
    setup_constraints,
    merge_lifestyle,
    replace_family_history,
    replace_medical_history,
)


SMOKING    = ["Never", "Former", "Current"]
ALCOHOL    = ["None", "Occasional", "Moderate", "Heavy"]
EXERCISE   = ["Sedentary", "1-2x/week", "3-4x/week", "Daily"]
DIET       = ["Balanced", "Vegetarian", "Low-carb", "High-sodium", "Fast-food-heavy"]
STRESS     = ["Low", "Moderate", "High"]

# Hereditary-relevant conditions pool (aligned with care_gap_neo4j HEREDITARY set)
FAM_COND_POOL = [
    ["Hypertension", "Diabetes Type 2"],
    ["Coronary Artery Disease"],
    ["Breast Cancer"],
    ["Colorectal Cancer"],
    ["Stroke", "Hypertension"],
    ["Asthma"],
    ["Diabetes Type 2"],
    [],
    ["Hypertension"],
    ["High Cholesterol", "Coronary Artery Disease"],
]

PAST_COND_POOL = [
    [{"name": "Bronchitis", "onset_year": "2018", "status": "resolved"}],
    [{"name": "Migraine", "onset_year": "2015", "status": "resolved"}],
    [],
    [{"name": "Anemia", "onset_year": "2020", "status": "resolved"}],
]

CURRENT_COND_POOL = [
    [{"name": "Hypertension", "onset_year": "2021"}],
    [{"name": "Type 2 Diabetes", "onset_year": "2019"}],
    [{"name": "High Cholesterol", "onset_year": "2022"}],
    [],
    [{"name": "Asthma", "onset_year": "2010"}],
]

SURGERY_POOL = [
    [{"name": "Appendectomy", "year": "2012"}],
    [],
    [{"name": "Knee arthroscopy", "year": "2019"}],
]

ALLERGY_POOL = [
    [{"substance": "Penicillin", "severity": "moderate", "reaction": "rash"}],
    [{"substance": "Peanuts", "severity": "severe", "reaction": "anaphylaxis"}],
    [],
    [{"substance": "Pollen", "severity": "mild", "reaction": "sneezing"}],
]

MEDICATION_POOL = [
    [{"name": "Lisinopril", "dose": "10mg", "started": "2021", "purpose": "BP control"}],
    [{"name": "Metformin", "dose": "500mg BID", "started": "2019", "purpose": "Diabetes"}],
    [{"name": "Atorvastatin", "dose": "20mg", "started": "2022", "purpose": "Cholesterol"}],
    [],
]

IMMUNIZATION_POOL = [
    [{"name": "Influenza", "year": "2025"}, {"name": "Tdap", "year": "2020"}],
    [{"name": "Influenza", "year": "2024"}],
    [{"name": "COVID-19", "year": "2023"}, {"name": "Influenza", "year": "2025"}],
]


def _pick(seed_str: str, bucket: int, pool: list):
    """Deterministic pick from a pool, varied per member and per bucket."""
    h = hashlib.md5(f"{seed_str}:{bucket}".encode()).hexdigest()
    idx = int(h[:8], 16) % len(pool)
    return pool[idx]


def _bmi(height_cm, weight_kg):
    if not height_cm or not weight_kg:
        return None
    return round(weight_kg / ((height_cm / 100) ** 2), 1)


def build_lifestyle(mid: str) -> dict:
    h = int(hashlib.md5(f"{mid}:h".encode()).hexdigest()[:4], 16)
    height_cm = 155 + (h % 30)            # 155–184 cm
    weight_kg = 55 + ((h >> 3) % 45)       # 55–99 kg
    return {
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "bmi": _bmi(height_cm, weight_kg),
        "smoking_status":     _pick(mid, 1, SMOKING),
        "alcohol_use":        _pick(mid, 2, ALCOHOL),
        "exercise_frequency": _pick(mid, 3, EXERCISE),
        "diet_type":          _pick(mid, 4, DIET),
        "sleep_hours_avg":    6 + (h % 3),   # 6–8
        "stress_level":       _pick(mid, 5, STRESS),
        "notes": "Auto-seeded demo data.",
    }


def build_family(mid: str) -> list:
    father_cond  = _pick(mid, 10, FAM_COND_POOL)
    mother_cond  = _pick(mid, 11, FAM_COND_POOL)
    sibling_cond = _pick(mid, 12, FAM_COND_POOL)
    family = [
        {
            "relation": "father",
            "name": "",
            "alive": bool(int(hashlib.md5(f"{mid}:fa".encode()).hexdigest()[:2], 16) % 2),
            "age_or_age_at_death": 60 + (int(hashlib.md5(f"{mid}:fb".encode()).hexdigest()[:2], 16) % 25),
            "conditions": father_cond,
            "cause_of_death": "",
            "notes": "",
        },
        {
            "relation": "mother",
            "name": "",
            "alive": True,
            "age_or_age_at_death": 55 + (int(hashlib.md5(f"{mid}:mo".encode()).hexdigest()[:2], 16) % 25),
            "conditions": mother_cond,
            "cause_of_death": "",
            "notes": "",
        },
        {
            "relation": "sibling",
            "name": "",
            "alive": True,
            "age_or_age_at_death": 30 + (int(hashlib.md5(f"{mid}:si".encode()).hexdigest()[:2], 16) % 20),
            "conditions": sibling_cond,
            "cause_of_death": "",
            "notes": "",
        },
    ]
    return family


def build_history(mid: str, existing_chronic: list) -> dict:
    # Merge member's existing chronic list into current_conditions (preserves prior data)
    existing_current = [{"name": c} for c in (existing_chronic or []) if c]
    pool_current = _pick(mid, 20, CURRENT_COND_POOL)
    # Deduplicate by name
    seen = {c["name"].lower() for c in existing_current}
    for c in pool_current:
        if c["name"].lower() not in seen:
            existing_current.append(c)
            seen.add(c["name"].lower())

    return {
        "past_conditions":    _pick(mid, 21, PAST_COND_POOL),
        "current_conditions": existing_current,
        "surgeries":          _pick(mid, 22, SURGERY_POOL),
        "allergies":          _pick(mid, 23, ALLERGY_POOL),
        "medications":        _pick(mid, 24, MEDICATION_POOL),
        "immunizations":      _pick(mid, 25, IMMUNIZATION_POOL),
    }


def seed(only: str = None, skip_existing: bool = False):
    setup_constraints()
    kg = get_knowledge_graph()

    if only:
        rows = kg.run_query(
            "MATCH (m:Member {member_id: $mid}) RETURN m.member_id AS member_id, m.chronic_conditions AS cc",
            {"mid": only},
        )
    else:
        rows = kg.run_query(
            "MATCH (m:Member) RETURN m.member_id AS member_id, m.chronic_conditions AS cc",
            {},
        )

    print(f"[seed] Seeding {len(rows)} member(s)")
    ls_n = fh_n = mh_n = 0

    for row in rows:
        mid = row.get("member_id")
        if not mid:
            continue

        if skip_existing:
            ex = kg.run_query("""
                MATCH (m:Member {member_id: $mid})
                OPTIONAL MATCH (m)-[:HAS_RELATIVE]->(fm)
                WITH m, count(fm) AS fm_n
                OPTIONAL MATCH (m)-[:HAS_MEDICAL_HISTORY]->(e)
                RETURN fm_n, count(e) AS mh_n
            """, {"mid": mid})
            if ex and (ex[0]["fm_n"] > 0 or ex[0]["mh_n"] > 0):
                print(f"  - {mid}: already has data, skipped")
                continue

        merge_lifestyle(mid, build_lifestyle(mid));                  ls_n += 1
        replace_family_history(mid, build_family(mid));              fh_n += 1
        replace_medical_history(mid, build_history(mid, row.get("cc"))); mh_n += 1
        print(f"  + {mid}: seeded")

    print(f"[seed] Lifestyle: {ls_n}   FamilyHistory: {fh_n}   MedicalHistory: {mh_n}")
    print("[seed] Done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Seed only this member_id (e.g. M0113)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip members that already have family/medical history data")
    args = ap.parse_args()
    seed(only=args.only, skip_existing=args.skip_existing)
