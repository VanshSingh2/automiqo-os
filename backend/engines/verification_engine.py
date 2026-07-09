"""
Verification / Eval Engine — a pre-execution safety gate.

Before an autonomous action auto-fires, score whether it is safe & sensible.
Low-confidence or high-blast-radius actions get ESCALATED to owner approval
instead of firing. This is defense-in-depth on top of the policy engine.

Contract:
    await evaluate_action(business_id, workflow, parameters, reason="") -> dict
    {
        "approved": bool,             # True only when verdict == "allow"
        "score":    float,            # 0..1 combined confidence
        "verdict":  "allow"|"escalate"|"block",
        "reasons":  [str],            # human-readable factors
    }

Everything is wrapped defensively. On ANY unexpected error we fail OPEN
(allow) so verification never breaks the pipeline — UNLESS VERIFY_FAIL_CLOSED=true
in which case we fail to "escalate".

Env vars:
    VERIFY_LLM_JUDGE          ("true"/"false", default TRUE) — enable LLM-as-judge
                              (only actually runs when OPENAI_API_KEY is also set)
    VERIFY_ESCALATE_THRESHOLD (float, default 0.5) — score below this escalates
    VERIFY_FAIL_CLOSED        ("true"/"false", default false) — error handling mode
    VERIFY_CONSISTENCY_SAMPLES (int, default 3) — for high/critical-risk actions,
                              the LLM judge is sampled this many times and the
                              samples are checked for agreement (self-consistency).
                              Only used when the judge actually runs.
    VERIFY_GROUNDING          ("true"/"false", default TRUE) — verify that any
                              referenced entity ids (customer_id/appointment_id/
                              lead_id) actually exist in the DB (anti-hallucination).
"""
import os
import json

from backend.obs import get_logger, log_event

_log = get_logger("engines.verification")


# Actions with a large blast radius: always escalate regardless of score.
# (Policy already gates most of these; this is defense in depth.)
HIGH_BLAST_RADIUS: set[str] = {
    "send_sms_campaign",
    "send_email_campaign",
    "send_cold_outreach",
    "execute_deployment",
    "process_deposit_refund",
    "generate_invoice",
    "place_inventory_order",
    "rollback_to_version",
    "make_outbound_call",
}

# Substrings that mark a workflow as "messaging" — those need a recipient id.
_MESSAGING_MARKERS = ("sms", "email", "outreach", "message", "reminder", "call", "survey", "whatsapp")

_MAX_PARAM_CHARS = 8000


def _env_bool(name: str, default: bool = False) -> bool:
    try:
        val = os.getenv(name)
        if val is None:
            return default
        return val.strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        val = os.getenv(name)
        return float(val) if val is not None else default
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        val = os.getenv(name)
        return int(val) if val is not None else default
    except Exception:
        return default


def _risk_level(workflow: str) -> str:
    """Best-effort risk level for a workflow via the policy engine."""
    try:
        from backend.engines.policy_engine import policy
        return policy.risk_level(workflow) or "medium"
    except Exception:
        return "medium"


def _is_known_workflow(workflow: str) -> bool:
    """Return True if the workflow is present in the policy table."""
    try:
        from backend.engines.policy_engine import POLICIES
        return workflow in POLICIES
    except Exception:
        # If we can't tell, don't punish — treat as known.
        return True


async def _llm_judge(business_id: str, workflow: str, parameters: dict, reason: str):
    """
    LLM-as-judge (optional). Returns (score|None, reason_str).
    Any failure returns (None, "") so the caller ignores the judge (fail open).
    """
    try:
        from agents.base_agent import BaseAgent
        llm = BaseAgent._build_dept_llm()
        try:
            params_str = json.dumps(parameters, default=str)[:2000]
        except Exception:
            params_str = str(parameters)[:2000]
        prompt = (
            "You are a safety reviewer for an autonomous business operations system. "
            "Rate from 0 to 1 whether the following action is appropriate and safe to "
            "execute automatically for this business, considering the workflow, its "
            "parameters, and the stated reason.\n\n"
            f"WORKFLOW: {workflow}\n"
            f"PARAMETERS: {params_str}\n"
            f"REASON: {reason}\n\n"
            'Return STRICT JSON only: {"score": <0..1 float>, "ok": <true|false>, '
            '"reason": "<short explanation>"}'
        )
        resp = await llm.ainvoke(prompt)
        content = getattr(resp, "content", resp)
        if isinstance(content, list):
            content = "".join(
                (b.get("text", "") if isinstance(b, dict) else str(b)) for b in content
            )
        content = str(content or "")
        import re
        m = re.search(r"\{.*\}", content, re.S)
        data = json.loads(m.group(0)) if m else {}
        score = data.get("score")
        ok = data.get("ok")
        jr = str(data.get("reason", ""))[:120]
        if score is None and ok is not None:
            score = 1.0 if ok else 0.0
        return (float(score) if score is not None else None), jr
    except Exception:
        return None, ""


async def _judge_consistent(business_id: str, workflow: str, parameters: dict, reason: str, risk: str):
    """
    LLM-as-judge with SELF-CONSISTENCY for risky actions.

    For high/critical-risk actions the judge is sampled VERIFY_CONSISTENCY_SAMPLES
    times and the samples are checked for agreement relative to the escalate
    threshold. Low/medium-risk actions keep the single-call behavior (to control
    cost).

    Returns (blended_score|None, reasons_list). The score is folded into the
    overall score by the caller via min(). If the caller sees "judge_disagreement"
    or "judge_low" in reasons it must force-escalate. Any failure returns
    (None, []) so the caller ignores the judge entirely (fail open).
    """
    reasons: list[str] = []
    try:
        threshold = _env_float("VERIFY_ESCALATE_THRESHOLD", 0.5)
        samples_n = _env_int("VERIFY_CONSISTENCY_SAMPLES", 3)
        risky = str(risk or "").strip().lower() in ("high", "critical")

        # Single-sample path: low/medium risk, or sampling disabled.
        if not (risky and samples_n > 1):
            score, jr = await _llm_judge(business_id, workflow, parameters, reason)
            if score is not None:
                reasons.append(f"llm_judge:{jr}"[:120])
            return score, reasons

        # Multi-sample path: sample the judge N times (sequentially, so mocked
        # side-effect ordering is deterministic).
        scores: list[float] = []
        last_reason = ""
        for _ in range(samples_n):
            s, jr = await _llm_judge(business_id, workflow, parameters, reason)
            if s is not None:
                scores.append(s)
                last_reason = jr

        if not scores:
            return None, reasons

        smin, smax = min(scores), max(scores)
        mean = sum(scores) / len(scores)

        # Blend the MEAN into the overall score (via caller's min()).
        if smin < threshold < smax:
            # Samples straddle the threshold: some safe, some unsafe.
            reasons.append("judge_disagreement")
        elif smin < 0.15:
            # At least one sample is very-low-confidence.
            reasons.append("judge_low")
        else:
            # All samples agree it's safe.
            reasons.append(f"llm_judge:{last_reason}"[:120])
        return mean, reasons
    except Exception:
        return None, reasons


def _looks_like_test_id(value) -> bool:
    """
    True when an id looks like a test/dummy/placeholder value and should be
    SKIPPED by the grounding check (fail open — never penalize dummy ids).

    Rules: skip when empty, starts with "test", is all zeros, contains
    "0000000000", or does not look like a real UUID (short: len < 20 after
    removing dashes, or contains non-hex characters).
    """
    try:
        s = str(value).strip()
        if not s:
            return True
        low = s.lower()
        if low.startswith("test"):
            return True
        if "0000000000" in s:
            return True
        stripped = s.replace("-", "")
        if stripped and set(stripped) <= {"0"}:
            return True
        # Real ids are UUID-ish: 32+ hex chars (dashes ignored).
        if len(stripped) < 20:
            return True
        if not all(c in "0123456789abcdefABCDEF" for c in stripped):
            return True
        return False
    except Exception:
        return True


async def _grounding_check(business_id: str, parameters: dict):
    """
    GROUNDING CHECK — verify referenced entity ids are real, not hallucinated.

    For any real-looking customer_id / appointment_id / lead_id in the params,
    query the matching Supabase table by id. If the id is provided but NOT found
    -> ok=False with a reason like "ungrounded_customer_id". Dummy/test ids are
    skipped, and any DB error is treated as ok (fail open — never penalize on an
    internal error).

    Returns (ok: bool, reasons: list[str]).
    """
    reasons: list[str] = []
    try:
        if not isinstance(parameters, dict):
            return True, reasons

        id_tables = {
            "customer_id": "customers",
            "appointment_id": "appointments",
            "lead_id": "leads",
        }

        sb = None
        for key, table in id_tables.items():
            val = parameters.get(key)
            if not val:
                continue
            if _looks_like_test_id(val):
                continue
            try:
                if sb is None:
                    from backend.memory.supabase_client import get_supabase
                    sb = get_supabase()
                rows = sb.table(table).select("id").eq("id", val).limit(1).execute().data
                if not rows:
                    reasons.append(f"ungrounded_{key}")
            except Exception:
                # DB/import error — fail open, don't penalize.
                continue

        return (len(reasons) == 0), reasons
    except Exception:
        return True, reasons


async def evaluate_action(business_id: str, workflow: str, parameters: dict, reason: str = "") -> dict:
    """
    Score an autonomous action before it fires. See module docstring for contract.
    """
    fail_closed = _env_bool("VERIFY_FAIL_CLOSED", False)
    try:
        parameters = parameters if isinstance(parameters, dict) else {}
        reasons: list[str] = []
        score = 1.0
        force_escalate = False

        wf = (workflow or "").strip()

        # ── 1. RULE CHECKS (cheap, deterministic, always run) ────────────
        if not wf:
            reasons.append("empty_workflow")
            force_escalate = True
        elif not _is_known_workflow(wf):
            reasons.append("unknown_workflow")
            force_escalate = True

        # Messaging workflows should carry an obvious recipient id.
        if wf and any(marker in wf.lower() for marker in _MESSAGING_MARKERS):
            has_recipient = any(parameters.get(k) for k in ("customer_id", "phone", "email"))
            if not has_recipient:
                reasons.append("missing_recipient_id")
                score = min(score, 0.6)

        # High-blast-radius actions always escalate.
        if wf in HIGH_BLAST_RADIUS:
            reasons.append("high_blast_radius")
            force_escalate = True

        # Sanity: absurdly large parameter payloads are suspicious.
        try:
            serialized = json.dumps(parameters, default=str)
        except Exception:
            serialized = str(parameters)
        if len(serialized) > _MAX_PARAM_CHARS:
            reasons.append("oversized_parameters")
            force_escalate = True

        # ── 2. GRADUATED AUTONOMY (optional) ─────────────────────────────
        try:
            from backend.engines.autonomy_governor import assess
            gov = assess(business_id, wf, _risk_level(wf))
            if isinstance(gov, dict):
                if not gov.get("allow_auto", True):
                    force_escalate = True
                    reasons.append(f"governor_blocked:{gov.get('reason', 'not_allowed')}"[:100])
                reliability = gov.get("reliability")
                if isinstance(reliability, (int, float)):
                    score = min(score, float(reliability))
        except Exception:
            # Governor not present / errored — skip gracefully.
            pass

        # ── 3. GROUNDING CHECK (optional, on by default) ─────────────────
        # Verify any referenced entity ids actually exist (anti-hallucination).
        if _env_bool("VERIFY_GROUNDING", True):
            grounded, ground_reasons = await _grounding_check(business_id, parameters)
            if not grounded:
                force_escalate = True
                reasons.extend(ground_reasons)

        # ── 4. LLM-AS-JUDGE + SELF-CONSISTENCY (optional, off by default) ─
        if os.getenv("OPENAI_API_KEY") and _env_bool("VERIFY_LLM_JUDGE", True):
            judge_score, judge_reasons = await _judge_consistent(
                business_id, wf, parameters, reason, _risk_level(wf)
            )
            if judge_score is not None:
                score = min(score, judge_score)
            for jr in judge_reasons:
                reasons.append(jr)
            # Self-consistency low confidence -> force escalate.
            if any(r in ("judge_disagreement", "judge_low") for r in judge_reasons):
                force_escalate = True

        # ── Final verdict ────────────────────────────────────────────────
        threshold = _env_float("VERIFY_ESCALATE_THRESHOLD", 0.5)
        score = max(0.0, min(1.0, float(score)))
        if score < 0.15:
            verdict = "block"
        elif force_escalate or score < threshold:
            verdict = "escalate"
        else:
            verdict = "allow"

        return {
            "approved": verdict == "allow",
            "score": round(score, 4),
            "verdict": verdict,
            "reasons": reasons or ["ok"],
        }
    except Exception as e:
        # Should be unreachable given the inner guards, but stay safe.
        try:
            log_event(_log, "verify.error", workflow=workflow, error=str(e))
        except Exception:
            pass
        if fail_closed:
            return {
                "approved": False,
                "score": 0.0,
                "verdict": "escalate",
                "reasons": ["verify_error_failclosed"],
            }
        return {
            "approved": True,
            "score": 1.0,
            "verdict": "allow",
            "reasons": ["verify_error_failopen"],
        }
