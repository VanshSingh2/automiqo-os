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
        ctx = context or {}
        bid = str(self.business_id)
        sb = get_supabase()

        # Detect if this is a scrape/pipeline request
        q_lower = question.lower()
        is_pipeline = any(w in q_lower for w in ["find", "scrape", "discover", "get leads", "lead gen", "prospect"])

        pipeline_result = {}
        if is_pipeline:
            from backend.integrations.lead_pipeline import run_pipeline
            pipeline_result = await run_pipeline(
                business_id=bid,
                query=ctx.get("query", ctx.get("industry", "med spa")),
                location=ctx.get("location", "New Jersey"),
                industry=ctx.get("industry", "med spa"),
                count=int(ctx.get("count", 30)),
                enrich=True,
                min_score=40,
            )

        # Get current pipeline stats
        try:
            from backend.integrations.lead_pipeline import get_pipeline_stats
            stats = await get_pipeline_stats(bid)
        except Exception:
            leads = sb.table("leads").select("id,status,score,has_booking_system,email").eq("business_id", bid).execute().data or []
            stats = {
                "total": len(leads),
                "new": sum(1 for l in leads if l.get("status") == "new"),
                "high_score": sum(1 for l in leads if (l.get("score") or 0) >= 70),
                "with_email": sum(1 for l in leads if l.get("email")),
                "no_booking_system": sum(1 for l in leads if not l.get("has_booking_system")),
            }

        state = {**stats, **pipeline_result, **ctx}

        try:
            prompt = self._load_prompt("managers/cmo/lead_manager")
        except Exception:
            prompt = "You are the Lead Manager. Run discovery, enrichment, scoring and outreach for leads. Respond with JSON: {status, summary, metrics, recommendations}."

        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
