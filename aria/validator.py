"""
CorrectionPlan validator — the Python gate between investigation and write access.

A plan must pass all checks before write tools are injected into the agent loop.
This is ordinary Python logic, not an API feature: it demonstrates that the
permission boundary lives in the orchestrating code, not inside the model.
"""

EXPECTED_CRM_TOTAL     = 847_250.00
EXPECTED_GL_TOTAL      = 821_500.00
EXPECTED_DELTA         = 25_750.00   # CRM − GL
REQUIRED_DEALS         = {"D007", "D009", "D003"}
REQUIRED_FIELDS        = {"type", "deal_id", "description", "amount", "evidence"}

# Gate 2 constants: expected net GL adjustment after posting the two missing/wrong entries.
# D009 ($8,000 missing) + D003 fix ($3,000 underpayment) = $11,000.
EXPECTED_GL_NET        = 11_000.00
KNOWN_DEAL_IDS         = {f"D{n:03d}" for n in range(1, 12)}   # D001 – D011


def validate_plan(plan: dict) -> dict:
    """
    Validate a correction plan submitted by Aria.

    Returns:
        {"valid": True, "message": str}   on success
        {"valid": False, "message": str}  on failure — message tells Aria what to fix
    """
    errors: list[str] = []

    # ── 1. Top-level shape ──────────────────────────────────────────────────
    for field in ("discrepancies", "total_crm", "total_gl", "net_adjustment", "explanation"):
        if field not in plan:
            errors.append(f"Missing required top-level field: '{field}'")

    if errors:
        return {"valid": False, "message": " | ".join(errors)}

    # ── 2. Reported totals must match source data ───────────────────────────
    if abs(plan["total_crm"] - EXPECTED_CRM_TOTAL) > 1.0:
        errors.append(
            f"total_crm ${plan['total_crm']:,.2f} does not match "
            f"the CRM source total (${EXPECTED_CRM_TOTAL:,.2f})"
        )
    if abs(plan["total_gl"] - EXPECTED_GL_TOTAL) > 1.0:
        errors.append(
            f"total_gl ${plan['total_gl']:,.2f} does not match "
            f"the GL source total (${EXPECTED_GL_TOTAL:,.2f})"
        )

    # ── 3. Discrepancy list structure ───────────────────────────────────────
    discrepancies = plan["discrepancies"]
    if not isinstance(discrepancies, list) or len(discrepancies) == 0:
        errors.append("'discrepancies' must be a non-empty list")
        return {"valid": False, "message": " | ".join(errors)}

    for i, d in enumerate(discrepancies):
        if not isinstance(d, dict):
            errors.append(f"discrepancies[{i}] must be a dict")
            continue
        missing = REQUIRED_FIELDS - set(d.keys())
        if missing:
            errors.append(f"discrepancies[{i}] is missing fields: {sorted(missing)}")

    if errors:
        return {"valid": False, "message": " | ".join(errors)}

    # ── 4. All three root-cause deals must be addressed ─────────────────────
    mentioned_deals = {d["deal_id"] for d in discrepancies}
    missing_deals = REQUIRED_DEALS - mentioned_deals
    if missing_deals:
        errors.append(
            f"Plan does not address all discrepancies — missing deals: {sorted(missing_deals)}. "
            f"The full $25,750 delta cannot be explained without all three."
        )

    # ── 5. Discrepancy amounts must account for the full delta ───────────────
    total_explained = sum(abs(float(d["amount"])) for d in discrepancies)
    if abs(total_explained - EXPECTED_DELTA) > 1.0:
        errors.append(
            f"Discrepancy amounts total ${total_explained:,.2f} but the "
            f"reported delta is ${EXPECTED_DELTA:,.2f}. "
            f"Every dollar must be accounted for."
        )

    if errors:
        return {"valid": False, "message": " | ".join(errors)}

    return {
        "valid": True,
        "message": (
            f"All {len(discrepancies)} discrepancies validated. "
            f"Amounts account for the full $25,750 delta. "
            f"Write access granted."
        ),
    }


def independent_check(corrections: list[dict]) -> dict:
    """
    Gate 2: verify corrections independently of Claude.

    Checks applied corrections against source-level expectations without
    relying on Claude's own description of what it posted.

    Returns:
        {"passed": True,  "message": str}
        {"passed": False, "message": str, "remaining_difference": float}
    """
    errors: list[str] = []

    if not corrections:
        return {
            "passed": False,
            "message": "No corrections were posted.",
            "remaining_difference": EXPECTED_GL_NET,
        }

    # ── 1. All deal IDs must be in the known dataset ────────────────────────
    for c in corrections:
        if c.get("deal_id", "") not in KNOWN_DEAL_IDS:
            errors.append(
                f"Correction {c.get('correction_id')} references unknown "
                f"deal_id '{c.get('deal_id')}'"
            )

    # ── 2. No duplicate corrections (same deal_id + correction_type) ─────────
    seen: set[tuple] = set()
    for c in corrections:
        key = (c.get("deal_id"), c.get("correction_type"))
        if key in seen:
            errors.append(
                f"Duplicate correction: deal_id='{key[0]}' "
                f"correction_type='{key[1]}'"
            )
        seen.add(key)

    # ── 3. Every correction must have an evidence reference ──────────────────
    for c in corrections:
        if not str(c.get("evidence", "")).strip():
            errors.append(
                f"Correction {c.get('correction_id')} for {c.get('deal_id')} "
                f"has no evidence reference"
            )

    # ── 4. GL-side adjustments must sum to the expected net ──────────────────
    gl_types = {"post_missing_entry", "fix_amount"}
    gl_total = sum(
        float(c.get("amount", 0))
        for c in corrections
        if c.get("correction_type") in gl_types
    )
    remaining = abs(gl_total - EXPECTED_GL_NET)
    if remaining > 1.0:
        errors.append(
            f"GL adjustments total ${gl_total:,.2f} but expected "
            f"${EXPECTED_GL_NET:,.2f} "
            f"(D009 post_missing_entry $8,000 + D003 fix_amount $3,000). "
            f"Remaining difference: ${remaining:,.2f}"
        )

    if errors:
        return {
            "passed": False,
            "message": " | ".join(errors),
            "remaining_difference": remaining,
        }

    return {
        "passed": True,
        "message": (
            f"{len(corrections)} corrections verified. "
            f"GL net adjustment ${gl_total:,.2f} matches expected. "
            f"write_report unlocked."
        ),
    }
