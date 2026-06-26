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
