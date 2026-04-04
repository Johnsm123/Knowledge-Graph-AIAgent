"""
db_builder.py — Approach 2: Build HEDIS Rules per Disease/Measure in Neo4j

This script wipes the Neo4j database and rebuilds it from scratch:

  Layer 1 — HEDIS Golden Reference (rules as graph nodes):
    QualityMeasure     — one node per HEDIS measure (7 measures)
    CodeSet            — CPT/HCPCS/LOINC/ICD10 code groups per measure AND per screening option
    ScreeningOption    — per-option rules for multi-path measures (COL: 5 options, CCS: 3 options)
    ExclusionCriteria  — exclusion rules (mastectomy → BCS excluded, colectomy → COL excluded, etc.)
    ClinicalGuideline  — acceptable / not-acceptable documentation criteria
    BestPractices      — provider best-practice tips

  Layer 2 — Member + Transactional data (from Excel):
    Member, Provider, BenefitPlan, Claim, CareGap, Outreach

  For each new patient → run through the rulebook:
    Mary (F, 55)  → BCS applies → no mammogram in 24 months → CareGap created
    John          → BCS applies → mastectomy code Z90.13 found → EXCLUDED, no gap

Run from Knowledge-Graph-AIAgent/ directory:
    python -m src.db_builder
"""
import logging
from src.neo4j_connection import get_knowledge_graph
from src.wipe_and_reload import wipe_all, verify_empty
from src.care_gap_data_loader import load_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Main build pipeline
# ─────────────────────────────────────────────────────────────────────────────

def build():
    logger.info("=" * 65)
    logger.info("  HEDIS Knowledge Graph Builder — Approach 2 (Rules as Graph)")
    logger.info("=" * 65)

    # Step 1 — wipe
    logger.info("")
    logger.info("Step 1/3 — Wiping existing Neo4j database ...")
    wipe_all()
    if not verify_empty():
        logger.error("Database wipe incomplete. Aborting.")
        return False

    # Step 2 — build
    logger.info("")
    logger.info("Step 2/3 — Loading HEDIS golden reference + member data ...")
    load_all()

    # Step 3 — verify
    logger.info("")
    logger.info("Step 3/3 — Verifying graph ...")
    _verify()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Verification report
# ─────────────────────────────────────────────────────────────────────────────

def _verify():
    kg = get_knowledge_graph()

    # Node counts
    node_checks = [
        ("QualityMeasure (HEDIS rules)",   "MATCH (q:QualityMeasure)     RETURN count(q) AS n"),
        ("CodeSet (CPT/HCPCS/LOINC sets)", "MATCH (cs:CodeSet)           RETURN count(cs) AS n"),
        ("ScreeningOption (per-path rules)","MATCH (so:ScreeningOption)   RETURN count(so) AS n"),
        ("ExclusionCriteria",               "MATCH (e:ExclusionCriteria)  RETURN count(e) AS n"),
        ("ClinicalGuideline",               "MATCH (cg:ClinicalGuideline) RETURN count(cg) AS n"),
        ("BestPractices",                   "MATCH (bp:BestPractices)     RETURN count(bp) AS n"),
        ("Member (patients)",               "MATCH (m:Member)             RETURN count(m) AS n"),
        ("Provider",                        "MATCH (p:Provider)           RETURN count(p) AS n"),
        ("BenefitPlan",                     "MATCH (b:BenefitPlan)        RETURN count(b) AS n"),
        ("Claim",                           "MATCH (c:Claim)              RETURN count(c) AS n"),
        ("CareGap",                         "MATCH (g:CareGap)            RETURN count(g) AS n"),
        ("Outreach",                        "MATCH (o:Outreach)           RETURN count(o) AS n"),
    ]

    logger.info("")
    logger.info("  Node counts:")
    for label, q in node_checks:
        r = kg.run_query(q, {})
        n = r[0]["n"] if r else 0
        icon = "OK" if n > 0 else "!!"
        logger.info(f"    [{icon}]  {label:<38}  {n:>4}")

    # Per-measure breakdown
    measures = kg.run_query("""
        MATCH (q:QualityMeasure)
        OPTIONAL MATCH (q)-[:REQUIRES_CODES]->(cs:CodeSet)
        OPTIONAL MATCH (q)-[:HAS_EXCLUSION]->(e:ExclusionCriteria)
        OPTIONAL MATCH (q)-[:HAS_SCREENING_OPTION]->(so:ScreeningOption)
        RETURN q.measure_id        AS id,
               q.name              AS name,
               q.age_range         AS age_range,
               q.lookback_months   AS lb,
               q.gender_requirement AS gender,
               count(DISTINCT cs)  AS code_sets,
               count(DISTINCT e)   AS exclusions,
               count(DISTINCT so)  AS options
        ORDER BY q.measure_id
    """, {})

    logger.info("")
    logger.info("  HEDIS Rulebook (Approach 2 — rules stored as graph):")
    logger.info(
        f"  {'ID':<12} {'Name':<46} {'Age':<14} {'Gender':<8}"
        f" {'LB(mo)':<7} {'Codes':<6} {'Excl':<5} {'Opts'}"
    )
    logger.info("  " + "-" * 105)
    for m in measures:
        logger.info(
            f"  {m['id']:<12} {m['name'][:45]:<46} {m['age_range']:<14}"
            f" {m['gender']:<8} {str(m['lb']):<7} {m['code_sets']:<6}"
            f" {m['exclusions']:<5} {m['options']}"
        )

    # Screening options breakdown
    options = kg.run_query("""
        MATCH (q:QualityMeasure)-[:HAS_SCREENING_OPTION]->(so:ScreeningOption)
        OPTIONAL MATCH (so)-[:USES_CODES]->(cs:CodeSet)
        RETURN q.measure_id AS measure_id,
               so.type AS option_type,
               so.lookback_months AS lookback_months,
               count(DISTINCT cs) AS code_sets
        ORDER BY q.measure_id, so.lookback_months DESC
    """, {})

    if options:
        logger.info("")
        logger.info("  Multi-path screening options (OR logic — any one satisfies the gap):")
        for o in options:
            logger.info(
                f"    {o['measure_id']:<8} -> {o['option_type']:<30}"
                f" lookback={o['lookback_months']} months  code_sets={o['code_sets']}"
            )

    # Exclusion sample
    excl = kg.run_query("""
        MATCH (q:QualityMeasure)-[:HAS_EXCLUSION]->(e:ExclusionCriteria)
        RETURN q.measure_id AS measure_id, e.type AS excl_type
        ORDER BY q.measure_id, e.type
        LIMIT 20
    """, {})

    if excl:
        logger.info("")
        logger.info("  Sample exclusions loaded (run patient → rulebook → skip if matched):")
        for e in excl:
            logger.info(f"    {e['measure_id']:<12}  EXCLUDED_IF  {e['excl_type']}")

    logger.info("")
    logger.info("=" * 65)
    logger.info("  Build complete. Neo4j is ready for patient gap detection.")
    logger.info("  Start servers:  start_servers.bat")
    logger.info("=" * 65)


if __name__ == "__main__":
    build()
