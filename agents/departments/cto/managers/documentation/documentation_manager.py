"""
Documentation Manager — API docs, changelogs, SOPs, onboarding guides.
Scans knowledge base gaps and coordinates documentation sub-agents.
"""
import json
import asyncio
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class DocumentationManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        # Knowledge base health
        knowledge = sb.table("knowledge").select("id,category,title,approved")\
            .eq("business_id", bid).execute().data or []
        approved = [k for k in knowledge if k.get("approved")]
        pending_review = [k for k in knowledge if not k.get("approved")]

        # Knowledge categories present vs expected
        expected_categories = {"faq", "policy", "sop", "pricing", "services", "onboarding"}
        present_categories  = {k.get("category","").lower() for k in knowledge}
        missing_categories  = expected_categories - present_categories

        # Recent deployments needing changelog
        recent_deploys = sb.table("tasks").select("workflow,created_at,result")\
            .eq("business_id", bid).eq("workflow", "execute_deployment")\
            .eq("status", "completed").gte("created_at", month_ago)\
            .order("created_at", desc=True).limit(10).execute().data or []

        # Reflections without documented lessons
        undocumented = sb.table("reflections").select("id,what_happened")\
            .eq("business_id", bid).is_("lesson", "null")\
            .gte("created_at", month_ago).execute().data or []

        state = {
            **(context or {}),
            "knowledge_items_total":    len(knowledge),
            "knowledge_items_approved": len(approved),
            "knowledge_pending_review": len(pending_review),
            "missing_categories":       list(missing_categories),
            "present_categories":       list(present_categories),
            "recent_deployments":       len(recent_deploys),
            "undocumented_reflections": len(undocumented),
            "doc_health_score":         max(0, 100
                - len(missing_categories) * 10
                - len(pending_review) * 2
                - min(len(undocumented), 20) * 2),
        }

        # Sub-agents in parallel
        sub_reports = await self._run_sub_agents(question, state, missing_categories, recent_deploys)
        state["sub_agent_reports"] = sub_reports

        try:
            prompt = self._load_prompt("cto/documentation_manager")
        except Exception:
            prompt = (
                "You are the Documentation Manager for {business_name}. "
                "Maintain knowledge base, API docs, changelogs, SOPs, and onboarding guides. "
                "Flag documentation gaps that could cause operational issues. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )

        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result

    async def _run_sub_agents(self, question: str, state: dict,
                               missing_categories: set, recent_deploys: list) -> dict:
        from agents.departments.cto.managers.documentation.agents.api_docs_agent import APIDocsAgent
        from agents.departments.cto.managers.documentation.agents.changelog_agent import ChangelogAgent
        from agents.departments.cto.managers.documentation.agents.sop_writer_agent import SOPWriterAgent
        from agents.departments.cto.managers.documentation.agents.onboarding_docs_agent import OnboardingDocsAgent

        reports = {}
        async def _safe(name, coro):
            try:
                r = await coro
                reports[name] = r.summary if hasattr(r, "summary") else str(r)
            except Exception as e:
                reports[name] = f"skipped: {e}"

        tasks = [
            _safe("api_docs", APIDocsAgent(self.business_id).run(
                f"Review API documentation gaps. Missing knowledge categories: {list(missing_categories)}. "
                f"Pending review items: {state.get('knowledge_pending_review',0)}. {question}",
                state
            )),
        ]
        if recent_deploys:
            tasks.append(_safe("changelog", ChangelogAgent(self.business_id).run(
                f"Write changelog for {len(recent_deploys)} recent deployments. "
                f"Latest deploy: {recent_deploys[0].get('created_at','?') if recent_deploys else 'none'}",
                state
            )))
        if "sop" in missing_categories or "onboarding" in missing_categories:
            tasks.append(_safe("sop", SOPWriterAgent(self.business_id).run(
                f"Missing SOPs detected: {list(missing_categories)}. Create priority SOP documents.",
                state
            )))
            tasks.append(_safe("onboarding", OnboardingDocsAgent(self.business_id).run(
                "Review and update client onboarding documentation.", state
            )))

        await asyncio.gather(*tasks)
        return reports
