import os
import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase

LEAD_GEN_KEYWORDS = [
    "find leads", "find businesses", "scrape leads", "get leads", "discover leads",
    "lead gen", "lead generation", "prospect", "find prospects",
    "find med spas", "find gyms", "find salons", "find dentists", "find spas",
    "find", "scrape", "discover",
]

INDUSTRY_MAP = {
    "medspa": "medspa", "med spa": "medspa", "medical spa": "medspa",
    "gym": "gym", "fitness": "gym", "yoga": "gym",
    "salon": "salon", "hair": "salon", "nail": "salon", "barber": "salon",
    "dental": "dental", "dentist": "dental",
    "wellness": "wellness", "massage": "wellness", "chiropractic": "wellness",
}


class LeadManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    def _detect_industry(self, question: str) -> str:
        q_lower = question.lower()
        for keyword, industry in INDUSTRY_MAP.items():
            if keyword in q_lower:
                return industry
        return "medspa"

    async def run_lead_pipeline(self, industry: str, locations: list[str] = None,
                                limit_per_location: int = 20, include_social: bool = False) -> dict:
        """Run the full Lead Intelligence Pipeline (v2 — Serper + Scrapling + Crawl4AI + Social)."""
        from backend.integrations.lead_intelligence import run_full_pipeline
        return await run_full_pipeline(
            business_id=self.business_id,
            industry=industry,
            locations=locations,
            limit_per_location=limit_per_location,
            include_social=include_social,
        )

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        bid = str(self.business_id)
        sb = get_supabase()
        q_lower = question.lower()

        # Detect lead generation intent
        is_lead_gen = any(w in q_lower for w in LEAD_GEN_KEYWORDS)
        is_social_lead_gen = any(w in q_lower for w in [
            "twitter", "reddit", "instagram", "social media", "social leads",
            "find on social", "social scraping", "agent reach", "agent-reach",
        ])
        pipeline_result = {}

        if is_social_lead_gen:
            from backend.integrations.social_lead_pipeline import run_social_lead_pipeline
            industry = ctx.get("industry") or self._detect_industry(question)
            platforms = ctx.get("platforms")
            pipeline_result = await run_social_lead_pipeline(
                business_id=self.business_id,
                industry=industry,
                platforms=platforms,
                limit_per_platform=int(ctx.get("limit_per_platform", 30)),
            )
        elif is_lead_gen:
            industry = ctx.get("industry") or self._detect_industry(question)
            locations = ctx.get("locations")
            limit = int(ctx.get("limit_per_location", ctx.get("count", 20)))
            include_social = ctx.get("include_social", False)
            pipeline_result = await self.run_lead_pipeline(
                industry=industry,
                locations=locations,
                limit_per_location=limit,
                include_social=include_social,
            )

        # Get pipeline stats
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
            prompt = "You are the Lead Intelligence Manager. Run discovery, enrichment, scoring and outreach for leads. Respond with JSON: {status, summary, metrics, recommendations}."

        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}

        if pipeline_result.get("pipeline_complete"):
            seg = pipeline_result.get("segments", {})
            result.recommendations = [
                f"Start outreach with {seg.get('tier_a_count', 0)} Tier A leads",
                f"{seg.get('no_booking_system', 0)} businesses have NO online booking — highest conversion probability",
                f"Total pipeline: {pipeline_result.get('total_discovered', 0)} found, {pipeline_result.get('total_saved', 0)} saved to CRM",
            ]

        return result
