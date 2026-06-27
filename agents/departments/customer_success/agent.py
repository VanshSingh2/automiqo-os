import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class CustomerSuccessAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        open_complaints = sb.table("calls").select("id, sentiment").eq("business_id", bid).eq("sentiment", "negative").execute().data or []
        all_customers = sb.table("customers").select("id, tags").eq("business_id", bid).execute().data or []
        churn_risk = [c for c in all_customers if "churn_risk" in (c.get("tags") or [])]
        state = {"open_complaints": len(open_complaints), "churn_risk": len(churn_risk)}
        try:
            prompt = self._load_prompt("customer_success_director")
        except Exception:
            prompt = "You are the Customer Success Director. Monitor complaints and churn."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", response.content),
                metrics={**state, **parsed.get("metrics", {})},
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
