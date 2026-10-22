"""
Read-only investigation tools — available in Phase 1 only.

All four tools load static JSON fixtures. In a real system these would
query a database or call an API; the fixture approach keeps the project
self-contained and the bugs deterministic.
"""

import json
from pathlib import Path
from anthropic import beta_tool

DATA_DIR = Path(__file__).parent.parent / "data"


def _load_crm() -> dict:
    return json.loads((DATA_DIR / "crm_october.json").read_text())


def _load_gl() -> dict:
    return json.loads((DATA_DIR / "gl_october.json").read_text())


@beta_tool
def query_crm(deal_id: str = "") -> str:
    """Query CRM billing records for October 2026.

    Args:
        deal_id: Filter by a specific deal ID (e.g. 'D007'). Leave empty to return all records.
    """
    data = _load_crm()
    records = data["records"]
    if deal_id:
        records = [r for r in records if r["deal_id"] == deal_id]
    return json.dumps({
        "source": data["source"],
        "period": data["period"],
        "total_reported": data["total_reported"],
        "record_count": len(records),
        "records": records,
    }, indent=2)


@beta_tool
def query_gl(deal_ref: str = "") -> str:
    """Query General Ledger revenue entries for October 2026.

    Args:
        deal_ref: Filter by a specific deal reference (e.g. 'D009'). Leave empty for all entries.
    """
    data = _load_gl()
    entries = data["entries"]
    if deal_ref:
        entries = [e for e in entries if e["deal_ref"] == deal_ref]
    return json.dumps({
        "source": data["source"],
        "period": data["period"],
        "total_reported": data["total_reported"],
        "entry_count": len(entries),
        "entries": entries,
    }, indent=2)


@beta_tool
def get_summary() -> str:
    """Get a high-level summary: totals, record counts, and the reported delta between CRM and GL."""
    crm = _load_crm()
    gl = _load_gl()

    crm_deal_ids = [r["deal_id"] for r in crm["records"]]
    gl_deal_refs = [e["deal_ref"] for e in gl["entries"]]
    crm_unique = set(crm_deal_ids)
    gl_unique = set(gl_deal_refs)

    crm_total = crm["total_reported"]
    gl_total = gl["total_reported"]

    return json.dumps({
        "crm_total_reported": crm_total,
        "crm_record_count": len(crm["records"]),
        "crm_unique_deal_ids": len(crm_unique),
        "gl_total_reported": gl_total,
        "gl_entry_count": len(gl["entries"]),
        "gl_unique_deal_refs": len(gl_unique),
        "delta_crm_minus_gl": crm_total - gl_total,
        "deals_in_crm_not_gl": sorted(crm_unique - gl_unique),
        "deals_in_gl_not_crm": sorted(gl_unique - crm_unique),
    }, indent=2)


@beta_tool
def compare_sources() -> str:
    """Compare every deal side-by-side: CRM amount vs GL amount, highlighting mismatches."""
    crm = _load_crm()
    gl = _load_gl()

    crm_by_deal: dict[str, list] = {}
    for r in crm["records"]:
        crm_by_deal.setdefault(r["deal_id"], []).append(r)

    gl_by_deal: dict[str, list] = {}
    for e in gl["entries"]:
        gl_by_deal.setdefault(e["deal_ref"], []).append(e)

    all_deals = sorted(set(list(crm_by_deal) + list(gl_by_deal)))
    rows = []
    for deal_id in all_deals:
        crm_records = crm_by_deal.get(deal_id, [])
        gl_entries  = gl_by_deal.get(deal_id, [])
        crm_amount  = sum(r["amount"] for r in crm_records)
        gl_amount   = sum(e["amount"] for e in gl_entries)
        diff        = crm_amount - gl_amount
        rows.append({
            "deal_id":          deal_id,
            "crm_record_count": len(crm_records),
            "crm_total":        crm_amount,
            "gl_entry_count":   len(gl_entries),
            "gl_total":         gl_amount,
            "diff_crm_minus_gl": diff,
            "status":           "OK" if abs(diff) < 0.01 else "MISMATCH",
        })

    mismatches = [r for r in rows if r["status"] != "OK"]
    return json.dumps({
        "total_deals": len(rows),
        "mismatches_found": len(mismatches),
        "comparison": rows,
    }, indent=2)
