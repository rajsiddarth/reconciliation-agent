"""
Shared mutable state for Aria's investigation phases.

Module-level variables act as a simple in-process store. Any module that
imports `aria.state` reads and writes the same objects.
"""

# Set by submit_plan() when Aria calls it; consumed by the gate check.
pending_plan: dict | None = None

# Flipped to True once the validator accepts a plan.
validated: bool = False

# Accumulates each post_correction() call result.
corrections_applied: list[dict] = []

# Set by write_report() when the audit report is written.
report_path: str | None = None

# Flipped to True once the independent check (Gate 2) passes.
check_passed: bool = False
