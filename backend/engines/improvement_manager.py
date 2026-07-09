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


def _read_current_metric_window_days() -> int:
    """Lookback window (days) for the canary success-rate signal. Default 14."""
    try:
        return int(os.getenv("IMPROVE_METRIC_WINDOW_DAYS", "14"))
    except Exception:
        return 14


# Hardcoded fallback prompt targets used when the prompts/ dir is missing or
# unreadable. These are the real top-level prompt basenames under prompts/.
_FALLBACK_PROMPT_TARGETS = {
    "ceo", "coo", "cro", "cmo", "cfo", "cto",
    "customer_success_director", "learning_director", "chief_of_staff",
}

# Module-level cache for the scanned prompt-target set (populated lazily).
_VALID_PROMPT_TARGETS_CACHE: "set[str] | None" = None


def valid_prompt_targets() -> "set[str]":
    """
    Best-effort set of valid prompt target keys (basenames of *.md files under
    the repo ``prompts/`` directory, recursive, without the ``.md`` suffix).

    The prompt basename is what BaseAgent loads by NAME and what a prompt
    addendum is keyed on, so only these are meaningful prompt targets for an
    adopted improvement. Result is cached in a module global. If the directory
    is missing/unreadable, returns a hardcoded fallback set. Never raises.
    """
    global _VALID_PROMPT_TARGETS_CACHE
    if _VALID_PROMPT_TARGETS_CACHE is not None:
        return set(_VALID_PROMPT_TARGETS_CACHE)
    found: "set[str]" = set()
    try:
        # improvement_manager.py lives at backend/engines/ -> repo root is 2 up.
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        prompts_dir = os.path.join(repo_root, "prompts")
        for dirpath, _dirs, files in os.walk(prompts_dir):
            for fname in files:
                if fname.endswith(".md"):
                    found.add(fname[:-3])
    except Exception:
        found = set()
    if not found:
        found = set(_FALLBACK_PROMPT_TARGETS)
    _VALID_PROMPT_TARGETS_CACHE = set(found)
    return set(found)


def _valid_target(target_type, target_key) -> bool:
    """
    Pure validation helper for a proposed improvement target.

    A ``prompt`` target is only valid if its key is a real prompt basename
    (so an adopted addendum actually reaches an agent). ``workflow`` (and any
    non-prompt) targets are accepted as-is (ledger-only). Never raises.
    """
    try:
        key = (target_key or "").strip()
        if not key:
            return False
        if (target_type or "").strip().lower() == "prompt":
            return key in valid_prompt_targets()
        return True
    except Exception:
        return False


def _normalize_agent(name) -> str:
    """
    Normalize an agent identifier for fuzzy matching between the ``agent_metrics``
    ``agent_name`` (a CLASS name like ``CFOAgent``/``CustomerSuccessAgent``/
    ``LearningDirectorAgent``) and a prompt target key (like ``cfo``).

    Lowercases, strips a trailing ``agent``/``director``/``chatagent`` suffix,
    then strips all non-alphanumerics. Examples:
      ``CFOAgent`` -> ``cfo``
      ``CustomerSuccessAgent`` -> ``customersuccess``
      ``LearningDirectorAgent`` -> ``learning``
    Never raises.
    """
    try:
        import re
        s = (name or "").strip().lower()
        # Strip trailing role suffixes repeatedly so "LearningDirectorAgent"
        # collapses through "learningdirector" down to "learning".
        changed = True
        while changed:
            changed = False
            for suffix in ("chatagent", "agent", "director"):
                # Compare on alnum-normalized boundary to tolerate separators.
                stripped = re.sub(r"[^a-z0-9]", "", s)
                if stripped.endswith(suffix) and stripped != suffix:
                    s = stripped[: -len(suffix)]
                    changed = True
                    break
        return re.sub(r"[^a-z0-9]", "", s)
    except Exception:
        return ""


async def _read_current_metric(business_id: str, target_key: str) -> float:
    """
    Best-effort current QUALITY metric (0..1) for a prompt/agent target.

    The ``agent_metrics`` table stores ``agent_name`` as the agent CLASS name
    (e.g. ``CFOAgent``), while a prompt-targeted improvement carries a prompt
    KEY (e.g. ``cfo``). We therefore scan the business's recent metric rows and
    compute the success_rate over rows whose NORMALIZED agent_name matches the
    normalized ``target_key`` (equal, or one contained in the other).

    Fallbacks (all best-effort, never raise):
      * no matching rows        -> agent_metrics.reliability(...)["success_rate"]
      * any error / no signal   -> 1.0 (neutral, trusting) so a no-signal canary
                                    never forces a rollback of everything.
    """
    try:
        from datetime import timedelta
        from backend.memory.supabase_client import get_supabase

        target_norm = _normalize_agent(target_key)
        window = _read_current_metric_window_days()
        since = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()

        rows = []
        try:
            rows = (
                get_supabase().table("agent_metrics")
                .select("agent_name,success")
                .eq("business_id", str(business_id))
                .gte("created_at", since)
                .execute().data
            ) or []
        except Exception:
            rows = []

        matched = []
        for r in rows:
            an = _normalize_agent(r.get("agent_name"))
            if not an or not target_norm:
                continue
            if an == target_norm or an in target_norm or target_norm in an:
                matched.append(r)

        if matched:
            successes = sum(1 for r in matched if r.get("success"))
            return float(successes / len(matched))

        # No matching rows: fall back to the reliability helper (which also
        # returns a trusting default when there is no signal).
        try:
            from backend.engines import agent_metrics
            stats = await agent_metrics.reliability(business_id, target_key)
            return float(stats.get("success_rate", 1.0) or 1.0)
        except Exception:
            return 1.0
    except Exception:
        # Neutral default so a no-signal canary doesn't force a rollback.
        return 1.0


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
