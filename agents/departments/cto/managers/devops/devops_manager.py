"""DevOps Manager — deployment, backup, rollback, infra monitoring."""
import os
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage


class DevOpsManager:
    def __init__(self, business_id: UUID):
        self.business_id = business_id
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def run(self, task: str) -> dict:
        messages = [
            SystemMessage(content="You are the DevOps Manager. You manage deployments (Docker Compose), backups (Supabase), rollbacks, and infrastructure monitoring. Ensure zero-downtime deployments."),
            HumanMessage(content=task),
        ]
        response = await self.llm.ainvoke(messages)
        return {"status": "ok", "summary": response.content}
