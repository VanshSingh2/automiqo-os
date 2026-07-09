"""
evals.runner — execute the golden scenario set against the backend decision logic.

Design goals
------------
* OFFLINE + DETERMINISTIC: no network, no API keys. ``run_all`` forces the
  verification engine's LLM-as-judge and grounding OFF in-process so verdicts
  come only from the cheap, rule-based path. That makes this safe for CI.
* DEFENSIVE: every scenario is wrapped in try/except. A scenario that raises is
  reported as ``passed=False`` with the error in ``detail`` — the harness itself
  never crashes.
* IMPORTABLE OFFLINE: the heavy ``supabase`` SDK is not installed in CI. If it is
  missing we inject a tiny stub into ``sys.modules`` *before* importing the
  backend engines, mirroring what the test suite's conftest does. Only the
  Python standard library is used by this module.

Scenario kinds
--------------
* ``"verification"`` — input ``{workflow, parameters, reason}``. Runs
  ``backend.engines.verification_engine.evaluate_action`` and compares the
  resulting ``verdict`` (``allow`` | ``escalate`` | ``block``) to ``expect``.
* ``"policy"`` — input ``{workflow}``. Runs
  ``backend.engines.policy_engine.policy.check(workflow)`` and compares
  ``requires_approval`` (bool) to ``expect``.
* ``"agent"`` — reserved for a future live-LLM eval kind. Not implemented here;
  ``run_scenario`` reports it as a skipped failure so it is impossible to add an
  ``agent`` scenario by accident and have it silently "pass". The dispatch table
  is structured so a real implementation can be dropped in later.

Public API
----------
* ``load_scenarios(path=None) -> list``
* ``async def run_scenario(s) -> dict``
* ``async def run_all(scenarios=None) -> dict``
"""
from __future__ import annotations

import os
import sys
import json

# ── make the repo root importable (so ``backend`` resolves when this module is
#    imported from scripts/ or from an arbitrary CWD) ────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── offline stub for the heavy supabase SDK (stdlib only) ────────────────────
# The backend engines import ``backend.memory.supabase_client`` at module load
# time, which does ``from supabase import create_client, Client``. In CI the SDK
# is not installed, so provide a harmless stub. If the real package IS present
# (or already stubbed by the test conftest), we leave it untouched.
try:  # pragma: no cover - depends on environment
    import supabase  # noqa: F401
except Exception:  # ImportError and anything else
    from unittest.mock import MagicMock

    _stub = MagicMock(name="supabase_stub")
    _stub.create_client = MagicMock(name="create_client")
    _stub.Client = object
    sys.modules["supabase"] = _stub


DEFAULT_SCENARIOS_PATH = os.path.join(_THIS_DIR, "scenarios.json")

# A stable, obviously-fake business id used for verification scenarios. It never
# touches a real datastore because grounding/governor lookups fail-safe offline.
_EVAL_BUSINESS_ID = "eval-biz"

_VALID_KINDS = ("verification", "policy", "agent")


def load_scenarios(path: str | None = None) -> list:
    """Load the golden scenario set.

    Defaults to ``evals/scenarios.json`` next to this module. Returns a list of
    scenario dicts. Raises only if the file is missing or not valid JSON — those
    are genuine configuration errors the caller should see.
    """
    path = path or DEFAULT_SCENARIOS_PATH
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "scenarios" in data:
        data = data["scenarios"]
    if not isinstance(data, list):
        raise ValueError(f"scenarios file {path!r} must contain a JSON list of scenarios")
    return data


def _expand_params(parameters: dict) -> dict:
    """Materialize scenario parameter conventions into concrete values.

    Keeps ``scenarios.json`` compact and readable instead of embedding huge
    literals. Supported conventions (all optional):

      * ``"__oversized__": N`` -> inject ``{"blob": "x" * N}`` so the payload
        serializes to more than the engine's max-param threshold. This lets a
        scenario exercise the "oversized_parameters" rule without a giant JSON
        literal in the golden file.
    """
    if not isinstance(parameters, dict):
        return {}
    out = dict(parameters)
    n = out.pop("__oversized__", None)
    if isinstance(n, int) and n > 0:
        out["blob"] = "x" * n
    return out


async def _run_verification(s: dict) -> tuple:
    """Return ``(actual, detail)`` for a verification scenario."""
    from backend.engines import verification_engine

    inp = s.get("input") or {}
    workflow = inp.get("workflow", "")
    parameters = _expand_params(inp.get("parameters") or {})
    reason = inp.get("reason", "")
    result = await verification_engine.evaluate_action(
        _EVAL_BUSINESS_ID, workflow, parameters, reason
    )
    actual = result.get("verdict")
    detail = f"score={result.get('score')} reasons={result.get('reasons')}"
    return actual, detail


async def _run_policy(s: dict) -> tuple:
    """Return ``(actual, detail)`` for a policy scenario."""
    from backend.engines.policy_engine import policy

    inp = s.get("input") or {}
    workflow = inp.get("workflow", "")
    result = policy.check(workflow)
    actual = bool(result.requires_approval)
    detail = f"risk={result.risk_level} policy={result.policy_name}"
    return actual, detail


async def run_scenario(s: dict) -> dict:
    """Run a single scenario and return a structured result.

    Returns ``{id, kind, passed, expected, actual, detail}``. Any exception is
    caught and reported as ``passed=False`` with the error text in ``detail`` so
    one broken scenario can never abort the whole run.
    """
    sid = (s or {}).get("id", "<no-id>")
    kind = (s or {}).get("kind", "<no-kind>")
    expected = (s or {}).get("expect")
    actual = None
    detail = ""
    try:
        if kind == "verification":
            actual, detail = await _run_verification(s)
        elif kind == "policy":
            actual, detail = await _run_policy(s)
        elif kind == "agent":
            # Reserved for future live-LLM evals. Intentionally not supported in
            # the offline harness — report as a non-passing skip.
            detail = "agent kind not supported in offline harness"
            return {
                "id": sid, "kind": kind, "passed": False,
                "expected": expected, "actual": None, "detail": detail,
            }
        else:
            detail = f"unknown scenario kind: {kind!r}"
            return {
                "id": sid, "kind": kind, "passed": False,
                "expected": expected, "actual": None, "detail": detail,
            }

        passed = actual == expected
        return {
            "id": sid, "kind": kind, "passed": bool(passed),
            "expected": expected, "actual": actual, "detail": detail,
        }
    except Exception as e:  # defensive: never let a scenario crash the run
        return {
            "id": sid, "kind": kind, "passed": False,
            "expected": expected, "actual": None,
            "detail": f"error: {type(e).__name__}: {e}",
        }


async def run_all(scenarios: list | None = None) -> dict:
    """Run every scenario and return an aggregate summary.

    Sets ``VERIFY_LLM_JUDGE`` and ``VERIFY_GROUNDING`` to ``"false"`` up front so
    the verification engine stays purely rule-based / deterministic offline.

    Returns ``{total, passed, failed, pass_rate, results}`` where ``pass_rate``
    is a float in ``[0, 1]`` (0.0 when there are no scenarios).
    """
    # Force determinism/offline BEFORE any evaluation runs.
    os.environ["VERIFY_LLM_JUDGE"] = "false"
    os.environ["VERIFY_GROUNDING"] = "false"

    if scenarios is None:
        scenarios = load_scenarios()

    results = []
    for s in scenarios:
        results.append(await run_scenario(s))

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    pass_rate = (passed / total) if total else 0.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "results": results,
    }
