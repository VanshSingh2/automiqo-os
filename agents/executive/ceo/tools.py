import os
from uuid import UUID
from langchain_core.tools import tool


def make_ceo_tools(business_id: UUID):

    @tool
    async def get_business_state() -> dict:
        """Get current business metrics: revenue, appointments, staff."""
        from backend.memory.company import get_company_state
        return await get_company_state(business_id)

    @tool
    async def ask_coo(question: str) -> dict:
        """Ask the COO about operations, appointments, staff."""
        from agents.departments.coo.agent import COOAgent
        agent = COOAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def ask_cro(question: str) -> dict:
        """Ask the CRO about revenue, dormant customers, memberships."""
        from agents.departments.cro.agent import CROAgent
        agent = CROAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def ask_customer_success(question: str) -> dict:
        """Ask Customer Success about complaints and churn risk."""
        from agents.departments.customer_success.agent import CustomerSuccessAgent
        agent = CustomerSuccessAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def create_recommendation(title: str, description: str, category: str, priority: str = "normal") -> dict:
        """Save a recommendation for owner approval."""
        from backend.memory.supabase_client import get_supabase
        result = get_supabase().table("recommendations").insert({
            "business_id": str(business_id),
            "generated_by": "ceo",
            "category": category,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "pending",
        }).execute()
        return {"saved": True, "id": result.data[0]["id"] if result.data else None}

    return [get_business_state, ask_coo, ask_cro, ask_customer_success, create_recommendation]
