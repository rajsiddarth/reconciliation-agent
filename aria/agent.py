"""
Aria — core orchestrator.

Runs the two-phase agentic loop:

  Phase 1  Investigation with read-only tools.
           Aria calls get_summary, compare_sources, query_crm, query_gl, and
           submit_plan. submit_plan is the gate: it validates the plan with
           plain Python before signalling that write access is granted.

  Gate     Python validates the CorrectionPlan before any writes happen.
           This is deterministic code, not an API feature.

  Phase 2  Write phase with post_correction and write_report.
           These tools are injected only after the gate passes.
"""

import json
import sys
import anthropic
from anthropic import beta_tool

from aria import state
from aria.tools.read_tools import query_crm, query_gl, get_summary, compare_sources
from aria.tools.write_tools import post_correction, write_report
from aria.validator import validate_plan

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

_WRITE_PROMPT_TEMPLATE = """\
Your correction plan has been validated and write access is now granted.

APPROVED PLAN
-------------
{plan_json}

TASKS
-----
1. Call post_correction() for each discrepancy that requires a ledger adjustment.
   Use the evidence field to reference the specific source record.
2. Call write_report() with a summary, the true revenue figure, and structured findings.

Apply all corrections before writing the report.
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
            "hand control to the write phase. Do not make further tool calls."
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
    """Phase 2: apply corrections and write the report using the validated plan."""
    _header("Phase 2 — Applying Corrections")

    prompt = _WRITE_PROMPT_TEMPLATE.format(
        plan_json=json.dumps(state.pending_plan, indent=2)
    )

    runner = client.beta.messages.tool_runner(
        model="claude-sonnet-5-5",
        max_tokens=8_000,
        tools=[post_correction, write_report],
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
