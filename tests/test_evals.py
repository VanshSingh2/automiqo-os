"""
Offline tests for the eval harness.

These run under pytest, so tests/conftest.py has already stubbed the heavy
third-party SDKs (supabase, langchain, ...) in sys.modules and disabled the
verification LLM judge — everything here is deterministic and offline.

The most valuable assertion is that the golden set passes 100% offline
(pass_rate == 1.0): that is the proof that the backend's decision logic still
matches the documented expectations. If it ever drifts, this test fails.
"""
import asyncio

from evals import runner


def test_scenarios_load_and_are_nonempty():
    scenarios = runner.load_scenarios()
    assert isinstance(scenarios, list)
    assert len(scenarios) > 0


def test_every_scenario_has_required_fields():
    scenarios = runner.load_scenarios()
    valid_kinds = {"verification", "policy", "agent"}
    seen_ids = set()
    for s in scenarios:
        assert "id" in s and s["id"], f"scenario missing id: {s}"
        assert s["id"] not in seen_ids, f"duplicate scenario id: {s['id']}"
        seen_ids.add(s["id"])
        assert "kind" in s and s["kind"] in valid_kinds, f"bad kind: {s}"
        assert "input" in s and isinstance(s["input"], dict), f"bad input: {s}"
        assert "expect" in s, f"missing expect: {s}"


def test_run_all_shape_and_totals():
    scenarios = runner.load_scenarios()
    summary = asyncio.run(runner.run_all(scenarios))

    assert summary["total"] == len(scenarios)
    assert summary["passed"] + summary["failed"] == summary["total"]
    assert isinstance(summary["pass_rate"], float)
    assert 0.0 <= summary["pass_rate"] <= 1.0
    assert len(summary["results"]) == summary["total"]

    for r in summary["results"]:
        assert set(r.keys()) == {"id", "kind", "passed", "expected", "actual", "detail"}
        assert isinstance(r["passed"], bool)


def test_run_all_defaults_to_bundled_scenarios():
    # Called with no argument -> loads evals/scenarios.json internally.
    summary = asyncio.run(runner.run_all())
    assert summary["total"] > 0


def test_golden_set_fully_passes_offline():
    # The real value of the harness: the decision logic matches expectations.
    summary = asyncio.run(runner.run_all())
    failures = [r for r in summary["results"] if not r["passed"]]
    assert summary["pass_rate"] == 1.0, (
        "golden eval set drifted; failing scenarios:\n"
        + "\n".join(f"  {r['id']}: expected {r['expected']!r} got {r['actual']!r} ({r['detail']})"
                    for r in failures)
    )
