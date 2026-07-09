#!/usr/bin/env python3
"""
Deep validator for the n8n workflow graphs — a CI/pre-deploy gate.

Beyond "is it valid JSON", this checks the CONNECTION LOGIC of every workflow:
  * every connection source/target references a node that exists
  * no duplicate node names
  * every node is reachable from a trigger (no orphaned/dead branches)
  * every `$('Node')` expression reference points at a real node
  * a webhook with responseMode=responseNode has a REACHABLE respondToWebhook
    node (otherwise the dispatcher's HTTP call hangs until timeout)

Usage:
    python scripts/validate_n8n.py            # human report, exit 1 on any issue
    python scripts/validate_n8n.py --quiet    # only the summary line
"""
from __future__ import annotations
import glob
import json
import os
import re
import sys

_TRIGGER_HINTS = ("webhook", "trigger", "cron", "schedule", "interval")
_N8N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "n8n")


def validate_workflow(wf: dict) -> list:
    """Return a list of graph issues for one parsed workflow (empty == clean)."""
    problems: list = []
    nodes = wf.get("nodes", [])
    node_names = [n.get("name") for n in nodes]
    names = set(node_names)
    types = {n.get("name"): n.get("type", "") for n in nodes}
    conns = wf.get("connections", {}) or {}

    dups = {n for n in node_names if node_names.count(n) > 1}
    if dups:
        problems.append(f"duplicate node names: {sorted(dups)}")

    for src, outs in conns.items():
        if src not in names:
            problems.append(f"connection source is not a node: {src!r}")
        for group in (outs.get("main") or []):
            for c in (group or []):
                if c.get("node") not in names:
                    problems.append(f"connection -> missing node: {c.get('node')!r}")

    triggers = [n.get("name") for n in nodes
                if any(h in n.get("type", "").lower() for h in _TRIGGER_HINTS)]
    if not triggers:
        problems.append("no trigger node")

    # Reachability from the trigger(s).
    reach = set(triggers)
    frontier = list(triggers)
    while frontier:
        cur = frontier.pop()
        for group in ((conns.get(cur) or {}).get("main") or []):
            for c in (group or []):
                t = c.get("node")
                if t and t not in reach:
                    reach.add(t)
                    frontier.append(t)
    orphans = [n for n in node_names if n and n not in reach]
    if orphans and triggers:
        problems.append(f"unreachable nodes: {orphans}")

    # `$('Node')` expression references must exist.
    for ref in set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", json.dumps(wf))):
        if ref not in names:
            problems.append(f"$('{ref}') references a missing node")

    # Webhook response contract.
    wh = [n for n in nodes if n.get("type", "").lower().endswith("webhook")
          and "respond" not in n.get("type", "").lower()]
    if wh and any((n.get("parameters", {}) or {}).get("responseMode") == "responseNode" for n in wh):
        if not any("respondtowebhook" in types.get(nn, "").lower() for nn in reach):
            problems.append("responseMode=responseNode but no reachable respondToWebhook (dispatcher will hang)")

    return problems


def validate_all(n8n_dir: str = _N8N_DIR) -> dict:
    """Validate every workflow. Returns {file: [issues]} for files with issues."""
    out = {}
    for f in sorted(glob.glob(os.path.join(n8n_dir, "**", "*.json"), recursive=True)):
        try:
            wf = json.load(open(f, encoding="utf-8-sig"))
        except Exception as e:
            out[f] = [f"invalid JSON: {e}"]
            continue
        issues = validate_workflow(wf)
        if issues:
            out[f] = issues
    return out


def main(argv=None) -> int:
    quiet = "--quiet" in (argv or sys.argv[1:])
    results = validate_all()
    total = len(glob.glob(os.path.join(_N8N_DIR, "**", "*.json"), recursive=True))
    if results and not quiet:
        for f, issues in results.items():
            print(f"### {os.path.basename(f)}")
            for i in issues:
                print(f"   - {i}")
    print(f"{total - len(results)}/{total} workflows clean; {len(results)} with issues")
    return 1 if results else 0


if __name__ == "__main__":
    raise SystemExit(main())
