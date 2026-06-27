import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class CMOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        campaigns = sb.table("campaigns").select("id, name, status, sent_count, response_count, booking_count").eq("business_id", bid).limit(10).execute().data or []
        active = [c for c in campaigns if c["status"] == "running"]
        state = {
            "active_campaigns": len(active),
            "total_campaigns": len(campaigns),
            "total_sent": sum(c.get("sent_count") or 0 for c in campaigns),
            "total_bookings_from_campaigns": sum(c.get("booking_count") or 0 for c in campaigns),
        }
        try:
            prompt = self._load_prompt("cmo")
        except Exception:
            prompt = "You are the CMO. Manage campaigns, content, and lead generation."
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
