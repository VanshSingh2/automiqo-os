#!/usr/bin/env python3
"""
run_evals.py — CLI wrapper for the automiqo-os eval harness.

Usage
-----
    python scripts/run_evals.py                 # human-readable PASS/FAIL table
    python scripts/run_evals.py --json          # machine-readable JSON summary
    python scripts/run_evals.py --scenarios PATH# run an alternate scenario file

What it does
------------
Runs the golden scenario set (evals/scenarios.json) against the backend's
decision logic — the verification engine (allow | escalate | block verdicts)
and the policy engine (requires_approval gate) — scores each scenario pass/fail,
prints a summary, and exits non-zero if ANY scenario fails.

Offline & deterministic
------------------------
The harness runs entirely OFFLINE: no network calls and no API keys required.
The verification LLM-as-judge and grounding are forced OFF in-process, so every
verdict comes only from the fast, rule-based path. Results are stable run to run.

Why it exists (CI / canary gate)
---------------------------------
This is the canary for prompt + workflow changes. Wire it into CI:

    python scripts/run_evals.py            # exit 0 = golden set holds, 1 = drift

If someone edits a prompt, adds a workflow, or changes a policy/verification
rule in a way that shifts a decision the golden set expected, the run fails and
CI blocks the change until the behavior (or the golden expectation) is
reconciled deliberately.
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
import argparse

# Ensure the repo root is importable regardless of CWD.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from evals import runner  # noqa: E402


def _print_table(summary: dict) -> None:
    results = summary.get("results", [])
    id_width = max([len("SCENARIO")] + [len(str(r.get("id", ""))) for r in results])
    kind_width = max([len("KIND")] + [len(str(r.get("kind", ""))) for r in results])

    header = f"{'RESULT':<6}  {'SCENARIO':<{id_width}}  {'KIND':<{kind_width}}  EXPECTED -> ACTUAL"
    print(header)
    print("-" * len(header))
    for r in results:
        mark = "PASS" if r.get("passed") else "FAIL"
        sid = str(r.get("id", ""))
        kind = str(r.get("kind", ""))
        expected = r.get("expected")
        actual = r.get("actual")
        line = f"{mark:<6}  {sid:<{id_width}}  {kind:<{kind_width}}  {expected!r} -> {actual!r}"
        print(line)
        if not r.get("passed") and r.get("detail"):
            print(f"        detail: {r.get('detail')}")

    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    pct = summary.get("pass_rate", 0.0) * 100.0
    print("-" * len(header))
    print(f"{passed}/{total} passed ({pct:.1f}%)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the automiqo-os eval harness (offline, deterministic CI canary)."
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--scenarios", metavar="PATH", default=None,
                        help="path to an alternate scenarios.json (defaults to evals/scenarios.json)")
    args = parser.parse_args(argv)

    scenarios = runner.load_scenarios(args.scenarios) if args.scenarios else None
    summary = asyncio.run(runner.run_all(scenarios))

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        _print_table(summary)

    return 1 if summary.get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
