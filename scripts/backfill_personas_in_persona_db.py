"""Backfill IdealPersona links for any Member in the persona DB that has none.

  - For each Member in persona DB without a COMPARED_TO -> IdealPersona edge:
      • If the member also exists in the main DB, push a full persona
        (lifestyle, family, medical, screenings) using push_member_persona.
      • Otherwise, allocate a random P01..P99 id and create a minimal
        COMPARED_TO link to a (possibly shared) IdealPersona node.
"""
import os, sys, random
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.persona_demo_writer import (
    _get_driver as get_persona_driver,
    build_persona_comparison,
    push_member_persona,
    _allocate_persona_id,
    IDEAL_LIFESTYLE,
)
from src.care_gap_neo4j import (
    get_knowledge_graph,
    get_member_profile,
    get_member_open_gaps,
    get_member_family_history,
    get_member_medical_history,
    get_member_lifestyle,
)


def _main_db_member_ids() -> set[str]:
    kg = get_knowledge_graph()
    return {r["mid"] for r in kg.run_query("MATCH (m:Member) RETURN m.member_id AS mid")}


def main():
    drv = get_persona_driver()
    if drv is None:
        print("Persona-demo driver unavailable — aborting")
        return

    main_ids = _main_db_member_ids()
    with drv.session() as s:
        orphans = s.run("""
            MATCH (m:Member)
            WHERE NOT (m)-[:COMPARED_TO]->(:IdealPersona)
            RETURN m.member_id AS mid, m.name AS name
        """).data()
    print(f"Orphan members (no persona): {len(orphans)}")

    full, minimal = 0, 0
    for o in orphans:
        mid = o["mid"]; name = o.get("name") or mid
        if mid in main_ids:
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
                if push_member_persona(profile, cmp):
                    full += 1
                    print(f"  full push  {mid} ({name}) -> {cmp['persona_id']}")
            except Exception as e:
                print(f"  ERROR {mid}: {e}")
        else:
            pid = _allocate_persona_id(mid)
            now = datetime.now().date().isoformat()
            with drv.session() as s:
                s.run(
                    """
                    MERGE (p:IdealPersona {persona_id: $pid})
                      ON CREATE SET p.name = $pid,
                                    p.model = 'closest-fit-ideal-twin',
                                    p.compliance_score = 100.0,
                                    p.summary = $summary,
                                    p.ideal_bmi      = $bmi,
                                    p.ideal_smoking  = $smoking,
                                    p.ideal_alcohol  = $alcohol,
                                    p.ideal_exercise = $exercise,
                                    p.ideal_diet     = $diet,
                                    p.ideal_sleep_hours = $sleep,
                                    p.ideal_stress   = $stress
                    WITH p
                    MATCH (m:Member {member_id: $mid})
                    MERGE (m)-[r:COMPARED_TO]->(p)
                      ON CREATE SET r.gap_count = 0,
                                    r.gap_measures = [],
                                    r.compared_at = $now
                    """,
                    {
                        "pid": pid,
                        "mid": mid,
                        "now": now,
                        "summary": f"Closest-fit ideal twin (backfilled) for {mid}.",
                        "bmi":      IDEAL_LIFESTYLE["bmi"],
                        "smoking":  IDEAL_LIFESTYLE["smoking_status"],
                        "alcohol":  IDEAL_LIFESTYLE["alcohol_use"],
                        "exercise": IDEAL_LIFESTYLE["exercise_frequency"],
                        "diet":     IDEAL_LIFESTYLE["diet_type"],
                        "sleep":    IDEAL_LIFESTYLE["sleep_hours_avg"],
                        "stress":   IDEAL_LIFESTYLE["stress_level"],
                    },
                ).consume()
            minimal += 1
            print(f"  minimal    {mid} ({name}) -> {pid}  [not in main DB]")

    # Final verification.
    with drv.session() as s:
        remaining = s.run("""
            MATCH (m:Member)
            WHERE NOT (m)-[:COMPARED_TO]->(:IdealPersona)
            RETURN count(m) AS c
        """).single()["c"]
    print(f"\nDone. Full pushes: {full}, minimal links: {minimal}, remaining orphans: {remaining}")


if __name__ == "__main__":
    main()
