"""
Backfill Lifestyle + MedicalHistory placeholder nodes for every existing
Member, so the extended patient record UI renders cleanly (with empty
"Not recorded" fields) for members created before this schema extension.

Idempotent: uses MERGE via the existing helpers. Safe to run multiple times.

Usage:
    python -m src.backfill_patient_records
"""
from src.neo4j_connection import get_knowledge_graph
from src.care_gap_neo4j import (
    setup_constraints,
    merge_lifestyle,
    replace_medical_history,
)


EMPTY_LIFESTYLE = {
    "bmi": None, "height_cm": None, "weight_kg": None,
    "smoking_status": "", "alcohol_use": "", "exercise_frequency": "",
    "diet_type": "", "sleep_hours_avg": None, "stress_level": "",
    "notes": "",
}


def backfill():
    setup_constraints()
    kg = get_knowledge_graph()
    rows = kg.run_query("MATCH (m:Member) RETURN m.member_id AS member_id", {})
    total = len(rows)
    print(f"[backfill] Found {total} members")

    lifestyle_created = 0
    history_initialized = 0

    for row in rows:
        mid = row.get("member_id")
        if not mid:
            continue

        has_lifestyle = kg.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_LIFESTYLE]->(l:Lifestyle)
            RETURN count(l) AS n
        """, {"mid": mid})
        if not has_lifestyle or has_lifestyle[0]["n"] == 0:
            merge_lifestyle(mid, EMPTY_LIFESTYLE)
            lifestyle_created += 1

        has_history = kg.run_query("""
            MATCH (m:Member {member_id: $mid})-[:HAS_MEDICAL_HISTORY]->(e:MedicalHistoryEntry)
            RETURN count(e) AS n
        """, {"mid": mid})
        if not has_history or has_history[0]["n"] == 0:
            # If the member has chronic_conditions on the flat list, lift them
            # into current_conditions so the UI has something meaningful.
            current = kg.run_query("""
                MATCH (m:Member {member_id: $mid})
                RETURN m.chronic_conditions AS cc
            """, {"mid": mid})
            cc = (current[0].get("cc") if current else None) or []
            current_conditions = [{"name": c} for c in cc if c]
            replace_medical_history(mid, {"current_conditions": current_conditions})
            history_initialized += 1

    print(f"[backfill] Lifestyle created: {lifestyle_created}/{total}")
    print(f"[backfill] MedicalHistory initialized: {history_initialized}/{total}")
    print("[backfill] Done. Family history left empty (no inference source).")


if __name__ == "__main__":
    backfill()
