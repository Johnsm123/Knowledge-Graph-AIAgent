"""
Audit (dry-run) — list buggy members in the live Neo4j Aura DB.

A member is BUGGY if any of:
  - CareGap.primary_cpt_code or CareGap.primary_icd10 is empty
  - CareGap.primary_cpt_code or CareGap.primary_icd10 contains "," or ";"
  - The member has >1 CareGap node attached to the same QualityMeasure

This script READS only — never writes or deletes.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.care_gap_cleanup import find_buggy_members


def main() -> int:
    buggy = find_buggy_members()

    if not buggy:
        print("[OK] No buggy members found. DB is clean.")
        return 0

    print(f"[WARN] Found {len(buggy)} buggy member(s):\n")
    print(json.dumps(buggy, indent=2, default=str))
    print(f"\nTotal: {len(buggy)} member(s) would be removed if you run purge_buggy_members.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
