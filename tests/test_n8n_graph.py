"""Locks in the n8n workflow-graph integrity (offline, no deps).

Runs the deep validator over every workflow and asserts all graphs are clean —
connection targets exist, no orphaned branches, no dangling `$('Node')` refs,
and every response-node webhook has a reachable respondToWebhook. Guards against
regressions in the workflow JSONs.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.validate_n8n import validate_all  # noqa: E402


def test_all_n8n_workflow_graphs_are_clean():
    results = validate_all()
    assert results == {}, (
        "n8n workflow graph issues found:\n"
        + "\n".join(f"  {os.path.basename(f)}: {issues}" for f, issues in results.items())
    )
