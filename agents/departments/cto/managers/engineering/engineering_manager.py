"""
Engineering Manager — coordinates 5 developer agents.
Queries failed tasks, pending work, and delegates to the right developer.
"""
import json
import asyncio
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class EngineeringManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Real data: failed tasks, pending tasks, recent errors
        failed = sb.table("tasks").select("workflow,error,parameters,created_at")\
            .eq("business_id", bid).eq("status", "failed")\
            .gte("created_at", week_ago).order("created_at", desc=True).limit(20).execute().data or []
        pending = sb.table("tasks").select("workflow,priority,created_at")\
            .eq("business_id", bid).eq("status", "pending").limit(10).execute().data or []
        ai_costs = sb.table("ai_costs").select("model,cost_usd,agent_name")\
            .eq("business_id", bid).gte("created_at", week_ago).execute().data or []

        # Categorise failures by type
        backend_errors   = [t for t in failed if any(w in (t.get("workflow","")) for w in ["api","backend","lead","pipeline","enrich"])]
        integration_errs = [t for t in failed if any(w in (t.get("workflow","")) for w in ["webhook","sms","cal","stripe","twilio","vapi"])]
        db_errors        = [t for t in failed if any(w in (t.get("error","").lower()) for w in ["supabase","postgres","unique","foreign","null"])]

        state = {
            **(context or {}),
            "failed_tasks_7d":        len(failed),
            "pending_tasks":          len(pending),
            "backend_failures":       len(backend_errors),
            "integration_failures":   len(integration_errs),
            "db_failures":            len(db_errors),
            "top_errors":             list({t.get("error","")[:120] for t in failed if t.get("error")})[:5],
            "top_failing_workflows":  list({t.get("workflow","") for t in failed})[:8],
            "ai_cost_7d_usd":         round(sum(float(c.get("cost_usd") or 0) for c in ai_costs), 4),
            "models_used":            list({c.get("model","") for c in ai_costs}),
        }

        # Run relevant developer sub-agents in parallel
        dev_reports = await self._delegate_to_developers(question, state, backend_errors, integration_errs, db_errors)
        state["developer_reports"] = dev_reports

        try:
            prompt = self._load_prompt("cto/engineering_manager")
        except Exception:
            prompt = (
                "You are the Engineering Manager for {business_name}. "
                "You oversee backend, frontend, API, database, and integration developers. "
                "Analyse failures, delegate fixes, and report engineering health. "
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

    async def _delegate_to_developers(self, question: str, state: dict,
                                       backend_errors, integration_errs, db_errors) -> dict:
        from agents.departments.cto.managers.engineering.developers.backend_developer import BackendDeveloper
        from agents.departments.cto.managers.engineering.developers.api_developer import APIDeveloper
        from agents.departments.cto.managers.engineering.developers.database_developer import DatabaseDeveloper
        from agents.departments.cto.managers.engineering.developers.integration_developer import IntegrationDeveloper
        from agents.departments.cto.managers.engineering.developers.frontend_developer import FrontendDeveloper

        reports = {}

        async def _safe(name, coro):
            try:
                r = await coro
                reports[name] = r.summary if hasattr(r, "summary") else str(r)
            except Exception as e:
                reports[name] = f"skipped: {e}"

        tasks = []
        # Always ask backend dev
        tasks.append(_safe("backend", BackendDeveloper(self.business_id).run(
            f"Review these backend failures and recommend fixes: {[t.get('workflow') for t in backend_errors[:5]]}\n{question}",
            {"errors": [t.get("error","")[:200] for t in backend_errors[:3]]}
        )))
        # DB dev if db errors
        if db_errors:
            tasks.append(_safe("database", DatabaseDeveloper(self.business_id).run(
                f"Review these database errors and suggest schema/query fixes: {[t.get('error','')[:150] for t in db_errors[:3]]}\n{question}",
                state
            )))
        # Integration dev if integration errors
        if integration_errs:
            tasks.append(_safe("integration", IntegrationDeveloper(self.business_id).run(
                f"Review these integration failures and fix webhook/API issues: {[t.get('workflow') for t in integration_errs[:5]]}\n{question}",
                {"errors": [t.get("error","")[:200] for t in integration_errs[:3]]}
            )))
        # API dev if question mentions APIs
        if any(w in question.lower() for w in ["api","endpoint","route","webhook","cal","twilio","stripe"]):
            tasks.append(_safe("api", APIDeveloper(self.business_id).run(question, state)))
        # Frontend dev if question mentions UI
        if any(w in question.lower() for w in ["frontend","ui","dashboard","page","component","next"]):
            tasks.append(_safe("frontend", FrontendDeveloper(self.business_id).run(question, state)))

        await asyncio.gather(*tasks)
        return reports
