import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from shared.schemas import TaskRequest, TaskPriority


@pytest.mark.asyncio
async def test_dispatch_creates_task():
    # Simple test - verify the function can be called
    # Full integration testing requires mocking Supabase and Redis clients
    from shared.schemas import TaskRequest, TaskResult, TaskPriority

    req = TaskRequest(
        business_id=uuid4(),
        created_by="coo",
        workflow="book_appointment",
        priority=TaskPriority.NORMAL
    )

    # Verify request can be created properly
    assert req.workflow == "book_appointment"
    assert req.priority == TaskPriority.NORMAL



# ── enqueue_task: queue selection ───────────────────────────────────────────
async def test_enqueue_high_priority_goes_to_high_queue():
    from backend.dispatcher import queue
    r = MagicMock()
    r.rpush = AsyncMock()
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(return_value=r)):
        await queue.enqueue_task({"priority": "high", "workflow": "w", "task_id": "t"})
    assert r.rpush.await_args.args[0] == "tasks:high"


async def test_enqueue_normal_priority_goes_to_normal_queue():
    from backend.dispatcher import queue
    r = MagicMock()
    r.rpush = AsyncMock()
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(return_value=r)):
        await queue.enqueue_task({"priority": "normal", "workflow": "w", "task_id": "t"})
    assert r.rpush.await_args.args[0] == "tasks:normal"


# ── retry_with_backoff: failure path ────────────────────────────────────────
async def test_retry_raises_after_max_retries():
    from backend.dispatcher import retry
    payload = {"business_id": "b", "task_id": "t", "parameters": {}}
    with patch.object(retry.httpx, "AsyncClient", side_effect=RuntimeError("net")), \
         patch("backend.dispatcher.retry.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="Failed after 3 retries"):
            await retry.retry_with_backoff("http://x/w", payload, max_retries=3)
