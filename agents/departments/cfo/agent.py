import os
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class CFOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        appts_week = sb.table("appointments").select("revenue, status").eq("business_id", bid).gte("scheduled_at", week_ago).execute().data or []
        appts_month = sb.table("appointments").select("revenue, status").eq("business_id", bid).gte("scheduled_at", month_ago).execute().data or []

        revenue_week = sum(a.get("revenue") or 0 for a in appts_week if a["status"] == "completed")
        revenue_month = sum(a.get("revenue") or 0 for a in appts_month if a["status"] == "completed")
        state = {
            "revenue_7d": revenue_week,
            "revenue_30d": revenue_month,
            "appts_week": len(appts_week),
            "completed_week": len([a for a in appts_week if a["status"] == "completed"]),
            "no_shows_week": len([a for a in appts_week if a["status"] == "no_show"]),
        }
        try:
            prompt = self._load_prompt("cfo")
        except Exception:
            prompt = "You are the CFO. Analyze revenue, identify trends, flag financial risks."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(status=parsed.get("status", "ok"), metrics=state,
                                 summary=parsed.get("summary", ""), recommendations=parsed.get("recommendations", []))
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
