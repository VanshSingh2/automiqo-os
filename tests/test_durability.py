"""
Durability tests for autonomous execution recovery across restarts.

Verifies backend.dispatcher.queue.recover_pending_tasks re-hydrates the Redis
fast queue from the durable Supabase `tasks` table, and that enqueue routing
still works. Fully offline — Supabase/Redis are patched.
"""
from unittest.mock import AsyncMock, MagicMock, patch


async def test_recover_reenqueues_queued_and_resets_running(make_sb):
    from backend.dispatcher import queue

    sb = make_sb({
        "tasks": [
            {"id": "t1", "business_id": "b", "workflow": "send_reminder_24h",
             "parameters": {}, "priority": "normal", "status": "queued"},
            {"id": "t2", "business_id": "b", "workflow": "send_reminder_24h",
             "parameters": {}, "priority": "high", "status": "running"},
        ]
    })

    enq = AsyncMock()
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=enq):
        count = await queue.recover_pending_tasks()

    # Both tasks re-enqueued.
    assert count == 2
    assert enq.await_count == 2

    # The 'running' task (t2) was reset back to 'queued' before re-enqueue.
    assert sb.queries["tasks"].updated == [{"status": "queued"}]

    # The re-enqueued payloads carry the row fields through.
    enq_ids = {c.args[0]["task_id"] for c in enq.await_args_list}
    assert enq_ids == {"t1", "t2"}


async def test_recover_returns_zero_when_db_errors():
    from backend.dispatcher import queue

    def _boom():
        raise RuntimeError("supabase down")

    with patch("backend.memory.supabase_client.get_supabase", side_effect=_boom):
        # Must not raise; best-effort recovery returns 0.
        count = await queue.recover_pending_tasks()

    assert count == 0


async def test_recover_dedupes_on_task_id(make_sb):
    from backend.dispatcher import queue

    sb = make_sb({
        "tasks": [
            {"id": "dup", "business_id": "b", "workflow": "w",
             "parameters": {}, "priority": "normal", "status": "queued"},
            {"id": "dup", "business_id": "b", "workflow": "w",
             "parameters": {}, "priority": "normal", "status": "queued"},
        ]
    })

    enq = AsyncMock()
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb), \
         patch("backend.dispatcher.queue.enqueue_task", new=enq):
        count = await queue.recover_pending_tasks()

    assert count == 1
    assert enq.await_count == 1


# ── enqueue_task routing regression ─────────────────────────────────────────
async def test_enqueue_high_priority_selects_high_queue():
    from backend.dispatcher import queue

    r = MagicMock()
    r.rpush = AsyncMock()
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(return_value=r)):
        await queue.enqueue_task({"priority": "high", "workflow": "w", "task_id": "t"})

    assert r.rpush.await_args.args[0] == "tasks:high"


async def test_enqueue_normal_priority_selects_normal_queue():
    from backend.dispatcher import queue

    r = MagicMock()
    r.rpush = AsyncMock()
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(return_value=r)):
        await queue.enqueue_task({"priority": "normal", "workflow": "w", "task_id": "t"})

    assert r.rpush.await_args.args[0] == "tasks:normal"
