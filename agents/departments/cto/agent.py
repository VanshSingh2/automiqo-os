"""
CTO Agent — monitors platform health, workflow reliability, and system performance.
Coordinates: EngineeringManager, DevOpsManager, SecurityManager, PerformanceManager,
DocumentationManager, QADirector.
"""
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase


class CTOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        day_ago  = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        failed    = sb.table("tasks").select("workflow,error,created_at")\
            .eq("business_id", bid).eq("status", "failed").gte("created_at", week_ago).execute().data or []
        completed = sb.table("tasks").select("id")\
            .eq("business_id", bid).eq("status", "completed").gte("created_at", week_ago).execute().data or []
        pending   = sb.table("tasks").select("id")\
            .eq("business_id", bid).eq("status", "pending").execute().data or []
        total     = (len(failed) + len(completed)) or 1

        # AI cost last 7d
        ai_costs = sb.table("ai_costs").select("cost_usd,model")\
            .eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        total_ai_cost = sum(float(c.get("cost_usd") or 0) for c in ai_costs)

        state = {
            **(context or {}),
            "failed_tasks_7d":       len(failed),
            "completed_tasks_7d":    len(completed),
            "pending_tasks":         len(pending),
            "success_rate":          round(len(completed) / total * 100, 1),
            "top_failing_workflows": list({t.get("workflow","") for t in failed})[:5],
            "ai_cost_7d_usd":        round(total_ai_cost, 4),
        }

        # ── Specialist consultations (built BEFORE messages list) ────────
        q = question.lower()
        consultations = []
        if any(w in q for w in ["slow","query","database","index","performance","latency"]):
            consultations.append({"specialist": "database_optimizer", "task": question})
        if any(w in q for w in ["deploy","docker","vps","server","infrastructure","ci"]):
            consultations.append({"specialist": "devops_automator", "task": question})
        if any(w in q for w in ["incident","outage","down","error","critical","crash"]):
            consultations.append({"specialist": "incident_response_commander", "task": question})
        if any(w in q for w in ["security","vulnerability","breach","credential","leak"]):
            consultations.append({"specialist": "security_architect", "task": question})
        if any(w in q for w in ["compliance","hipaa","gdpr","tcpa","legal","audit"]):
            consultations.append({"specialist": "compliance_auditor", "task": question})

        specialist_block = ""
        if consultations:
            insights = await self.consult_specialists_parallel(consultations)
            specialist_block = "\n\n## Specialist Insights\n" + "\n".join(
                f"### {k.replace('_',' ').title()}\n{v}" for k, v in insights.items()
            )

        # ── Sub-manager parallel run ─────────────────────────────────────
        manager_summaries = await self._run_managers(question, state)

        try:
            prompt = self._load_prompt("cto")
        except Exception:
            prompt = (
                "You are the CTO for {business_name}. Monitor platform health, reliability, and performance. "
                "Coordinate engineering, devops, security, performance, documentation, and QA. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )

        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=(
                f"Data: {json.dumps(state, default=str)}\n\n"
                f"Manager Reports:\n{json.dumps(manager_summaries, default=str)}"
                f"{specialist_block}\n\nQuestion: {question}"
            )),
        ]

        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result

    async def _run_managers(self, question: str, state: dict) -> dict:
        """Run all CTO sub-managers in parallel and collect summaries."""
        import asyncio
        results = {}

        async def _safe(name: str, coro):
            try:
                r = await coro
                results[name] = r.summary if hasattr(r, "summary") else str(r)
            except Exception as e:
                results[name] = f"error: {e}"

        from agents.departments.cto.managers.engineering.engineering_manager import EngineeringManager
        from agents.departments.cto.managers.devops.devops_manager import DevOpsManager
        from agents.departments.cto.managers.security.security_manager import SecurityManager
        from agents.departments.cto.managers.performance.performance_manager import PerformanceManager
        from agents.departments.cto.managers.documentation.documentation_manager import DocumentationManager
        from agents.departments.cto.managers.qa.qa_director import QADirector

        await asyncio.gather(
            _safe("engineering",    EngineeringManager(self.business_id).run(question, state)),
            _safe("devops",         DevOpsManager(self.business_id).run(question, state)),
            _safe("security",       SecurityManager(self.business_id).run(question, state)),
            _safe("performance",    PerformanceManager(self.business_id).run(question, state)),
            _safe("documentation",  DocumentationManager(self.business_id).run(question, state)),
            _safe("qa",             QADirector(self.business_id).run(question, state)),
        )
        return results
