import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class ChangelogAgent(BaseAgent):
    ROLE = "Write plain-English changelog after each deployment. Categorize: feature/bugfix/breaking."

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
