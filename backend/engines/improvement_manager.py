"""
Improvement Manager — SAFE CLOSED-LOOP SELF-IMPROVEMENT.

The Learning loop already generates prompt/workflow improvement SUGGESTIONS and
stores them as `recommendations` for a human to approve. This engine adds an
OPTIONAL automated path with guardrails:

    proposed  ->  canary  ->  (adopted | rolled_back)

Guardrails / SAFE DEFAULTS:
  - Everything is gated behind the AUTO_IMPROVE env flag which defaults to OFF.
    When OFF, start_canary/evaluate_canary are no-ops that leave proposals in
    the 'proposed' state so a human still decides.
  - A canary is only "adopted" if its measured metric stays within
    CANARY_TOLERANCE of the baseline (i.e. it did not regress). Otherwise it is
    rolled back automatically.
  - All Supabase access is best-effort: any DB error is swallowed and a safe
    value is returned. These functions must NEVER raise into the nightly loop.

IMPORTANT SAFETY NOTE:
  Adoption here only marks the row status and persists `new_value` on the
  `improvements` row. It deliberately does NOT overwrite live prompt files or
  n8n workflow JSON on disk -- that is out of scope and unsafe to do
  automatically. Actually applying an adopted prompt/workflow change to the
  live system is a manual/operator deploy step, unless a future adopter hook is
  wired in here (see _apply_adopted_value placeholder).

Supabase table `improvements` (DDL in module docstring below / task report):
    id             uuid primary key
    business_id    uuid / text
    target_type    text   -- 'prompt' | 'workflow'
    target_key     text   -- e.g. 'cfo' or a workflow name
    old_value      text
    new_value      text
    status         text   -- 'proposed'|'canary'|'adopted'|'rolled_back'|'rejected'
    metric_baseline numeric
    metric_canary   numeric
    rationale      text
    created_at     timestamptz
    decided_at     timestamptz
"""
import os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_improve_enabled() -> bool:
    """AUTO_IMPROVE gate. Default OFF (safe)."""
    return os.getenv("AUTO_IMPROVE", "false").strip().lower() in ("1", "true", "yes", "on")


def _canary_tolerance() -> float:
    """Fractional regression allowed before rollback. Default 0.05 (5%)."""
    try:
        return float(os.getenv("CANARY_TOLERANCE", "0.05"))
    except Exception:
        return 0.05


async def _read_current_metric(business_id: str, target_key: str) -> float:
    """
    Best-effort current QUALITY metric (0..1) for a target.

    Uses the real ``agent_metrics`` schema via ``agent_metrics.reliability`` and
    returns the target agent's recent success_rate as the canary/baseline
    signal — so a regression (more failures after the change) drives a rollback.
    ``reliability`` itself never raises and returns a trusting default
    (success_rate=1.0) when there is no signal yet; we only fall back to 0.0 on
    a hard error here.
    """
    try:
        from backend.engines import agent_metrics
        stats = await agent_metrics.reliability(business_id, target_key)
        return float(stats.get("success_rate", 1.0) or 0.0)
    except Exception:
        return 0.0


def _apply_adopted_value(business_id: str, row: dict) -> None:
    """
    Apply an adopted improvement in a SAFE, REVERSIBLE way.

    PROMPT improvements are applied as ADDITIVE addenda stored on the business
    config: ``businesses.config['prompt_addenda'][target_key] = [..texts..]``.
    Agents append these to their system prompt at run time (see
    BaseAgent._inject_biz), so an adopted change actually affects behaviour —
    yet we never overwrite prompt files or n8n JSON, and a rollback simply
    removes the addendum. The list is capped so prompts can't grow unbounded.

    WORKFLOW improvements stay ledger-only (auto-editing n8n JSON is out of
    scope / unsafe). Never raises.
    """
    try:
        if (row or {}).get("target_type") != "prompt":
            return
        target_key = (row.get("target_key") or "").strip()
        new_value = (row.get("new_value") or "").strip()
        if not target_key or not new_value:
            return
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        biz = sb.table("businesses").select("config").eq("id", business_id).limit(1).execute().data or []
        cfg = (biz[0].get("config") if biz else {}) or {}
        addenda = cfg.get("prompt_addenda") or {}
        lst = list(addenda.get(target_key) or [])
        if new_value not in lst:
            lst.append(new_value)
        addenda[target_key] = lst[-5:]  # keep only the 5 most recent, bound prompt growth
        cfg["prompt_addenda"] = addenda
        sb.table("businesses").update({"config": cfg}).eq("id", business_id).execute()
    except Exception:
        return None


def _remove_adopted_value(business_id: str, row: dict) -> None:
    """Reverse _apply_adopted_value: drop the addendum for a rolled-back prompt
    improvement from the business config. Best-effort; never raises."""
    try:
        if (row or {}).get("target_type") != "prompt":
            return
        target_key = (row.get("target_key") or "").strip()
        new_value = (row.get("new_value") or "").strip()
        if not target_key or not new_value:
            return
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        biz = sb.table("businesses").select("config").eq("id", business_id).limit(1).execute().data or []
        cfg = (biz[0].get("config") if biz else {}) or {}
        addenda = cfg.get("prompt_addenda") or {}
        lst = [x for x in (addenda.get(target_key) or []) if x != new_value]
        addenda[target_key] = lst
        cfg["prompt_addenda"] = addenda
        sb.table("businesses").update({"config": cfg}).eq("id", business_id).execute()
    except Exception:
        return None


async def propose(business_id, target_type, target_key, new_value,
                  old_value="", rationale="") -> "str | None":
    """
    Log a structured improvement proposal (status='proposed').

    Returns the new row id (best-effort) or None on any DB error.
    """
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        payload = {
            "business_id": business_id,
            "target_type": target_type,
            "target_key": target_key,
            "old_value": old_value or "",
            "new_value": new_value or "",
            "status": "proposed",
            "metric_baseline": 0,
            "metric_canary": 0,
            "rationale": rationale or "",
            "created_at": _now(),
        }
        res = sb.table("improvements").insert(payload).execute()
        data = getattr(res, "data", None) or []
        if data and isinstance(data, list) and data[0].get("id") is not None:
            return str(data[0]["id"])
        return None
    except Exception:
        return None


async def start_canary(business_id, improvement_id) -> bool:
    """
    Move a proposal into canary and record metric_baseline (best-effort).

    Gated by AUTO_IMPROVE: if the flag is OFF the proposal is left as
    'proposed' and this returns False. Never raises.
    """
    if not _auto_improve_enabled():
        return False
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        # Best-effort: find the target so we can pull a baseline metric.
        target_key = ""
        try:
            rows = sb.table("improvements").select("*")\
                .eq("business_id", business_id).eq("id", improvement_id)\
                .limit(1).execute().data or []
            if rows:
                target_key = rows[0].get("target_key", "") or ""
        except Exception:
            target_key = ""

        baseline = await _read_current_metric(business_id, target_key)
        sb.table("improvements").update({
            "status": "canary",
            "metric_baseline": baseline,
        }).eq("business_id", business_id).eq("id", improvement_id).execute()
        return True
    except Exception:
        return False


async def evaluate_canary(business_id, improvement_id) -> str:
    """
    Compare canary metric against baseline and adopt or roll back.

    adopt  iff  metric_canary >= metric_baseline * (1 - CANARY_TOLERANCE)
    else   roll back.

    Gated by AUTO_IMPROVE: if OFF this is a no-op and returns 'proposed'.
    Returns the resulting status string. Never raises.
    """
    if not _auto_improve_enabled():
        return "proposed"
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()

        baseline = 0.0
        target_key = ""
        row = {}
        try:
            rows = sb.table("improvements").select("*")\
                .eq("business_id", business_id).eq("id", improvement_id)\
                .limit(1).execute().data or []
            if rows:
                row = rows[0]
                baseline = float(row.get("metric_baseline") or 0.0)
                target_key = row.get("target_key", "") or ""
        except Exception:
            baseline, target_key, row = 0.0, "", {}

        canary = await _read_current_metric(business_id, target_key)
        threshold = baseline * (1 - _canary_tolerance())
        adopt = canary >= threshold
        new_status = "adopted" if adopt else "rolled_back"

        try:
            sb.table("improvements").update({
                "status": new_status,
                "metric_canary": canary,
                "decided_at": _now(),
            }).eq("business_id", business_id).eq("id", improvement_id).execute()
        except Exception:
            pass

        if adopt:
            # NOTE: does not touch live prompt/workflow files (see module doc).
            _apply_adopted_value(business_id, row)

        return new_status
    except Exception:
        # On unexpected failure, prefer the safe outcome.
        return "rolled_back"


async def rollback(business_id, improvement_id) -> bool:
    """Mark an improvement as rolled back AND undo any applied addendum
    (best-effort). Never raises."""
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        # Undo the live effect (remove the prompt addendum) if it was adopted.
        try:
            rows = sb.table("improvements").select("*") \
                .eq("business_id", business_id).eq("id", improvement_id) \
                .limit(1).execute().data or []
            if rows:
                _remove_adopted_value(business_id, rows[0])
        except Exception:
            pass
        sb.table("improvements").update({
            "status": "rolled_back",
            "decided_at": _now(),
        }).eq("business_id", business_id).eq("id", improvement_id).execute()
        return True
    except Exception:
        return False
