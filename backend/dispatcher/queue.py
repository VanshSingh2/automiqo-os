import os
import json
import asyncio
from datetime import datetime, timezone, timedelta

import redis.asyncio as aioredis

from backend.obs import get_logger, log_event

_log = get_logger("dispatcher.queue")
_redis = None


async def get_redis():
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    return _redis


async def enqueue_task(payload: dict) -> None:
    r = await get_redis()
    queue = "tasks:high" if payload.get("priority") == "high" else "tasks:normal"
    await r.rpush(queue, json.dumps(payload))
    log_event(_log, "task.enqueued", business_id=payload.get("business_id"),
              workflow=payload.get("workflow"), queue=queue)


async def recover_pending_tasks() -> int:
    """
    Best-effort startup recovery to make autonomous execution durable across
    restarts.

    The Supabase `tasks` table is the durable source of truth; Redis is only a
    fast, volatile queue. On a restart, tasks that were persisted as
    status='queued' can be lost from the Redis list (never executed), and tasks
    left status='running' are orphaned mid-flight. This re-hydrates the Redis
    queue from Supabase:

      - Rows with status in ('queued','running') created within the last
        RECOVERY_WINDOW_HOURS (default 24), oldest-first, capped at RECOVERY_MAX
        (default 500).
      - Orphaned 'running' rows are reset to 'queued' first so the normal retry
        logic stays consistent, then re-enqueued.
      - De-dupes on task_id via an in-function seen-set.

    Never raises: any failure is logged via obs.log_event and returns 0.
    Returns the number of tasks re-enqueued.
    """
    try:
        window_hours = int(os.getenv("RECOVERY_WINDOW_HOURS", "24"))
        max_rows = int(os.getenv("RECOVERY_MAX", "500"))
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

        # Lazy import so the module (and tests) don't require Supabase at import
        # time; mirrors _mark_failed's import path for patch-ability.
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()

        result = (
            sb.table("tasks")
            .select("id,business_id,workflow,parameters,priority,status,created_at")
            .in_("status", ["queued", "running"])
            .gte("created_at", cutoff)
            .order("created_at", desc=False)
            .limit(max_rows)
            .execute()
        )
        rows = result.data or []

        seen: set = set()
        count = 0
        for row in rows:
            task_id = row.get("id")
            if not task_id or task_id in seen:
                continue
            seen.add(task_id)
            try:
                # Reset orphaned 'running' rows back to 'queued' before re-enqueue
                # so retry logic treats them like a fresh queued task.
                if row.get("status") == "running":
                    try:
                        sb.table("tasks").update({"status": "queued"}).eq("id", task_id).execute()
                    except Exception as e:
                        log_event(_log, "recovery.reset_error", task_id=task_id, error=str(e))

                await enqueue_task({
                    "task_id": task_id,
                    "business_id": row.get("business_id"),
                    "workflow": row.get("workflow"),
                    "parameters": row.get("parameters") or {},
                    "priority": row.get("priority") or "normal",
                })
                count += 1
            except Exception as e:
                log_event(_log, "recovery.enqueue_error", task_id=task_id, error=str(e))

        log_event(_log, "recovery.requeued", count=count)
        return count
    except Exception as e:
        log_event(_log, "recovery.error", error=str(e))
        return 0


async def worker_loop():
    base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "http://localhost:5678/webhook")

    while True:
        # Redis can blip (transient connection error, restart). Never let that
        # crash the worker loop — log, back off briefly, and keep going.
        try:
            r = await get_redis()
            item = await r.blpop(["tasks:high", "tasks:normal"], timeout=5)
        except Exception as e:
            log_event(_log, "worker.redis_error", error=str(e))
            await asyncio.sleep(2)
            continue

        if not item:
            continue
        _, raw = item
        payload = json.loads(raw)
        webhook_url = f"{base_url}/{payload['workflow']}"

        try:
            from backend.dispatcher.retry import retry_with_backoff
            await retry_with_backoff(webhook_url, payload)
        except Exception as e:
            log_event(_log, "task.failed", task_id=payload.get("task_id"),
                      workflow=payload.get("workflow"), error=str(e))
            await _mark_failed(payload["task_id"], str(e))


async def _mark_failed(task_id: str, error: str):
    from backend.memory.supabase_client import get_supabase
    get_supabase().table("tasks").update(
        {"status": "failed", "error": error}
    ).eq("id", task_id).execute()
