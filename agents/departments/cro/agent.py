import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.customer import get_dormant_customers
from backend.memory.supabase_client import get_supabase


class CROAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        dormant = await get_dormant_customers(self.business_id, inactive_days=30)
        sb = get_supabase()
        all_customers = sb.table("customers").select("id, tags").eq("business_id", str(self.business_id)).execute().data or []
        at_risk = [c for c in all_customers if "churn_risk" in (c.get("tags") or [])]
        state = {"dormant_30d": len(dormant), "churn_risk_count": len(at_risk)}
        try:
            prompt = self._load_prompt("cro")
        except Exception:
            prompt = "You are the CRO. Identify revenue recovery and growth opportunities."
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
