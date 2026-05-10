"""One-off inspection: report what will be deleted for M0011..M0015."""
from src.neo4j_connection import get_knowledge_graph

MEMBER_IDS = ["M0017", "M0018", "M0019", "M0020"]

kg = get_knowledge_graph()

print("=" * 70)
print("Inspection report for members:", ", ".join(MEMBER_IDS))
print("=" * 70)

for mid in MEMBER_IDS:
    rows = kg.run_query("""
        MATCH (m:Member {member_id: $mid})
        OPTIONAL MATCH (m)-[:HAS_CARE_GAP]->(g:CareGap)
        OPTIONAL MATCH (m)-[:HAS_CLAIM]->(c:Claim)
        OPTIONAL MATCH (m)-[:HAS_EMAIL]->(e:Email)
        OPTIONAL MATCH (m)-[:HAS_APPOINTMENT]->(a:Appointment)
        OPTIONAL MATCH (m)-[:HAS_LIFESTYLE]->(l:Lifestyle)
        OPTIONAL MATCH (m)-[:HAS_RELATIVE]->(fm:FamilyMember)
        OPTIONAL MATCH (m)-[:HAS_MEDICAL_HISTORY]->(mh:MedicalHistoryEntry)
        OPTIONAL MATCH (o:Outreach)-[:CONTACTS]->(m)
        RETURN m.member_id  AS member_id,
               m.name       AS name,
               count(DISTINCT g)  AS care_gaps,
               count(DISTINCT c)  AS claims,
               count(DISTINCT e)  AS emails,
               count(DISTINCT a)  AS appointments,
               count(DISTINCT l)  AS lifestyle,
               count(DISTINCT fm) AS family_members,
               count(DISTINCT mh) AS medical_history,
               count(DISTINCT o)  AS outreach
    """, {"mid": mid})
    if not rows or not rows[0].get("member_id"):
        print(f"  {mid}: NOT FOUND in DB")
        continue
    r = rows[0]
    print(f"  {r['member_id']} ({r['name']}): "
          f"gaps={r['care_gaps']}, claims={r['claims']}, emails={r['emails']}, "
          f"appts={r['appointments']}, lifestyle={r['lifestyle']}, "
          f"family={r['family_members']}, medhist={r['medical_history']}, "
          f"outreach={r['outreach']}")

print("=" * 70)
