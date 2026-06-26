import os
import json
import asyncio
import httpx
import redis.asyncio as aioredis

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


async def worker_loop():
    r = await get_redis()
    base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "http://localhost:5678/webhook")

    while True:
        item = await r.blpop(["tasks:high", "tasks:normal"], timeout=5)
        if not item:
            continue
        _, raw = item
        payload = json.loads(raw)
        webhook_url = f"{base_url}/{payload['workflow']}"

        try:
            from backend.dispatcher.retry import retry_with_backoff
            await retry_with_backoff(webhook_url, payload)
        except Exception as e:
            await _mark_failed(payload["task_id"], str(e))


async def _mark_failed(task_id: str, error: str):
    from backend.memory.supabase_client import get_supabase
    get_supabase().table("tasks").update(
        {"status": "failed", "error": error}
    ).eq("id", task_id).execute()
