"""One-shot sync: push every existing main-DB member into the persona-demo DB.

  - For every Member in main DB: build the persona comparison and write
    Member + IdealPersona (+ Lifestyle, FamilyMember, MedicalHistoryEntry,
    Screening) into the persona-demo DB.
  - Then remove any Member node in the persona-demo DB that has no
    COMPARED_TO -> IdealPersona edge (orphan cleanup).
  - Persona nodes themselves are kept regardless of membership.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.care_gap_neo4j import (
    get_knowledge_graph,
    get_member_profile,
    get_member_open_gaps,
    get_member_family_history,
    get_member_medical_history,
    get_member_lifestyle,
)
from src.persona_demo_writer import (
    build_persona_comparison,
    push_member_persona,
    _get_driver as get_persona_driver,
)


def main():
    kg = get_knowledge_graph()
    members = kg.run_query("MATCH (m:Member) RETURN m.member_id AS mid, m.name AS name ORDER BY m.member_id")
    print(f"Found {len(members)} members in main DB")

    pushed, failed = 0, 0
    for row in members:
        mid = row["mid"]
        name = row.get("name") or mid
        try:
            profile = get_member_profile(mid) or {"member_id": mid, "name": name}
            profile["member_id"] = mid
            cmp = build_persona_comparison(
                profile,
                get_member_open_gaps(mid) or [],
                completed=[],
                family_history=get_member_family_history(mid) or [],
                medical_history=get_member_medical_history(mid) or {},
                lifestyle=get_member_lifestyle(mid) or {},
            )
            ok = push_member_persona(profile, cmp)
            if ok:
                pushed += 1
                print(f"  pushed {mid} ({name}) -> {cmp['persona_id']}")
            else:
                failed += 1
                print(f"  FAILED {mid} ({name})")
        except Exception as e:
            failed += 1
            print(f"  ERROR {mid}: {e}")

    print(f"\nPushed {pushed}, failed {failed}")

    # Cleanup orphan members (Member without a COMPARED_TO IdealPersona).
    drv = get_persona_driver()
    if drv is None:
        print("No persona-demo driver — skipping orphan cleanup")
        return
    with drv.session() as s:
        res = s.run(
            """
            MATCH (m:Member)
            WHERE NOT (m)-[:COMPARED_TO]->(:IdealPersona)
            OPTIONAL MATCH (m)-[:HAS_LIFESTYLE]->(l:Lifestyle)
            OPTIONAL MATCH (m)-[:HAS_RELATIVE]->(fm:FamilyMember)
            OPTIONAL MATCH (m)-[:HAS_MEDICAL_HISTORY]->(mh:MedicalHistoryEntry)
            WITH collect(DISTINCT m.member_id) AS removed_ids,
                 collect(DISTINCT m) AS ms,
                 collect(DISTINCT l) AS ls,
                 collect(DISTINCT fm) AS fms,
                 collect(DISTINCT mh) AS mhs
            FOREACH (n IN ls  | DETACH DELETE n)
            FOREACH (n IN fms | DETACH DELETE n)
            FOREACH (n IN mhs | DETACH DELETE n)
            FOREACH (n IN ms  | DETACH DELETE n)
            RETURN removed_ids
            """
        ).single()
        ids = res["removed_ids"] if res else []
        print(f"Removed {len(ids)} orphan member(s) from persona DB: {ids}")


if __name__ == "__main__":
    main()
