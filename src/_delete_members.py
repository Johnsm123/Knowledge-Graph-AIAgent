"""One-off deletion: remove M0011..M0015 and all their owned dependent nodes.

Owned (deleted): CareGap, Claim, Email, Appointment, Lifestyle, FamilyMember,
MedicalHistoryEntry, Outreach.
Shared (preserved): Provider, BenefitPlan, QualityMeasure, Condition.
"""
from src.neo4j_connection import get_knowledge_graph

MEMBER_IDS = ["M0017", "M0018", "M0019", "M0020"]

kg = get_knowledge_graph()

for mid in MEMBER_IDS:
    print(f"\n--- Deleting {mid} ---")

    # 1. Delete owned dependent nodes via DETACH DELETE (each its own statement
    #    so a missing label/relation doesn't abort the rest).
    cleanup_statements = [
        ("care gaps",        "MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap) DETACH DELETE g"),
        ("claims",           "MATCH (m:Member {member_id: $mid})-[:HAS_CLAIM]->(c:Claim) DETACH DELETE c"),
        ("emails",           "MATCH (m:Member {member_id: $mid})-[:HAS_EMAIL]->(e:Email) DETACH DELETE e"),
        ("appointments",     "MATCH (m:Member {member_id: $mid})-[:HAS_APPOINTMENT]->(a:Appointment) DETACH DELETE a"),
        ("lifestyle",        "MATCH (m:Member {member_id: $mid})-[:HAS_LIFESTYLE]->(l:Lifestyle) DETACH DELETE l"),
        ("family members",   "MATCH (m:Member {member_id: $mid})-[:HAS_RELATIVE]->(fm:FamilyMember) DETACH DELETE fm"),
        ("medical history",  "MATCH (m:Member {member_id: $mid})-[:HAS_MEDICAL_HISTORY]->(mh:MedicalHistoryEntry) DETACH DELETE mh"),
        ("outreach",         "MATCH (o:Outreach)-[:CONTACTS]->(m:Member {member_id: $mid}) DETACH DELETE o"),
    ]
    for label, stmt in cleanup_statements:
        ok = kg.execute_write(stmt, {"mid": mid})
        print(f"  {label:18s} -> {'ok' if ok else 'FAILED'}")

    # 2. Finally delete the Member itself (DETACH to drop any remaining shared rels).
    ok = kg.execute_write(
        "MATCH (m:Member {member_id: $mid}) DETACH DELETE m",
        {"mid": mid}
    )
    print(f"  member node        -> {'ok' if ok else 'FAILED'}")

# Verify all gone
print("\n=== Verification ===")
rows = kg.run_query("""
    MATCH (m:Member) WHERE m.member_id IN $ids
    RETURN m.member_id AS member_id
""", {"ids": MEMBER_IDS})
if rows:
    print("STILL PRESENT:", [r["member_id"] for r in rows])
else:
    print(f"All {len(MEMBER_IDS)} members deleted successfully.")
