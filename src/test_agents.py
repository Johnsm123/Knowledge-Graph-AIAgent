"""
Agent test — runs validate_and_suggest on 3 members covering all scenarios:
  M0011 — open BCS gap (42F, no mammogram within 24 months)
  M0002 — open HbA1c gap (diabetic member, E11.9 ICD)
  M0009 — COL gap exists in graph but has CPT 45380 claim (should be compliant)
"""
import sys
import io
import logging

# Force UTF-8 output so agent responses with special chars print correctly on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from src.care_gap_agents import CareGapAgentSystem

logging.basicConfig(level=logging.WARNING)

def run_test(member_id: str, system: CareGapAgentSystem):
    print(f"\n{'='*60}")
    print(f"TESTING MEMBER: {member_id}")
    print('='*60)
    result = system.validate_and_suggest(member_id)

    print(f"  Name            : {result.get('member_name')}")
    print(f"  Age             : {result.get('age')}")
    print(f"  Gender          : {result.get('gender')}")
    print(f"  Applicable Measures : {result.get('applicable_measures')}")
    print(f"  Compliant       : {result.get('compliant_measures')}")
    print(f"  Open Gaps       : {result.get('open_gaps_detected')}")
    print(f"  Graph Gaps      : {[(g['measure_id'], g['gap_status']) for g in result.get('existing_graph_gaps', [])]}")

    print("\n--- AGENT RESPONSES ---")
    for agent, response in result.get('agent_responses', {}).items():
        print(f"\n[{agent.upper()}]")
        print(response)

if __name__ == "__main__":
    system = CareGapAgentSystem()

    # M0011 — 42F with open BCS gap (mammogram claim C000073 is from 2023, outside 24-month window)
    run_test("M0011", system)

    # M0002 — has E11.9 (diabetes) ICD in claims → CDC-HbA1c applies
    run_test("M0002", system)

    # M0009 — has CPT 45380 claim on 2026-01-18 → COL should be COMPLIANT despite graph gap
    run_test("M0009", system)
