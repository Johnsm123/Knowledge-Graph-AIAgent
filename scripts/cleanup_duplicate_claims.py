"""
One-shot cleanup: remove duplicate AUTO-CLM-* claims that the buggy
auto-close pass accumulated. Keeps only the claim whose claim_id is
currently stamped on the matching CareGap (g.claim_id) — every other
auto-generated claim for that member+measure is an orphan and is deleted.

Usage:
    python scripts/cleanup_duplicate_claims.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.neo4j_connection import get_knowledge_graph


def main() -> None:
    kg = get_knowledge_graph()
    res = kg.run_query(
        """
        MATCH (m:Member)-[:HAS_CLAIM]->(c:Claim)
        WHERE c.auto_generated = true
          AND NOT EXISTS {
              MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
              WHERE g.claim_id = c.claim_id
          }
        WITH c, count(c) AS n
        DETACH DELETE c
        RETURN sum(n) AS deleted
        """, {}
    )
    n = (res[0]["deleted"] if res else 0) or 0
    print(f"deleted {n} orphan auto-generated claim(s)")


if __name__ == "__main__":
    main()
