"""
Aria — core orchestrator.

Runs the three-phase agentic loop:

  Phase 1  Investigation with read-only tools.
           Aria calls get_summary, compare_sources, query_crm, query_gl, and
           submit_plan. submit_plan is Gate 1: it validates the plan with
           plain Python before signalling that write access is granted.

  Gate 1   Python validates the CorrectionPlan before any writes happen.

  Phase 2a Corrections phase: only post_correction is available.
           Aria applies each correction identified in the plan.

  Gate 2   Python independently re-verifies the corrections without relying
           on Claude's description of what it posted. If verification fails,
           Aria is given the remaining difference and retries (up to 3×).

  Phase 2b Report phase: write_report is injected only after Gate 2 passes.
           Aria writes the human-readable audit report.
"""

import json
import sys
import anthropic
from anthropic import beta_tool

from aria import state
from aria.tools.read_tools import query_crm, query_gl, get_summary, compare_sources
from aria.tools.write_tools import post_correction, write_report
from aria.validator import validate_plan, independent_check

client = anthropic.Anthropic()

_INVESTIGATION_PROMPT = """\
You are Aria, a precise reconciliation agent for CorditeLabs.

MISSION
-------
Investigate a month-end revenue mismatch for October 2026 and submit an
evidence-backed correction plan.

KNOWN FIGURES
-------------
CRM reports:  $847,250.00  (12 records)
GL reports:   $821,500.00  (11 entries)
Delta:         $25,750.00  — every dollar must be explained.

PROTOCOL
--------
1. Call get_summary() to confirm the top-level numbers.
2. Call compare_sources() to find all deal-level discrepancies.
3. Use query_crm() and query_gl() to drill into any suspicious deals.
4. When you have evidence for EVERY dollar of the $25,750 gap, call submit_plan().

RULES
-----
- Never guess. Every claim in your plan must reference a specific record you retrieved.
- Do not call submit_plan() until you can explain the full delta.
- If the validator rejects your plan, read the feedback, investigate further, and resubmit.
"""

_CORRECTIONS_PROMPT_TEMPLATE = """\
Your correction plan has been validated and post_correction is now available.

APPROVED PLAN
-------------
{plan_json}

TASK
----
Call post_correction() for each discrepancy that requires a ledger adjustment.
Use the evidence field to reference the specific source record (e.g. 'GL-OCT-012').

Apply all corrections. Do not call write_report — that tool is not yet available.
"""

_CORRECTIONS_RETRY_TEMPLATE = """\
The independent check found issues with the corrections you applied:

ERRORS
------
{feedback}

CORRECTIONS ALREADY POSTED (now cleared)
-----------------------------------------
{corrections}

Call post_correction() again with corrected values.
Trace each amount back to its source record before calling.
"""

_REPORT_PROMPT_TEMPLATE = """\
All corrections have been independently verified and write_report is now available.

VERIFICATION RESULT
-------------------
{check_message}

CORRECTIONS APPLIED
-------------------
{corrections_json}

TASK
----
Call write_report() once with:
  - summary: 2–4 sentence executive summary
  - true_revenue: the reconciled October revenue (CRM after duplicate removal = GL after adjustments)
  - findings: one entry per deal (deal_id, issue, impact, resolution)
  - corrections_count: number of corrections applied
"""


@beta_tool
def submit_plan(
    discrepancies: list,
    total_crm: float,
    total_gl: float,
    net_adjustment: float,
    explanation: str,
) -> str:
    """Submit a correction plan for Python validation. Write tools unlock only if this passes.

    Args:
        discrepancies: List of dicts, each with keys: type, deal_id, description, amount, evidence.
        total_crm: Total CRM revenue as reported ($847,250.00).
        total_gl: Total GL revenue as reported ($821,500.00).
        net_adjustment: Net dollar adjustment to apply to the GL to reach true revenue.
        explanation: Plain-language summary of all findings.
    """
    plan = {
        "discrepancies":  discrepancies,
        "total_crm":      total_crm,
        "total_gl":       total_gl,
        "net_adjustment": net_adjustment,
        "explanation":    explanation,
    }

    result = validate_plan(plan)

    if result["valid"]:
        state.pending_plan = plan
        state.validated    = True
        return (
            f"✓ Plan validated. {result['message']}\n\n"
            "Your investigation is complete. The Python orchestrator will now "
            "hand control to the corrections phase. Do not make further tool calls."
        )
    else:
        return (
            f"✗ Validation failed: {result['message']}\n\n"
            "Please investigate further, correct the issues above, and call submit_plan() again."
        )


def run_investigation() -> bool:
    """Phase 1: read-only investigation loop. Returns True if a valid plan was submitted."""
    _header("Phase 1 — Investigation")

    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5-5",
        max_tokens=16_000,
        tools=[get_summary, compare_sources, query_crm, query_gl, submit_plan],
        messages=[{"role": "user", "content": _INVESTIGATION_PROMPT}],
    )

    for message in runner:
        _display(message)

    return state.validated


def run_write_phase() -> None:
    """Phases 2a → Gate 2 → 2b.

    2a: apply corrections (post_correction only)
    Gate 2: Python re-verifies corrections independently
    2b: write report (write_report injected only after Gate 2 passes)
    """
    _run_corrections()


def _run_corrections(feedback: str = "", attempt: int = 1) -> None:
    """Phase 2a: apply corrections. Calls Gate 2 on completion."""
    _header(f"Phase 2a — Applying Corrections (attempt {attempt}/3)")

    if feedback:
        state.corrections_applied.clear()
        prompt = _CORRECTIONS_RETRY_TEMPLATE.format(
            feedback=feedback,
            corrections=json.dumps(state.corrections_applied, indent=2),
        )
        max_tokens = 16_000
    else:
        prompt = _CORRECTIONS_PROMPT_TEMPLATE.format(
            plan_json=json.dumps(state.pending_plan, indent=2)
        )
        max_tokens = 8_000

    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5-5",
        max_tokens=max_tokens,
        tools=[post_correction],
        messages=[{"role": "user", "content": prompt}],
    )

    for message in runner:
        _display(message)

    _gate2(attempt)


def _gate2(attempt: int) -> None:
    """Gate 2: independent check. Unlocks write_report on pass; retries corrections on fail."""
    _header("Gate 2 — Independent Check")

    result = independent_check(state.corrections_applied)

    if result["passed"]:
        print(f"  ✓  {result['message']}\n")
        state.check_passed = True
        _run_report(result["message"])
    elif attempt < 3:
        print(f"  ✗  Independent check failed: {result['message']}")
        print(f"     Sending remaining difference to Aria — retry {attempt + 1}/3\n")
        _run_corrections(feedback=result["message"], attempt=attempt + 1)
    else:
        print(f"  ✗  Independent check failed after {attempt} attempts. Stopping.\n")
        sys.exit(1)


def _run_report(check_message: str) -> None:
    """Phase 2b: write the audit report. write_report is injected only after Gate 2 passes."""
    _header("Phase 2b — Writing Report")

    prompt = _REPORT_PROMPT_TEMPLATE.format(
        check_message=check_message,
        corrections_json=json.dumps(state.corrections_applied, indent=2),
    )

    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5-5",
        max_tokens=8_000,
        tools=[write_report],
        messages=[{"role": "user", "content": prompt}],
    )

    for message in runner:
        _display(message)


def _header(title: str) -> None:
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}\n")


def _display(message: anthropic.types.BetaMessage) -> None:
    for block in message.content:
        if block.type == "text" and block.text.strip():
            print(f"\nAria › {block.text.strip()}\n")
        elif block.type == "tool_use":
            args_preview = json.dumps(block.input, separators=(",", ":"))
            if len(args_preview) > 120:
                args_preview = args_preview[:117] + "…"
            print(f"  ↳ {block.name}({args_preview})")
