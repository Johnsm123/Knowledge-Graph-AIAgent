"""
validate_personas.py
Validates generated personas against measure config rules.

Usage:
  python validate_personas.py measures/bcs_e_config.json measures/bcs_e_personas.json
"""

import sys, json
from collections import Counter

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def validate(config, personas):
    errors   = []
    warnings = []

    gc_codes   = [g["code"] for g in config.get("gender_criteria", [])]
    ab_codes   = [b["code"] for b in config.get("age_bands", [])]
    excl_names = list(config.get("exclusion_codes", {}).keys())
    ab2_only   = set(config.get("ab2_only_exclusions", []))
    valid_statuses = set(config.get("gap_statuses", []))

    # ── Rule 1: No duplicate persona_ids ─────────────────────────────────────
    ids = [p["persona_id"] for p in personas]
    dupes = [pid for pid, cnt in Counter(ids).items() if cnt > 1]
    if dupes:
        errors.append(f"Duplicate persona_ids: {dupes}")

    # ── Rule 2: Expected counts ───────────────────────────────────────────────
    excl_ab1     = [e for e in excl_names if e not in ab2_only]
    excl_ab2     = excl_names
    expected = {
        "NOT_ELIGIBLE": len(gc_codes) * len(ab_codes),
        "COMPLIANT":    len(gc_codes) * len(ab_codes),
        "OPEN_GAP":     len(gc_codes) * len(ab_codes),
        "EXCLUDED":     len(gc_codes) * len(excl_ab1) + len(gc_codes) * len(excl_ab2),
    }
    expected_total = sum(expected.values())
    actual = Counter(p.get("care_gap_status") for p in personas)

    for status, exp_cnt in expected.items():
        act_cnt = actual.get(status, 0)
        if act_cnt != exp_cnt:
            errors.append(f"Count mismatch [{status}]: expected {exp_cnt}, got {act_cnt}")

    if len(personas) != expected_total:
        errors.append(f"Total count: expected {expected_total}, got {len(personas)}")

    # ── Per-persona rules ─────────────────────────────────────────────────────
    for p in personas:
        pid    = p.get("persona_id", "?")
        status = p.get("care_gap_status")
        ab     = p.get("age_band_code")
        excl   = p.get("exclusion_reason")
        enrolled = p.get("is_enrolled")
        has_excl = p.get("has_any_exclusion")
        has_svc  = p.get("has_compliance_service")

        # Rule 3: Valid status
        if status not in valid_statuses:
            errors.append(f"[{pid}] Invalid status: {status}")

        # Rule 4: Valid GC code
        if p.get("gender_criteria_code") not in gc_codes:
            errors.append(f"[{pid}] Invalid gender_criteria_code: {p.get('gender_criteria_code')}")

        # Rule 5: Valid AB code
        if ab not in ab_codes:
            errors.append(f"[{pid}] Invalid age_band_code: {ab}")

        # Rule 6: AB2-only exclusions must not appear in AB1
        if excl and excl in ab2_only and ab == "AB1":
            errors.append(f"[{pid}] AB2-only exclusion '{excl}' used in AB1")

        # Rule 7: NOT_ELIGIBLE must have is_enrolled=False
        if status == "NOT_ELIGIBLE" and enrolled:
            errors.append(f"[{pid}] NOT_ELIGIBLE but is_enrolled=True")

        # Rule 8: EXCLUDED must have has_any_exclusion=True and valid exclusion_reason
        if status == "EXCLUDED":
            if not has_excl:
                errors.append(f"[{pid}] EXCLUDED but has_any_exclusion=False")
            if not excl:
                errors.append(f"[{pid}] EXCLUDED but exclusion_reason is null")
            elif excl not in excl_names:
                warnings.append(f"[{pid}] Unknown exclusion_reason: '{excl}'")

        # Rule 9: COMPLIANT must have has_compliance_service=True and no exclusion
        if status == "COMPLIANT":
            if not has_svc:
                errors.append(f"[{pid}] COMPLIANT but has_compliance_service=False")
            if has_excl:
                errors.append(f"[{pid}] COMPLIANT but has_any_exclusion=True")

        # Rule 10: OPEN_GAP must have has_compliance_service=False and no exclusion
        if status == "OPEN_GAP":
            if has_svc:
                errors.append(f"[{pid}] OPEN_GAP but has_compliance_service=True")
            if has_excl:
                errors.append(f"[{pid}] OPEN_GAP but has_any_exclusion=True")

    return errors, warnings, actual, expected


def main():
    if len(sys.argv) < 3:
        print("Usage: python validate_personas.py <config.json> <personas.json>")
        sys.exit(1)

    config   = load(sys.argv[1])
    personas = load(sys.argv[2])

    print(f"\nValidating {len(personas)} personas for {config['measure_id']}...\n")

    errors, warnings, actual, expected = validate(config, personas)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"{'Status':<20} {'Expected':>10} {'Actual':>10} {'Match':>8}")
    print("-" * 52)
    for status in config.get("gap_statuses", []):
        exp = expected.get(status, 0)
        act = actual.get(status, 0)
        match = "✅" if exp == act else "❌"
        print(f"{status:<20} {exp:>10} {act:>10} {match:>8}")
    print("-" * 52)
    print(f"{'TOTAL':<20} {sum(expected.values()):>10} {len(personas):>10} {'✅' if sum(expected.values()) == len(personas) else '❌':>8}")

    # ── Errors & Warnings ─────────────────────────────────────────────────────
    print(f"\nErrors   : {len(errors)}")
    for e in errors:
        print(f"  ❌ {e}")

    print(f"\nWarnings : {len(warnings)}")
    for w in warnings:
        print(f"  ⚠️  {w}")

    if not errors:
        print(f"\n✅ All personas are VALID for {config['measure_id']}")
    else:
        print(f"\n❌ {len(errors)} validation error(s) found — re-run persona_generator.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
