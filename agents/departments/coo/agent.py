import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.company import get_company_state


class COOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        state = await get_company_state(self.business_id)
        try:
            prompt = self._load_prompt("coo")
        except Exception:
            prompt = "You are the COO. Monitor operations, appointments, and staff."
        system = prompt.replace("{business_name}", "Your Business") \
                       .replace("{industry}", "service") \
                       .replace("{timezone}", "America/New_York")
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=f"Context: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", ""),
                metrics={**state, **parsed.get("metrics", {})},
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
