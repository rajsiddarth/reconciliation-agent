"""
Write tools — injected into the agent loop ONLY after the validator approves the plan.

Both tools write to the output/ directory. Running the project produces:
  output/corrections.json  — machine-readable correction log
  output/aria_report.md    — human-readable audit report
"""

import json
import datetime
from pathlib import Path
from anthropic import beta_tool
from aria import state

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


@beta_tool
def post_correction(
    deal_id: str,
    correction_type: str,
    amount: float,
    description: str,
    evidence: str,
) -> str:
    """Post a validated correction to the ledger correction log.

    Args:
        deal_id: The deal this correction applies to (e.g. 'D007').
        correction_type: One of 'remove_duplicate', 'post_missing_entry', 'fix_amount'.
        amount: Dollar amount of the correction (positive = increases GL effective total).
        description: Plain-language description of what is being corrected and why.
        evidence: Source record reference that justifies this correction (e.g. 'CRM-2026-007B').
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    log_path = OUTPUT_DIR / "corrections.json"

    entry = {
        "correction_id": f"CORR-{len(state.corrections_applied) + 1:03d}",
        "deal_id":        deal_id,
        "correction_type": correction_type,
        "amount":         amount,
        "description":    description,
        "evidence":       evidence,
        "applied_at":     datetime.datetime.utcnow().isoformat() + "Z",
        "applied_by":     "aria",
    }

    state.corrections_applied.append(entry)

    existing: list = json.loads(log_path.read_text()) if log_path.exists() else []
    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2))

    return json.dumps({"status": "posted", "correction": entry}, indent=2)


@beta_tool
def write_report(
    summary: str,
    true_revenue: float,
    findings: list,
    corrections_count: int,
) -> str:
    """Write the final audit report to output/aria_report.md.

    Args:
        summary: Executive summary of the investigation (2-4 sentences).
        true_revenue: The reconciled true October revenue figure.
        findings: List of dicts, each with keys: deal_id, issue, impact, resolution.
        corrections_count: Total number of corrections applied.
    """
    OUTPUT_DIR.mkdir(exist_ok=True)
    report_path = OUTPUT_DIR / "aria_report.md"

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Aria Reconciliation Report — October 2026",
        "",
        f"**Generated:** {now}  ",
        "**Agent:** Aria (`claude-sonnet-5-5`)  ",
        f"**Corrections applied:** {corrections_count}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        summary,
        "",
        "---",
        "",
        "## Findings",
        "",
    ]

    for i, f in enumerate(findings, 1):
        lines += [
            f"### {i}. Deal {f.get('deal_id', 'N/A')}",
            "",
            f"**Issue:** {f.get('issue', '')}  ",
            f"**Impact:** {f.get('impact', '')}  ",
            f"**Resolution:** {f.get('resolution', '')}",
            "",
        ]

    lines += [
        "---",
        "",
        "## Reconciled Totals",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        "| CRM reported | $847,250.00 |",
        "| GL reported | $821,500.00 |",
        "| Reported delta | $25,750.00 |",
        f"| **True October revenue** | **${true_revenue:,.2f}** |",
        f"| Corrections applied | {corrections_count} |",
        "",
        "---",
        "",
        "_Report produced by Aria. All corrections reference original source records._",
    ]

    report_path.write_text("\n".join(lines))
    state.report_path = str(report_path)

    return json.dumps({
        "status": "written",
        "path": str(report_path),
        "true_revenue": true_revenue,
    }, indent=2)
