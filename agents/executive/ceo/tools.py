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

    @tool
    async def ask_cmo(question: str) -> dict:
        """Ask the CMO about campaigns, leads, and marketing performance."""
        from agents.departments.cmo.agent import CMOAgent
        agent = CMOAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def ask_cfo(question: str) -> dict:
        """Ask the CFO about revenue trends, financial reports, and forecasts."""
        from agents.departments.cfo.agent import CFOAgent
        agent = CFOAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def ask_cto(question: str) -> dict:
        """Ask the CTO about platform health, workflow failures, and system reliability."""
        from agents.departments.cto.agent import CTOAgent
        agent = CTOAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def ask_chief_of_staff(question: str) -> dict:
        """Ask Chief of Staff about active tasks, conflicts, and coordination issues."""
        from agents.executive.chief_of_staff.agent import ChiefOfStaffAgent
        agent = ChiefOfStaffAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def ask_learning_director(question: str) -> dict:
        """Ask Learning Director about mistakes, knowledge gaps, and improvement opportunities."""
        from agents.departments.learning.agent import LearningDirectorAgent
        agent = LearningDirectorAgent(business_id)
        resp = await agent.run(question)
        return {"summary": resp.summary, "metrics": resp.metrics}

    @tool
    async def create_action_plan(goal: str, steps: list) -> dict:
        """Break an owner request into a numbered action plan and save it as a task sequence.
        steps is a list of dicts: [{department, action, workflow, parameters}]
        """
        from backend.memory.supabase_client import get_supabase
        from datetime import datetime, timezone
        sb = get_supabase()
        plan_id = None
        tasks_created = []
        for i, step in enumerate(steps):
            result = sb.table("tasks").insert({
                "business_id": str(business_id),
                "created_by": "ceo",
                "workflow": step.get("workflow", ""),
                "parameters": {**step.get("parameters", {}), "goal": goal, "step": i + 1},
                "priority": "high" if i == 0 else "normal",
                "status": "queued",
            }).execute()
            if result.data:
                tasks_created.append(result.data[0]["id"])
        return {"plan_goal": goal, "steps_queued": len(tasks_created), "task_ids": tasks_created}

    @tool
    async def assign_task_to_manager(department: str, task: str, workflow: str, parameters: dict = {}) -> dict:
        """Delegate a specific task to a department manager via the dispatcher.
        department: coo|cro|cmo|cfo|cto|customer_success|learning
        workflow: n8n workflow name to trigger
        """
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        result = sb.table("tasks").insert({
            "business_id": str(business_id),
            "created_by": f"ceo→{department}",
            "workflow": workflow,
            "parameters": {**parameters, "task_description": task},
            "priority": "high",
            "status": "queued",
        }).execute()
        task_id = result.data[0]["id"] if result.data else None
        # Also enqueue to Redis for immediate execution
        try:
            from backend.dispatcher.queue import enqueue_task
            await enqueue_task({
                "task_id": str(task_id),
                "business_id": str(business_id),
                "workflow": workflow,
                "parameters": parameters,
                "priority": "high",
            })
        except Exception:
            pass
        return {"task_id": str(task_id), "department": department, "workflow": workflow, "queued": True}

    @tool
    async def check_task_status(task_id: str = "", workflow: str = "") -> dict:
        """Check progress of a running task. Pass task_id or workflow name."""
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        q = sb.table("tasks").select("id,workflow,status,result,error,created_at,completed_at") \
            .eq("business_id", str(business_id))
        if task_id:
            q = q.eq("id", task_id)
        elif workflow:
            q = q.eq("workflow", workflow).order("created_at", desc=True).limit(5)
        else:
            q = q.in_("status", ["queued", "running"]).order("created_at", desc=True).limit(10)
        tasks = q.execute().data or []
        return {"tasks": tasks, "count": len(tasks)}

    @tool
    async def dispatch_workflow_directly(workflow: str, parameters: dict = {}, priority: str = "high") -> dict:
        """Immediately dispatch an n8n workflow without creating a full plan.
        Use for single urgent actions: send SMS, book appointment, scrape leads, etc.
        """
        from backend.memory.supabase_client import get_supabase
        from backend.dispatcher.queue import enqueue_task
        sb = get_supabase()
        result = sb.table("tasks").insert({
            "business_id": str(business_id),
            "created_by": "ceo_direct",
            "workflow": workflow,
            "parameters": parameters,
            "priority": priority,
            "status": "queued",
        }).execute()
        task_id = result.data[0]["id"] if result.data else "unknown"
        await enqueue_task({
            "task_id": str(task_id),
            "business_id": str(business_id),
            "workflow": workflow,
            "parameters": parameters,
            "priority": priority,
        })
        return {"dispatched": True, "task_id": str(task_id), "workflow": workflow}

    @tool
    async def scrape_leads(query: str, location: str, count: int = 50, industry: str = "med spa") -> dict:
        """Scrape business leads from Google Maps for a given query and location.
        Delegates to CMO Lead Manager which runs the scrape_google_maps_leads workflow.
        Example: scrape_leads('med spa', 'New Jersey', 50)
        """
        from agents.departments.cmo.managers.lead_manager import LeadManager
        agent = LeadManager(business_id)
        resp = await agent.run(
            f"Scrape {count} {industry} leads in {location}. Query: {query}",
            context={"query": query, "location": location, "count": count, "industry": industry}
        )
        return {"summary": resp.summary, "metrics": resp.metrics}

    return [
        get_business_state, ask_coo, ask_cro, ask_customer_success,
        create_recommendation, ask_cmo, ask_cfo, ask_cto,
        ask_chief_of_staff, ask_learning_director,
        create_action_plan, assign_task_to_manager,
        check_task_status, dispatch_workflow_directly, scrape_leads,
    ]
