import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class TenantIsolationAgent(BaseAgent):
    ROLE = "Nightly check: verify every Supabase table row has valid business_id. Test RLS policies."

    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        messages = [
            SystemMessage(content=self.ROLE),
            HumanMessage(content=question),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
