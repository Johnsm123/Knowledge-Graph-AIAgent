"""
Care Gap data hygiene utilities.

Two operations:
  1. backfill_primary_codes()  — walks every CareGap node and ensures
     primary_cpt_code + primary_icd10 are SINGLE codes pulled from the
     golden reference (overwrites any comma-joined / empty value).
  2. delete_duplicate_member_gaps() — for each (member, measure) pair,
     keeps only one CareGap node (newest created_on) and deletes others.

Both are idempotent. Safe to run repeatedly.
"""
import logging
from datetime import datetime

from src.neo4j_connection import get_knowledge_graph

logger = logging.getLogger(__name__)


def _measure_codes(measure_id: str) -> tuple[str, str]:
    """Single primary CPT + primary ICD-10 from the golden reference."""
    try:
        from src.hedis_golden_reference import HEDIS_MEASURES
        m = HEDIS_MEASURES.get(measure_id, {})
        return (m.get("primary_cpt", "") or "").strip(), (m.get("primary_icd10", "") or "").strip()
    except Exception:
        return "", ""


def _strip_to_single(code: str) -> str:
    """If a comma/space-joined string sneaks in, take the first non-empty token."""
    if not code:
        return ""
    for tok in str(code).replace(";", ",").split(","):
        t = tok.strip()
        if t and t.lower() not in {"nan", "none"}:
            return t
    return ""


def backfill_primary_codes() -> dict:
    """For every CareGap, ensure primary_cpt_code + primary_icd10 are single canonical codes.

    Logic:
      - If gap currently has multiple comma-joined codes -> keep only the first one
      - If primary_cpt_code is missing -> pull from golden reference
      - If primary_icd10 is missing -> pull from golden reference (member-specific
        ICD overrides handled separately at booking/claim time)
    """
    kg = get_knowledge_graph()
    rows = kg.run_query(
        """
        MATCH (g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        RETURN g.care_gap_id      AS gap_id,
               q.measure_id       AS measure_id,
               g.primary_cpt_code AS cur_cpt,
               g.primary_icd10    AS cur_icd
        """
    ) or []
    fixed = 0
    skipped = 0
    for r in rows:
        gid = r.get("gap_id")
        measure_id = r.get("measure_id") or ""
        if not gid or not measure_id:
            skipped += 1
            continue

        cur_cpt = _strip_to_single(r.get("cur_cpt") or "")
        cur_icd = _strip_to_single(r.get("cur_icd") or "")
        gold_cpt, gold_icd = _measure_codes(measure_id)

        new_cpt = cur_cpt or gold_cpt
        new_icd = cur_icd or gold_icd

        if new_cpt == (r.get("cur_cpt") or "") and new_icd == (r.get("cur_icd") or ""):
            continue  # already clean
        kg.execute_write(
            """
            MATCH (g:CareGap {care_gap_id: $gid})
            SET g.primary_cpt_code = $cpt,
                g.primary_icd10    = $icd
            """,
            {"gid": gid, "cpt": new_cpt, "icd": new_icd},
        )
        fixed += 1

    logger.info(f"[CLEANUP] backfill_primary_codes: fixed={fixed} skipped={skipped} total={len(rows)}")
    return {"fixed": fixed, "skipped": skipped, "total": len(rows)}


def delete_duplicate_member_gaps() -> dict:
    """For each (member, measure) pair keep the newest CareGap, delete duplicates.

    A duplicate is defined as another CareGap node attached to the same Member
    via the same QualityMeasure relationship. We keep the one with the most
    recent created_on (or any one if all are null).
    """
    kg = get_knowledge_graph()

    # Find duplicates
    rows = kg.run_query(
        """
        MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        WITH m, q, collect(g) AS gaps
        WHERE size(gaps) > 1
        RETURN m.member_id AS member_id, q.measure_id AS measure_id,
               [g IN gaps | {gid: g.care_gap_id, created_on: g.created_on, is_open: g.is_open}] AS gap_list
        """
    ) or []

    deleted = 0
    for r in rows:
        gap_list = r.get("gap_list", [])
        # Sort by created_on DESC; keep first, delete rest. Prefer open gaps as keepers.
        gap_list.sort(key=lambda x: ((1 if x.get("is_open") else 0), x.get("created_on") or ""), reverse=True)
        keep = gap_list[0]["gid"]
        to_delete = [g["gid"] for g in gap_list[1:]]
        if not to_delete:
            continue
        kg.execute_write(
            """
            MATCH (g:CareGap)
            WHERE g.care_gap_id IN $ids
            DETACH DELETE g
            """,
            {"ids": to_delete},
        )
        deleted += len(to_delete)
        logger.info(f"[CLEANUP] {r.get('member_id')}/{r.get('measure_id')}: kept {keep}, deleted {to_delete}")

    return {"duplicate_pairs_found": len(rows), "gaps_deleted": deleted}


def cleanup_all() -> dict:
    """Run both passes and return aggregated stats."""
    dup_stats = delete_duplicate_member_gaps()
    fix_stats = backfill_primary_codes()
    return {"duplicates": dup_stats, "backfill": fix_stats, "ran_at": datetime.now().isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# Buggy-member audit + purge
# ─────────────────────────────────────────────────────────────────────────────
def _is_multi_or_empty(code: str) -> bool:
    """A code field is buggy if empty OR contains comma/semicolon (multi-coded)."""
    if code is None:
        return True
    s = str(code).strip()
    if not s or s.lower() in {"nan", "none"}:
        return True
    if "," in s or ";" in s:
        return True
    return False


def find_buggy_members() -> list:
    """Return member_ids whose CareGap nodes have multi-CPT/ICD or duplicate gaps.

    A member is BUGGY if ANY of:
      - any of their CareGap nodes has primary_cpt_code containing "," or ";" or empty
      - any of their CareGap nodes has primary_icd10 containing "," or ";" or empty
      - they have >1 CareGap for the same QualityMeasure (duplicate)
    """
    kg = get_knowledge_graph()

    # Pass 1 — comma/empty-coded gaps
    rows = kg.run_query(
        """
        MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)
        RETURN m.member_id        AS member_id,
               g.care_gap_id      AS gap_id,
               g.primary_cpt_code AS cpt,
               g.primary_icd10    AS icd
        """
    ) or []

    buggy = {}
    for r in rows:
        mid = r.get("member_id")
        if not mid:
            continue
        cpt = r.get("cpt")
        icd = r.get("icd")
        if _is_multi_or_empty(cpt) or _is_multi_or_empty(icd):
            buggy.setdefault(mid, {"reasons": set(), "gap_ids": []})
            buggy[mid]["gap_ids"].append(r.get("gap_id"))
            if _is_multi_or_empty(cpt):
                buggy[mid]["reasons"].add("multi_or_empty_cpt")
            if _is_multi_or_empty(icd):
                buggy[mid]["reasons"].add("multi_or_empty_icd")

    # Pass 2 — duplicate (member, measure) pairs
    dup_rows = kg.run_query(
        """
        MATCH (m:Member)-[:HAS_CARE_GAP]->(g:CareGap)-[:RELATES_TO]->(q:QualityMeasure)
        WITH m.member_id AS member_id, q.measure_id AS measure_id, count(g) AS gap_count
        WHERE gap_count > 1
        RETURN member_id, measure_id, gap_count
        """
    ) or []
    for r in dup_rows:
        mid = r.get("member_id")
        if not mid:
            continue
        buggy.setdefault(mid, {"reasons": set(), "gap_ids": []})
        buggy[mid]["reasons"].add(f"duplicate_gaps_{r.get('measure_id')}")

    return [
        {
            "member_id": mid,
            "reasons": sorted(list(meta["reasons"])),
            "buggy_gap_ids": meta["gap_ids"],
        }
        for mid, meta in sorted(buggy.items())
    ]


def _purge_member_main_db(member_id: str) -> dict:
    """Delete a member and ALL connected nodes (gaps, claims, appointments, etc.)
    from the main Neo4j DB. DETACH DELETE handles relationships safely.
    """
    kg = get_knowledge_graph()
    # Delete tightly-coupled child nodes first (those that only belong to this member)
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        DETACH DELETE g
        """,
        {"mid": member_id},
    )
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_CLAIM]->(c:Claim)
        DETACH DELETE c
        """,
        {"mid": member_id},
    )
    kg.execute_write(
        """
        MATCH (a:Appointment {member_id: $mid})
        DETACH DELETE a
        """,
        {"mid": member_id},
    )
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_LIFESTYLE]->(l)
        DETACH DELETE l
        """,
        {"mid": member_id},
    )
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_FAMILY_MEMBER]->(f)
        DETACH DELETE f
        """,
        {"mid": member_id},
    )
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_HISTORY_ITEM]->(h)
        DETACH DELETE h
        """,
        {"mid": member_id},
    )
    # Finally remove the Member node itself
    kg.execute_write(
        """
        MATCH (m:Member {member_id: $mid})
        DETACH DELETE m
        """,
        {"mid": member_id},
    )
    return {"member_id": member_id, "main_db": "purged"}


def _purge_member_reference_db(member_id: str) -> dict:
    """Delete a member's persona + lifecycle nodes from the reference DB."""
    try:
        from src.neo4j_connection import get_reference_graph
        ref = get_reference_graph()
    except Exception as exc:
        logger.warning(f"Reference DB not configured, skipping persona purge: {exc}")
        return {"member_id": member_id, "ref_db": "skipped"}

    ref.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_CARE_GAP]->(g:CareGap)
        OPTIONAL MATCH (g)-[:HAS_ACTION]->(a:Action)
        DETACH DELETE a, g
        """,
        {"mid": member_id},
    )
    ref.execute_write(
        """
        MATCH (m:Member {member_id: $mid})-[:HAS_PERSONA]->(p:Persona)
        DETACH DELETE p
        """,
        {"mid": member_id},
    )
    ref.execute_write(
        """
        MATCH (m:Member {member_id: $mid})
        DETACH DELETE m
        """,
        {"mid": member_id},
    )
    return {"member_id": member_id, "ref_db": "purged"}


def purge_buggy_members(dry_run: bool = True) -> dict:
    """Find and (optionally) delete every member whose care-gap data is buggy.

    dry_run=True   → returns the list of buggy members WITHOUT deleting.
    dry_run=False  → deletes from main DB AND reference DB, returns deletion log.
    """
    buggy = find_buggy_members()
    result = {
        "scanned_at": datetime.now().isoformat(),
        "buggy_count": len(buggy),
        "buggy_members": buggy,
        "dry_run": dry_run,
        "deleted": [],
    }
    if dry_run or not buggy:
        return result

    for entry in buggy:
        mid = entry["member_id"]
        try:
            main_res = _purge_member_main_db(mid)
            ref_res = _purge_member_reference_db(mid)
            result["deleted"].append(
                {**main_res, **ref_res, "reasons": entry["reasons"]}
            )
            logger.info(f"[PURGE] Removed buggy member {mid} "
                        f"(reasons: {entry['reasons']}) from both DBs")
        except Exception as exc:
            logger.error(f"[PURGE] Failed to remove {mid}: {exc}", exc_info=True)
            result["deleted"].append({"member_id": mid, "error": str(exc)})

    return result
