// ════════════════════════════════════════════════════════════════════════════
//  Persona-Comparison Demo — Cypher Query Cookbook
//  Run any of these in Neo4j Browser pointed at the *demo* Aura instance.
//  None of them touch the main DB or the live persona/reference DB.
// ════════════════════════════════════════════════════════════════════════════


// ── 1. THE HEADLINE QUERY ──────────────────────────────────────────────────
//   Show one member side-by-side with their ideal persona.
//   Pending care gaps appear as Screening nodes connected ONLY to the persona.
//   Compliant screenings appear as Screening nodes connected to BOTH.

MATCH (m:Member {member_id: 'M0012'})-[:COMPARED_TO]->(ip:IdealPersona)
OPTIONAL MATCH (ip)-[r1:WOULD_HAVE_COMPLETED]->(s:Screening)
OPTIONAL MATCH (m)-[r2:HAS_COMPLETED]->(s)
OPTIONAL MATCH (m)-[r3:HAS_PENDING]->(s2:Screening)
OPTIONAL MATCH (m)-[r4:EXCLUDED_FROM]->(s3:Screening)
RETURN m, ip, r1, r2, r3, r4, s, s2, s3;


// ── 2. PURE "WHAT IS PENDING?" — derived by SUBTRACTION ────────────────────
//   Persona has it, member doesn't.  This *is* the persona-comparison method.

MATCH (m:Member {member_id: 'M0012'})-[:COMPARED_TO]->(ip:IdealPersona)
MATCH (ip)-[:WOULD_HAVE_COMPLETED]->(s:Screening)
WHERE NOT (m)-[:HAS_COMPLETED]->(s)
  AND NOT (m)-[:EXCLUDED_FROM]->(s)
RETURN m.member_id  AS member,
       ip.persona_id AS ideal_twin,
       collect({
         measure: s.measure_id,
         name:    s.name,
         primary_cpt: s.primary_cpt,
         primary_icd: s.primary_icd10,
         lookback_months: s.lookback_months
       }) AS pending_screenings;


// ── 3. ONE MEMBER FULL VIEW — graph nicely laid out ────────────────────────
//   Drop a different member_id in to demo any patient.
//   Toggle node captions in Neo4j Browser to show measure_id / name.

MATCH (m:Member {member_id: 'M0012'})
OPTIONAL MATCH path1 = (m)-[:COMPARED_TO]->(:IdealPersona)-[:WOULD_HAVE_COMPLETED]->(:Screening)
OPTIONAL MATCH path2 = (m)-[:HAS_COMPLETED]->(:Screening)
OPTIONAL MATCH path3 = (m)-[:HAS_PENDING]->(:Screening)
OPTIONAL MATCH path4 = (m)-[:EXCLUDED_FROM]->(:Screening)
RETURN m, path1, path2, path3, path4;


// ── 4. TOP 10 MEASURES WITH MOST PENDING SCREENINGS ────────────────────────
//   Where is the population least compliant?

MATCH (m:Member)-[:HAS_PENDING]->(s:Screening)
RETURN s.measure_id AS measure,
       s.name       AS name,
       count(m)     AS pending_members
ORDER BY pending_members DESC
LIMIT 10;


// ── 5. COMPLIANCE DISTRIBUTION HISTOGRAM ───────────────────────────────────
//   How many members fall into each compliance bucket?

MATCH (m:Member)
WITH CASE
       WHEN m.compliance_score = 100 THEN '100% (Compliant)'
       WHEN m.compliance_score >= 75 THEN '75-99%'
       WHEN m.compliance_score >= 50 THEN '50-74%'
       WHEN m.compliance_score >= 25 THEN '25-49%'
       ELSE '< 25% (Critical)'
     END AS bucket
RETURN bucket, count(*) AS members
ORDER BY bucket DESC;


// ── 6. MEMBERS WITH ZERO COMPLETED SCREENINGS ──────────────────────────────
//   Highest-priority outreach candidates: persona has lots, member has none.

MATCH (m:Member)-[:COMPARED_TO]->(ip:IdealPersona)
WHERE m.completed_count = 0 AND m.pending_count > 0
RETURN m.member_id   AS member,
       m.name        AS name,
       m.age_str     AS age,
       ip.persona_id AS ideal_twin,
       m.pending_count AS pending,
       m.applicable_count AS applicable
ORDER BY pending DESC
LIMIT 25;


// ── 7. ONE MEMBER vs ONE SCREENING — full provenance ───────────────────────
//   Why does the engine think M0012 has BCS pending?

MATCH (m:Member {member_id: 'M0012'})-[r:HAS_PENDING]->(s:Screening {measure_id: 'BCS'})
RETURN m.member_id  AS member,
       m.gender     AS gender,
       m.age_str    AS age,
       s.measure_id AS measure,
       s.age_range  AS qualifies_age,
       s.gender_requirement AS qualifies_gender,
       s.lookback_months AS lookback_months,
       s.primary_cpt AS close_with_cpt,
       s.primary_icd10 AS encounter_icd,
       r.urgency    AS urgency,
       r.identified_on AS identified_on;


// ── 8. CARE-GAP NETWORK FOR A WHOLE COHORT ─────────────────────────────────
//   Cluster of members + their personas + the BCS screening — useful to
//   visualise how many members in the population share the same pending gap.

MATCH (s:Screening {measure_id: 'BCS'})
OPTIONAL MATCH (m:Member)-[:HAS_PENDING]->(s)
OPTIONAL MATCH (m)-[:COMPARED_TO]->(ip:IdealPersona)-[:WOULD_HAVE_COMPLETED]->(s)
RETURN s, m, ip
LIMIT 200;


// ── 9. AGGREGATE COUNTS — at-a-glance demo dashboard ───────────────────────

MATCH (m:Member)            WITH count(m) AS members
MATCH (p:IdealPersona)      WITH members, count(p) AS personas
MATCH (s:Screening)         WITH members, personas, count(s) AS screenings
MATCH ()-[r:HAS_PENDING]->()   WITH members, personas, screenings, count(r) AS pending_edges
MATCH ()-[c:HAS_COMPLETED]->() WITH members, personas, screenings, pending_edges, count(c) AS completed_edges
MATCH ()-[e:EXCLUDED_FROM]->() WITH members, personas, screenings, pending_edges, completed_edges, count(e) AS excluded_edges
RETURN {
  members:           members,
  ideal_personas:    personas,
  screenings:        screenings,
  pending_total:     pending_edges,
  completed_total:   completed_edges,
  excluded_total:    excluded_edges
} AS demo_overview;


// ── 9b. FULL PERSONA-VS-MEMBER MISSING-LINKS REPORT ────────────────────────
//   Side-by-side: ideal persona attributes vs the actual member, plus every
//   gap category (screenings, lifestyle, immunizations, unmanaged chronic,
//   family-risk follow-up). This is the "why this member differs from the
//   ideal" view to share with the manager.

MATCH (m:Member {member_id: 'M0012'})-[r:COMPARED_TO]->(p:IdealPersona)
RETURN
  m.member_id                AS member_id,
  p.persona_id               AS compared_to_persona,
  // Lifestyle side-by-side
  {
    bmi:       {member: m.bmi,                ideal: p.ideal_bmi_range},
    smoking:   {member: m.smoking_status,     ideal: p.ideal_smoking_status},
    alcohol:   {member: m.alcohol_use,        ideal: p.ideal_alcohol_use},
    exercise:  {member: m.exercise_frequency, ideal: p.ideal_exercise_frequency},
    diet:      {member: m.diet_type,          ideal: p.ideal_diet_type},
    sleep:     {member: m.sleep_hours_avg,    ideal: p.ideal_sleep_hours},
    stress:    {member: m.stress_level,       ideal: p.ideal_stress_level}
  } AS lifestyle_comparison,
  // Missing-links breakdown
  {
    pending_screenings:    r.gap_measures,
    lifestyle_gaps:        r.lifestyle_gaps,
    missing_immunizations: r.missing_immunizations,
    unmanaged_conditions:  r.unmanaged_conditions,
    family_risk_flags:     r.family_risk_flags,
    severe_allergies:      r.severe_allergies
  } AS missing_links,
  r.gap_categories      AS gap_categories,
  r.total_missing_links AS total_missing_links;


// ── 9c. FIRST-5 MEMBERS — at-a-glance comparison roster ────────────────────
//   Quick demo view: pick the first 5 member IDs and show their persona twin
//   plus the count of missing links in every category.

MATCH (m:Member)-[r:COMPARED_TO]->(p:IdealPersona)
RETURN m.member_id        AS member_id,
       m.name              AS member_name,
       p.persona_id        AS persona,
       r.gap_count         AS pending_screenings,
       size(r.lifestyle_gaps)        AS lifestyle_gaps,
       size(r.missing_immunizations) AS missing_immunizations,
       size(r.unmanaged_conditions)  AS unmanaged_conditions,
       size(r.family_risk_flags)     AS family_risk_flags,
       r.total_missing_links         AS total_missing_links,
       r.gap_categories              AS gap_categories
ORDER BY m.member_id
LIMIT 5;


// ── 10. RESET (DESTRUCTIVE — only run on the demo DB) ──────────────────────
//   If you ever want to wipe the demo data and re-run the Python seeder.

// MATCH (n) DETACH DELETE n;
