import os
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class LearningDirectorAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        reflections = sb.table("reflections").select("what_happened, lesson, mistake").eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        failed_tasks = sb.table("tasks").select("workflow, error").eq("business_id", bid).eq("status", "failed").gte("created_at", week_ago).execute().data or []
        calls = sb.table("calls").select("knowledge_gaps, sentiment").eq("business_id", bid).gte("called_at", week_ago).execute().data or []

        knowledge_gaps = []
        for c in calls:
            gaps = c.get("knowledge_gaps") or []
            knowledge_gaps.extend(gaps)

        state = {
            "reflections_7d": len(reflections),
            "mistakes_7d": len([r for r in reflections if r.get("mistake")]),
            "failed_workflows_7d": len(failed_tasks),
            "knowledge_gaps": list(set(knowledge_gaps))[:10],
            "negative_calls": len([c for c in calls if c.get("sentiment") == "negative"]),
        }
        try:
            prompt = self._load_prompt("learning_director")
        except Exception:
            prompt = "You are the Learning Director. Analyze failures, surface knowledge gaps, drive continuous improvement."
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(status=parsed.get("status", "ok"), metrics=state,
                                 summary=parsed.get("summary", ""), recommendations=parsed.get("recommendations", []))
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
