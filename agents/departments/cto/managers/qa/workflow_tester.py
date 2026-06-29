"""Workflow Tester — validates n8n workflow execution, nodes, retries, and edge cases."""
import json
import os
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class WorkflowTester(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        # Gather workflow health from tasks table
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            tasks = sb.table("tasks").select("workflow,status,created_at").eq("business_id", str(self.business_id)).order("created_at", desc=True).limit(100).execute().data or []
            failed = [t for t in tasks if t.get("status") == "failed"]
            completed = [t for t in tasks if t.get("status") == "completed"]
            pending = [t for t in tasks if t.get("status") == "pending"]
            # Count n8n workflow files
            n8n_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "n8n")
            workflow_count = 0
            if os.path.isdir(n8n_dir):
                for root, dirs, files in os.walk(n8n_dir):
                    workflow_count += len([f for f in files if f.endswith(".json")])
            state = {
                "total_tasks_last_100": len(tasks),
                "failed_tasks": len(failed),
                "completed_tasks": len(completed),
                "pending_tasks": len(pending),
                "success_rate": round(len(completed) / max(len(tasks), 1) * 100, 1),
                "n8n_workflow_count": workflow_count,
                "failed_workflows": list({t["workflow"] for t in failed}),
            }
        except Exception as e:
            state = {"error": str(e)}
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Workflow Tester for an AI business OS. "
                "Analyze n8n workflow execution health. Identify broken workflows, high failure rates, stuck tasks. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
