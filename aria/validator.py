"""
CorrectionPlan validator — the Python gate between investigation and write access.

A plan must pass all checks before write tools are injected into the agent loop.
This is ordinary Python logic, not an API feature: it demonstrates that the
permission boundary lives in the orchestrating code, not inside the model.
"""

EXPECTED_CRM_TOTAL = 847_250.00
EXPECTED_GL_TOTAL  = 821_500.00
EXPECTED_DELTA     = 25_750.00   # CRM − GL
REQUIRED_DEALS     = {"D007", "D009", "D003"}
REQUIRED_FIELDS    = {"type", "deal_id", "description", "amount", "evidence"}


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
