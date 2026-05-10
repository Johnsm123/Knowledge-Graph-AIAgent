"""
One-shot wipe of all member-tied data across the three Neo4j databases:
  • Main DB (rulebook detection)
  • Reference DB (lifecycle visualization)
  • Persona-Demo DB (member-vs-persona twin)

Preserves QualityMeasure, BenefitPlan, and Provider reference data in the
main DB. Removes everything member-related so the next bulk upload starts
from a clean slate.

Usage:
    python scripts/wipe_all_members.py
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# Member-tied labels in the MAIN DB. QualityMeasure / BenefitPlan / Provider
# stay because they are reference data (not tied to a specific member).
MAIN_LABELS = [
    "Outreach", "Appointment", "CareGap", "Claim", "Enrollment",
    "Lifestyle", "FamilyMember", "Condition", "MedicalHistoryEntry",
    "Persona", "Email", "Member",
]

# Reference DB stores only member-tied lifecycle/persona data — wipe wide.
REF_LABELS = [
    "Action", "CareGap", "Persona", "Member", "Measure",
]

# Persona-Demo DB stores member, persona, lifestyle, gap nodes — wipe wide.
PERSONA_LABELS = [
    "CareGap", "ScreeningHistory", "Lifestyle", "FamilyMember",
    "Condition", "Medication", "Allergy", "Surgery", "Immunization",
    "IdealPersona", "Persona", "Member",
]


def _wipe_with_driver(label_list: list[str], run_query, name: str) -> None:
    log.info(f"[{name}] wiping {len(label_list)} label(s)…")
    for label in label_list:
        deleted_total = 0
        while True:
            res = run_query(
                f"""
                MATCH (n:{label})
                WITH n LIMIT 1000
                DETACH DELETE n
                RETURN count(n) AS deleted
                """
            )
            deleted = (res[0]["deleted"] if res else 0) or 0
            deleted_total += deleted
            if deleted == 0:
                break
        if deleted_total:
            log.info(f"[{name}]   {label}: {deleted_total}")
    log.info(f"[{name}] done.")


def wipe_main() -> None:
    from src.neo4j_connection import get_knowledge_graph
    kg = get_knowledge_graph()
    _wipe_with_driver(MAIN_LABELS, kg.run_query, "MAIN")


def wipe_reference() -> None:
    from src.neo4j_connection import get_reference_graph
    ref = get_reference_graph()
    _wipe_with_driver(REF_LABELS, ref.run_query, "REF")


def wipe_persona_demo() -> None:
    from src.persona_demo_writer import _get_driver
    drv = _get_driver()
    if drv is None:
        log.warning("[PERSONA] persona-demo DB not configured — skipping")
        return

    def run_query(q, params=None):
        with drv.session() as s:
            return [r.data() for r in s.run(q, params or {})]

    _wipe_with_driver(PERSONA_LABELS, run_query, "PERSONA")


def main() -> None:
    wipe_main()
    wipe_reference()
    wipe_persona_demo()
    log.info("All three databases wiped of member-tied data.")


if __name__ == "__main__":
    main()
