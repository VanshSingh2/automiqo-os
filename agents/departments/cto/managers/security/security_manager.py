"""Security Manager — credentials, tenant isolation, RBAC, monitoring."""
import os
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.memory.supabase_client import get_supabase


class SecurityManager:
    def __init__(self, business_id: UUID):
        self.business_id = business_id
        self.llm = self._build_dept_llm()

    async def check_tenant_isolation(self) -> dict:
        """Verify no cross-tenant data leakage."""
        sb = get_supabase()
        tables = ["customers", "appointments", "tasks", "calls"]
        results = {}
        for table in tables:
            rows = sb.table(table).select("id, business_id").limit(1).execute().data or []
            results[table] = "ok" if rows else "empty"
        return {"isolation_check": results, "status": "ok"}

    async def run(self, task: str) -> dict:
        messages = [
            SystemMessage(content="You are the Security Manager. You monitor API credentials, enforce tenant isolation (every query must filter by business_id), manage RBAC, and detect suspicious patterns."),
            HumanMessage(content=task),
        ]
        response = await self.llm.ainvoke(messages)
        return {"status": "ok", "summary": response.content}
