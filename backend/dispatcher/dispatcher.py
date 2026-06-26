import uuid
from shared.schemas import TaskRequest, TaskResult
from backend.memory.supabase_client import get_supabase
from backend.dispatcher.queue import enqueue_task


async def dispatch(req: TaskRequest) -> TaskResult:
    sb = get_supabase()
    task_id = uuid.uuid4()

    sb.table("tasks").insert({
        "id": str(task_id),
        "business_id": str(req.business_id),
        "created_by": req.created_by,
        "workflow": req.workflow,
        "priority": req.priority.value,
        "parameters": req.parameters,
        "status": "pending",
    }).execute()

    await enqueue_task({
        "task_id": str(task_id),
        "business_id": str(req.business_id),
        "workflow": req.workflow,
        "parameters": req.parameters,
        "priority": req.priority.value,
    })

    return TaskResult(task_id=task_id, success=True, message=f"Task {task_id} queued for {req.workflow}")
