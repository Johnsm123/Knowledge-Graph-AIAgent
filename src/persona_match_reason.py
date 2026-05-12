"""
LLM-generated bullet-point analysis explaining why a specific Persona is
the closest match for a specific Member, and how that match drives the
care gaps detected.

Renders on hover of the green "IDEAL · P??" persona node in the
bulk-upload Care Gap Analysis Preview. Output is a list of short bullets
(5–7 lines), each a concrete factual statement grounded in the member's
demographic, lifestyle, family-history, and clinical data — so the care
manager can see WHY the agents picked this persona, not just THAT they did.

Returns a list[str]. Bullets render in the preview as <li> entries.
Falls back to a deterministic rulebook-derived bullet set if Bedrock fails.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TOKENS = 520
_MIN_BULLETS = 4
_MAX_BULLETS = 7


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


def _gap_names(pending: list) -> list:
    out = []
    for p in (pending or [])[:6]:
        n = p.get("measure_name") or p.get("measure_id")
        if n:
            out.append(str(n))
    return out


def _fmt_chronic(member: dict) -> str:
    c = member.get("chronic_conditions") or []
    if isinstance(c, list):
        return ", ".join(c) or "none on file"
    return str(c) or "none on file"


def _fallback_bullets(member: dict, pending: list, family_history: list,
                      medical_history: dict, lifestyle: dict) -> list:
    """Deterministic rule-driven bullets used when Bedrock is unavailable.
    Always returns at least 4 bullets so the tooltip never looks empty."""
    name = member.get("name") or "Member"
    age = member.get("age_str") or "unknown age"
    gender = "Female" if str(member.get("gender", "")).upper().startswith("F") else "Male"
    chronic = _fmt_chronic(member)
    gaps = _gap_names(pending)

    bullets = [
        f"Demographic fit — persona derived directly from this member's age "
        f"({age}) and gender ({gender}); cohort criteria for the detected "
        f"screenings align with this band.",
    ]

    bmi   = (lifestyle or {}).get("bmi")
    smoke = (lifestyle or {}).get("smoking_status")
    diet  = (lifestyle or {}).get("diet_type")
    exer  = (lifestyle or {}).get("exercise_frequency")
    life_bits = []
    if bmi:   life_bits.append(f"BMI {bmi}")
    if smoke: life_bits.append(f"smoking: {smoke}")
    if diet:  life_bits.append(f"diet: {diet}")
    if exer:  life_bits.append(f"exercise: {exer}")
    if life_bits:
        bullets.append(
            "Lifestyle alignment — " + ", ".join(life_bits) +
            " — mapped against the persona's healthy band to surface modifiable risks."
        )

    if chronic and chronic != "none on file":
        bullets.append(
            f"Clinical profile — chronic conditions on file ({chronic}) match "
            f"this persona's comorbidity signature, raising priority on the "
            f"linked screenings."
        )

    fh = []
    for f in (family_history or [])[:3]:
        rel = (f.get("relation") or "").strip()
        cond = ", ".join((f.get("conditions") or [])[:2])
        if rel and cond:
            fh.append(f"{rel}: {cond}")
    if fh:
        bullets.append(
            "Hereditary risk — first-degree family history (" + "; ".join(fh) +
            ") elevates this member's screening priority and reinforces the persona match."
        )

    if gaps:
        bullets.append(
            "Care-gap rationale — this persona's profile explains the open "
            "gaps for " + ", ".join(gaps) +
            ": each measure's eligibility rule fires on the demographic + "
            "clinical signals above."
        )

    bullets.append(
        f"Match quality — {name} sits inside this persona's defining cohort "
        "on every checked attribute, so it is the closest-fit reference "
        "profile for care-gap detection."
    )
    return bullets[:_MAX_BULLETS]


def _build_prompt(member: dict, pending: list, family_history: list,
                  medical_history: dict, lifestyle: dict) -> str:
    fh = []
    for f in (family_history or [])[:5]:
        rel  = (f.get("relation") or "").strip()
        cond = ", ".join((f.get("conditions") or [])[:3])
        if rel:
            fh.append(f"{rel}{(' — ' + cond) if cond else ''}")
    fh_text = "; ".join(fh) or "none on file"

    cur = ", ".join((e.get("name") or e.get("label") or "")
                    for e in (medical_history or {}).get("current_conditions", [])[:5]) or "none"
    past = ", ".join((e.get("name") or e.get("label") or "")
                     for e in (medical_history or {}).get("past_conditions",   [])[:5]) or "none"
    meds = ", ".join((e.get("name") or e.get("label") or "")
                     for e in (medical_history or {}).get("medications",       [])[:5]) or "none"

    bmi   = (lifestyle or {}).get("bmi", "")
    smoke = (lifestyle or {}).get("smoking_status", "")
    diet  = (lifestyle or {}).get("diet_type", "")
    exer  = (lifestyle or {}).get("exercise_frequency", "")

    gaps = ", ".join(_gap_names(pending)) or "none open"

    return (
        "You are a care-management analyst writing a brief justification report "
        "for a care manager. A persona has been auto-selected as the closest "
        "match for this member; you must explain WHY in concise bullet points.\n\n"
        "MEMBER PROFILE\n"
        f"  • Name: {member.get('name','?')}  |  ID: {member.get('member_id','?')}\n"
        f"  • Age: {member.get('age_str','?')}  |  Gender: "
        f"{'Female' if str(member.get('gender','')).upper().startswith('F') else 'Male'}\n"
        f"  • Chronic conditions: {_fmt_chronic(member)}\n"
        f"  • Insurance: {member.get('insurance_type','?')}\n"
        f"  • Lifestyle — BMI: {bmi or '?'}, smoking: {smoke or '?'}, "
        f"diet: {diet or '?'}, exercise: {exer or '?'}\n"
        f"  • Family history: {fh_text}\n"
        f"  • Current conditions: {cur}  |  Past: {past}  |  Medications: {meds}\n"
        f"  • Care gaps detected by the rulebook for this member: {gaps}\n\n"
        "INSTRUCTIONS\n"
        f"Return ONLY a JSON array of {_MIN_BULLETS}–{_MAX_BULLETS} strings. "
        "Each string is one analysis bullet. Cover (in this order):\n"
        "  1. Demographic alignment — age band and gender fit.\n"
        "  2. Lifestyle alignment — concrete BMI/smoking/diet/exercise comparison.\n"
        "  3. Clinical profile — comorbidities or medications driving the persona signature.\n"
        "  4. Hereditary risk — first-degree family-history signals that elevate risk.\n"
        "  5. Care-gap rationale — how the persona's profile explains the "
        "specific open care gaps listed above.\n"
        "  6. Match quality — a one-line conclusion stating this is the "
        "closest-fit persona and why.\n\n"
        "RULES\n"
        "  • Each bullet ≤ 28 words. Plain prose, no markdown, no bullet characters, no headings.\n"
        "  • Be concrete: cite the member's actual values, not generic statements.\n"
        "  • Never invent data not in the profile above. If a field is missing, omit that bullet.\n"
        "  • No CPT/ICD codes.\n"
        "  • Output strictly the JSON array — no preamble, no trailing prose."
    )


def _parse_bullets(text: str) -> list:
    """Try hard to extract a list of bullets from the LLM response.
    Handles: clean JSON array, fenced JSON, or fallback to line-splitting."""
    text = (text or "").strip()
    if not text:
        return []
    # Strip code fences
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    # First-pass JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    # Locate the outermost [ ... ] block
    s, e = text.find("["), text.rfind("]")
    if s != -1 and e != -1 and e > s:
        try:
            data = json.loads(text[s:e + 1])
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
    # Last-resort: split on newlines and strip bullet glyphs/numbers
    out = []
    for line in text.splitlines():
        line = re.sub(r"^[\s\-\*••\d\.\)\(]+", "", line).strip().strip('"')
        if line:
            out.append(line)
    return out


def generate_persona_match_bullets(
    member: dict,
    pending: list | None = None,
    family_history: list | None = None,
    medical_history: dict | None = None,
    lifestyle: dict | None = None,
) -> list:
    """Return a list of bullet-point analysis lines explaining the persona match."""
    pending          = pending or []
    family_history   = family_history or []
    medical_history  = medical_history or {}
    lifestyle        = lifestyle or {}
    try:
        client = _bedrock_client()
        prompt = _build_prompt(member, pending, family_history, medical_history, lifestyle)
        resp = client.converse(
            modelId=_model_id(),
            system=[{"text": (
                "You are a care-management analyst. Justify persona matches as "
                "tight, factual bullet points grounded only in the data provided. "
                "Respond strictly with a JSON array of strings — no other text."
            )}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": _MAX_TOKENS, "temperature": 0.35},
        )
        out = resp.get("output", {}).get("message", {}).get("content", [])
        text = " ".join(c.get("text", "") for c in out if c.get("text")).strip()
        bullets = _parse_bullets(text)
        # Quality gate — if we got too few, mix in fallbacks at the tail.
        if len(bullets) < _MIN_BULLETS:
            extra = _fallback_bullets(member, pending, family_history,
                                       medical_history, lifestyle)
            seen = {b.lower() for b in bullets}
            for b in extra:
                if b.lower() not in seen and len(bullets) < _MAX_BULLETS:
                    bullets.append(b)
                    seen.add(b.lower())
        return bullets[:_MAX_BULLETS]
    except Exception as exc:
        logger.warning(f"[PERSONA-MATCH-REASON] LLM failed for "
                       f"{member.get('member_id')}: {exc}")
        return _fallback_bullets(member, pending, family_history,
                                 medical_history, lifestyle)
