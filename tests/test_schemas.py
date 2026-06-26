import pytest
from uuid import uuid4
from shared.schemas import TaskRequest, TaskResult, AgentResponse, TaskPriority


def test_task_request_defaults():
    req = TaskRequest(
        business_id=uuid4(),
        created_by="coo",
        workflow="book_appointment",
    )
    assert req.priority == TaskPriority.NORMAL
    assert req.parameters == {}


def test_task_result_success():
    r = TaskResult(task_id=uuid4(), success=True, message="done")
    assert r.error is None


def test_agent_response_defaults():
    resp = AgentResponse(status="ok", summary="all good")
    assert resp.tasks_to_dispatch == []
    assert resp.recommendations == []
