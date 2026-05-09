"""
LLM-generated clinical reasons for individual care gaps.

Used by the bulk-upload preview UI to populate a hover tooltip on each
care-gap node explaining *why* the HEDIS rulebook flagged this gap for
this specific member, in plain clinical language.

One Bedrock Converse call per (member, measure) pair, run in parallel
across measures via a thread pool. Failures fall back to a deterministic
rulebook-derived sentence so the tooltip is never empty.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

# Cap reason length — tooltips should be skimmable, not paragraphs.
_MAX_TOKENS = 220
_TIMEOUT_S  = 25


def _bedrock_client():
    import boto3
    from config.settings import settings as cfg
    return boto3.client(
        "bedrock-runtime",
        region_name=cfg.aws_region,
        aws_access_key_id=cfg.aws_access_key_id,
        aws_secret_access_key=cfg.aws_secret_access_key,
    )


def _model_id() -> str:
    from config.settings import settings as cfg
    return cfg.bedrock_model_id


def _fallback_reason(member: dict, measure_def: dict) -> str:
    """Deterministic rulebook-derived reason — used when Bedrock is
    unavailable or the call errors. Keeps the tooltip useful even
    offline."""
    name   = member.get("name", "Member")
    age    = member.get("age_str", "")
    gender = "female" if str(member.get("gender", "")).upper().startswith("F") else "male"
    mname  = measure_def.get("name", measure_def.get("measure_id", "this measure"))
    lookback = measure_def.get("lookback_months") or 12
    return (
        f"{name} ({age}, {gender}) is in the eligible population for {mname} "
        f"per HEDIS criteria, but no qualifying claim was found within the last "
        f"{lookback} months. {measure_def.get('description', '')[:160]}"
    ).strip()


def _build_prompt(member: dict, measure_def: dict,
                  family_history: list, medical_history: dict,
                  lifestyle: dict) -> str:
    """Build the user-facing prompt for one (member, measure) pair."""
    fh = []
    for f in (family_history or [])[:5]:
        rel  = (f.get("relation") or "").strip()
        cond = ", ".join((f.get("conditions") or [])[:2])
        if rel:
            fh.append(f"{rel}{(' — ' + cond) if cond else ''}")
    fh_text = "; ".join(fh) or "none on file"

    cur = ", ".join((e.get("name") or e.get("label") or "") for e in (medical_history or {}).get("current_conditions", [])[:4]) or "none"
    past = ", ".join((e.get("name") or e.get("label") or "") for e in (medical_history or {}).get("past_conditions",   [])[:4]) or "none"
    meds = ", ".join((e.get("name") or e.get("label") or "") for e in (medical_history or {}).get("medications",       [])[:4]) or "none"

    bmi   = (lifestyle or {}).get("bmi", "")
    smoke = (lifestyle or {}).get("smoking_status", "")
    diet  = (lifestyle or {}).get("diet_type", "")

    return (
        f"Measure: {measure_def.get('measure_id')} — {measure_def.get('name')}\n"
        f"HEDIS criteria: ages {measure_def.get('age_range','')}, "
        f"{measure_def.get('gender_requirement','Any')} gender, "
        f"lookback {measure_def.get('lookback_months','')} months. "
        f"Numerator: {measure_def.get('numerator_criteria','')}. "
        f"Diagnosis required: {measure_def.get('diagnosis_requirement','none')}.\n\n"
        f"Member: {member.get('name','?')} | "
        f"{member.get('age_str','?')} | "
        f"{'Female' if str(member.get('gender','')).upper().startswith('F') else 'Male'} | "
        f"chronic: {member.get('chronic_conditions') or 'none'} | "
        f"insurance: {member.get('insurance_type','?')}\n"
        f"Lifestyle: BMI {bmi or '?'}, smoking {smoke or '?'}, diet {diet or '?'}.\n"
        f"Family history: {fh_text}.\n"
        f"Current conditions: {cur}. Past: {past}. Medications: {meds}.\n\n"
        "Write 2–3 short sentences for a care manager hover tooltip explaining "
        "WHY this specific member has this care gap. Be concrete: cite the "
        "member's age/gender vs the rulebook's eligibility, the missing claim, "
        "any family-history or comorbidity that elevates risk. No CPT/ICD codes, "
        "no markdown, no headings. Plain prose, max ~60 words."
    )


def generate_reason(member: dict, measure_def: dict,
                    family_history: list | None = None,
                    medical_history: dict | None = None,
                    lifestyle: dict | None = None) -> str:
    """One care-gap reason. Returns the fallback reason if the LLM call fails."""
    if not measure_def:
        return ""
    try:
        client = _bedrock_client()
        prompt = _build_prompt(
            member, measure_def,
            family_history or [], medical_history or {}, lifestyle or {},
        )
        resp = client.converse(
            modelId=_model_id(),
            system=[{"text": (
                "You are a HEDIS care-gap analyst. Write tight, factual "
                "clinical-style explanations for care managers. Never invent "
                "data not provided. No bullet points or headings."
            )}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": _MAX_TOKENS, "temperature": 0.4},
        )
        out = resp.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(c.get("text", "") for c in out if c.get("text")).strip()
        if text:
            return text
    except Exception as exc:
        logger.warning(f"[CARE-GAP-REASON] LLM failed for {member.get('member_id')}/"
                       f"{measure_def.get('measure_id')}: {exc}")
    return _fallback_reason(member, measure_def)


def generate_reasons_for_member(
    member: dict,
    pending_measure_ids: list,
    family_history: list | None = None,
    medical_history: dict | None = None,
    lifestyle: dict | None = None,
    max_workers: int = 4,
) -> dict:
    """Generate reasons for multiple measures in parallel. Returns a dict
    {measure_id: reason_text}."""
    from src.hedis_golden_reference import HEDIS_MEASURES

    if not pending_measure_ids:
        return {}

    out: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for mid in pending_measure_ids:
            mdef = HEDIS_MEASURES.get(mid)
            if not mdef:
                continue
            futures[ex.submit(
                generate_reason, member, mdef,
                family_history, medical_history, lifestyle,
            )] = mid
        for fut in as_completed(futures, timeout=_TIMEOUT_S * len(futures)):
            mid = futures[fut]
            try:
                out[mid] = fut.result(timeout=_TIMEOUT_S)
            except Exception as exc:
                logger.warning(f"[CARE-GAP-REASON] timeout/error for {mid}: {exc}")
                mdef = HEDIS_MEASURES.get(mid) or {}
                out[mid] = _fallback_reason(member, mdef)
    return out
