"""
Aria — entry point.

Usage:
    python run.py

Prerequisites:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...   (or use `ant auth login`)

Output files are written to output/ after a successful run:
    output/corrections.json   machine-readable correction log
    output/aria_report.md     human-readable audit report
"""

import sys
from aria import state
from aria.agent import run_investigation, run_write_phase


def main() -> None:
    print("\n  Aria  ·  Reconciliation Agent  ·  October 2026")
    print("  Model: claude-sonnet-5-5\n")

    # ── Phase 1: investigate ──────────────────────────────────────────────
    validated = run_investigation()

    if not validated:
        print("\n✗  Aria did not submit a valid correction plan.")
        print("   Check the output above for details.\n")
        sys.exit(1)

    # ── Gate: plan accepted ───────────────────────────────────────────────
    print("\n  ✓  Plan validated by Python validator.")
    print(f"     {len(state.pending_plan['discrepancies'])} discrepancies · "
          f"${state.pending_plan['net_adjustment']:,.2f} net GL adjustment\n")

    # ── Phase 2: apply corrections and write report ───────────────────────
    run_write_phase()

    if state.report_path:
        print(f"\n  Report written → {state.report_path}")
    if state.corrections_applied:
        print(f"  Corrections logged → output/corrections.json "
              f"({len(state.corrections_applied)} entries)")

    print("\n  Aria complete.\n")


if __name__ == "__main__":
    main()
