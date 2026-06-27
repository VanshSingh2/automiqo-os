import os
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage


class InfrastructureMonitorAgent:
    ROLE = "Monitor VPS CPU/RAM/disk. Check Docker containers. Alert if Redis queue > 100 tasks."

    def __init__(self, business_id: UUID):
        self.business_id = business_id
        self.llm = self._build_dept_llm()

    async def run(self, task: str) -> dict:
        messages = [
            SystemMessage(content=self.ROLE),
            HumanMessage(content=task),
        ]
        response = await self.llm.ainvoke(messages)
        return {"status": "ok", "summary": response.content, "agent": self.__class__.__name__}
