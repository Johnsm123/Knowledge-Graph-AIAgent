"""Quick inspector — print every CareGap field for one or more members."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.neo4j_connection import get_knowledge_graph


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python inspect_member.py M0139 [M0140 ...]")
        return 1

    kg = get_knowledge_graph()
    for mid in sys.argv[1:]:
        rows = kg.run_query(
            """
            MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
            RETURN g.care_gap_id      AS gap_id,
                   q.measure_id       AS measure_id,
                   g.primary_cpt_code AS cpt,
                   g.primary_icd10    AS icd,
                   g.is_open          AS is_open,
                   g.gap_status       AS status,
                   g.created_on       AS created
            ORDER BY g.created_on
            """,
            {"mid": mid},
        ) or []
        member_row = kg.run_query(
            "MATCH (m:Member {member_id: $mid}) RETURN m.name AS name, m.gender AS g, m.age_str AS age",
            {"mid": mid},
        ) or [{}]
        print(f"\n=== {mid} ({member_row[0].get('name','?')} | {member_row[0].get('g','?')} | {member_row[0].get('age','?')}) ===")
        if not rows:
            print("  (no CareGap nodes)")
            continue
        for r in rows:
            print("  " + json.dumps(r, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
