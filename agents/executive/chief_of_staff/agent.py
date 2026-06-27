import os
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class ChiefOfStaffAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        active_tasks = sb.table("tasks").select("id, workflow, status, priority, created_at") \
            .eq("business_id", bid).in_("status", ["queued", "running"]).execute().data or []
        failed_tasks = sb.table("tasks").select("workflow, error").eq("business_id", bid) \
            .eq("status", "failed").gte("created_at", cutoff).execute().data or []

        # detect duplicate queued workflows
        workflows = [t.get("workflow") for t in active_tasks]
        duplicates = [w for w in set(workflows) if workflows.count(w) > 1]

        state = {
            "active_tasks": len(active_tasks),
            "failed_last_24h": len(failed_tasks),
            "duplicates": duplicates,
            "task_list": active_tasks[:10],
        }
        try:
            prompt = self._load_prompt("chief_of_staff")
        except Exception:
            prompt = "You are the Chief of Staff. Track tasks, detect conflicts, brief the CEO."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("briefing_context", parsed.get("summary", response.content)),
                metrics=state,
                recommendations=parsed.get("conflicts", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
