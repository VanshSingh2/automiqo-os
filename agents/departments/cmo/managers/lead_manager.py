import os
import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class LeadManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        ctx = context or {}

        is_scrape = any(w in question.lower() for w in ["scrape", "find", "leads", "prospect"])
        task_id = None

        if is_scrape:
            query = ctx.get("query", question)
            location = ctx.get("location", "New Jersey")
            count = ctx.get("count", 50)
            industry = ctx.get("industry", "med spa")

            result = sb.table("tasks").insert({
                "business_id": bid,
                "created_by": "lead_manager",
                "workflow": "scrape_google_maps_leads",
                "parameters": {
                    "query": f"{industry} {query}",
                    "location": location,
                    "count": count,
                    "store_in_supabase": True,
                },
                "priority": "high",
                "status": "queued",
            }).execute()
            task_id = result.data[0]["id"] if result.data else None

            try:
                from backend.dispatcher.queue import enqueue_task
                await enqueue_task({
                    "task_id": str(task_id),
                    "business_id": bid,
                    "workflow": "scrape_google_maps_leads",
                    "parameters": {"query": f"{industry} {query}", "location": location, "count": count},
                    "priority": "high",
                })
            except Exception:
                pass

        # Current leads stats
        try:
            leads = sb.table("leads").select("id,status,score,has_booking_system") \
                .eq("business_id", bid).execute().data or []
        except Exception:
            leads = []

        state = {
            "total_leads": len(leads),
            "new_leads": len([l for l in leads if l.get("status") == "new"]),
            "high_score_leads": len([l for l in leads if (l.get("score") or 0) >= 70]),
            "no_booking_system": len([l for l in leads if not l.get("has_booking_system")]),
            "scrape_queued": task_id is not None,
            "scrape_task_id": str(task_id) if task_id else None,
        }

        try:
            prompt = self._load_prompt("managers/cmo/lead_manager")
        except Exception:
            prompt = "You are the Lead Manager. Manage lead acquisition, scoring, and outreach. Respond with JSON: {status, summary, metrics, recommendations}."

        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
