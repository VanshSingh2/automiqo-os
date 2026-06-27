"""Engineering Manager — coordinates developer agents."""
import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.memory.supabase_client import get_supabase


class EngineeringManager:
    def __init__(self, business_id: UUID):
        self.business_id = business_id
        self.llm = self._build_dept_llm()

    async def run(self, task: str) -> dict:
        """Coordinate developer agents for a given engineering task."""
        messages = [
            SystemMessage(content="You are the Engineering Manager. You coordinate backend, frontend, API, database, and integration developer agents. Break down engineering tasks and delegate."),
            HumanMessage(content=task),
        ]
        response = await self.llm.ainvoke(messages)
        return {"status": "ok", "summary": response.content, "next_actions": []}
