"""
Eval harness for automiqo-os.

A golden set of scenarios with expected outcomes, run against the backend's
decision logic (verification_engine + policy_engine), scored pass/fail.

Everything here is designed to run OFFLINE and DETERMINISTICALLY:
  * No network, no API keys required.
  * The verification LLM-as-judge and grounding are forced OFF in-process
    (see runner.run_all), so verdicts come only from the cheap, rule-based path.

Intended as a CI / canary gate: if a prompt or workflow change silently shifts a
decision (drift), the golden set stops passing and CI fails.
"""
