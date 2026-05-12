"""
LLM-generated explanation of *why* a Persona node matches a specific Member.

Mirrors src/care_gap_reason.py — same Bedrock Converse + fallback pattern.
The output populates a hover tooltip on the Persona node in the lifecycle
graph, so a care manager can see at a glance:
  • why this persona is a faithful representation of the member, and
  • how the persona profile drives the care gaps detected for the member.

One call per member (the persona is 1:1 with the member). Falls back to a
deterministic rulebook-derived sentence so the tooltip is never empty.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TOKENS = 240
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


def _gap_summary(open_gaps: list) -> str:
    """Compact comma-separated list of measure names with this member's open gaps."""
    names = []
    for og in (open_gaps or [])[:6]:
        n = og.get("measure_name") or og.get("measure_id")
        if n:
            names.append(str(n))
    return ", ".join(names) if names else "none"


def _fallback_reason(member: dict, open_gaps: list) -> str:
    """Deterministic explanation used when Bedrock is unavailable."""
    name   = member.get("name", "Member")
    age    = member.get("age_str", "")
    gender = "female" if str(member.get("gender", "")).upper().startswith("F") else "male"
    chronic = member.get("chronic_conditions") or []
    if isinstance(chronic, list):
        chronic = ", ".join(chronic)
    chronic_clause = f", with {chronic}" if chronic else ""
    gaps = _gap_summary(open_gaps)
    return (
        f"This persona mirrors {name} — a {age} {gender}{chronic_clause}. "
        f"It is a faithful match because the persona's demographics and clinical "
        f"profile are derived directly from this member's record. The persona "
        f"drives screening eligibility for: {gaps}."
    ).strip()


def _build_prompt(member: dict, open_gaps: list,
                  family_history: list, medical_history: dict,
                  lifestyle: dict) -> str:
    fh = []
    for f in (family_history or [])[:5]:
        rel  = (f.get("relation") or "").strip()
        cond = ", ".join((f.get("conditions") or [])[:2])
        if rel:
            fh.append(f"{rel}{(' — ' + cond) if cond else ''}")
    fh_text = "; ".join(fh) or "none on file"

    cur = ", ".join((e.get("name") or e.get("label") or "")
                    for e in (medical_history or {}).get("current_conditions", [])[:4]) or "none"
    past = ", ".join((e.get("name") or e.get("label") or "")
                     for e in (medical_history or {}).get("past_conditions",   [])[:4]) or "none"
    meds = ", ".join((e.get("name") or e.get("label") or "")
                     for e in (medical_history or {}).get("medications",       [])[:4]) or "none"

    bmi   = (lifestyle or {}).get("bmi", "")
    smoke = (lifestyle or {}).get("smoking_status", "")
    diet  = (lifestyle or {}).get("diet_type", "")

    chronic = member.get("chronic_conditions") or []
    if isinstance(chronic, list):
        chronic = ", ".join(chronic) or "none"

    gaps = _gap_summary(open_gaps)

    return (
        "Persona overview:\n"
        f"  • Member: {member.get('name','?')} | {member.get('age_str','?')} | "
        f"{'Female' if str(member.get('gender','')).upper().startswith('F') else 'Male'} | "
        f"chronic: {chronic} | insurance: {member.get('insurance_type','?')}\n"
        f"  • Lifestyle: BMI {bmi or '?'}, smoking {smoke or '?'}, diet {diet or '?'}.\n"
        f"  • Family history: {fh_text}.\n"
        f"  • Current conditions: {cur}. Past: {past}. Medications: {meds}.\n"
        f"  • Open care gaps detected for this member: {gaps}.\n\n"
        "Write 2–3 short sentences for a care-manager hover tooltip explaining "
        "WHY this persona is a faithful match for this specific member, AND "
        "how the persona's demographic/clinical profile drives the care gaps "
        "listed above. Be concrete: cite age band, gender, comorbidities, and "
        "family-history signals that elevate risk. No markdown, no headings, "
        "no bullet points, no CPT/ICD codes — plain prose, max ~65 words."
    )


def generate_persona_reason(
    member: dict,
    open_gaps: list | None = None,
    family_history: list | None = None,
    medical_history: dict | None = None,
    lifestyle: dict | None = None,
) -> str:
    """Return one paragraph explaining why this persona matches the member."""
    open_gaps = open_gaps or []
    try:
        client = _bedrock_client()
        prompt = _build_prompt(
            member, open_gaps,
            family_history or [], medical_history or {}, lifestyle or {},
        )
        resp = client.converse(
            modelId=_model_id(),
            system=[{"text": (
                "You are a care-management analyst. Explain in plain prose why "
                "a synthesized persona is a faithful representation of a specific "
                "member, and how that persona profile drives the member's care gaps. "
                "Never invent data not provided. No bullet points or headings."
            )}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": _MAX_TOKENS, "temperature": 0.4},
        )
        out = resp.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(c.get("text", "") for c in out if c.get("text")).strip()
        if text:
            return text
    except Exception as exc:
        logger.warning(f"[PERSONA-REASON] LLM failed for {member.get('member_id')}: {exc}")
    return _fallback_reason(member, open_gaps)
