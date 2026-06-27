import os
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
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

        failed = sb.table("tasks").select("workflow, error, created_at").eq("business_id", bid).eq("status", "failed").gte("created_at", week_ago).execute().data or []
        completed = sb.table("tasks").select("id").eq("business_id", bid).eq("status", "completed").gte("created_at", week_ago).execute().data or []
        total = (len(failed) + len(completed)) or 1

        state = {
            "failed_tasks_7d": len(failed),
            "completed_tasks_7d": len(completed),
            "success_rate": round((len(completed) / total) * 100, 1),
            "top_failing_workflows": list(set(t.get("workflow", "") for t in failed))[:5],
        }
        try:
            prompt = self._load_prompt("cto")
        except Exception:
            prompt = "You are the CTO. Monitor platform health, workflow reliability, and system performance."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}{_specialist_block}\n\nQuestion: {question}"),
        ]

        # Consult relevant specialists based on question keywords
        _q = question.lower()
        _consultations = []
        if any(w in _q for w in ["slow", "query", "database", "index", "performance", "latency"]):
            _consultations.append({"specialist": "database_optimizer", "task": question})
        if any(w in _q for w in ["deploy", "docker", "vps", "server", "infrastructure", "ci"]):
            _consultations.append({"specialist": "devops_automator", "task": question})
        if any(w in _q for w in ["incident", "outage", "down", "error", "critical", "crash"]):
            _consultations.append({"specialist": "incident_response_commander", "task": question})
        if any(w in _q for w in ["security", "vulnerability", "breach", "credential", "leak"]):
            _consultations.append({"specialist": "security_architect", "task": question})
        if any(w in _q for w in ["compliance", "hipaa", "gdpr", "tcpa", "legal", "audit"]):
            _consultations.append({"specialist": "compliance_auditor", "task": question})
        if _consultations:
            _insights = await self.consult_specialists_parallel(_consultations)
            _specialist_block = "\n\n## Specialist Insights\n" + "\n".join(
                f"### {k.replace('_', ' ').title()}\n{v}" for k, v in _insights.items()
            )
        else:
            _specialist_block = ""
                response = await self.llm.ainvoke(messages)
        try:

                            _m=__import__("re").search(r"""", response.content); _c=_m.group(0)[_m.group(0).find("{"): ] if _m else response.content; parsed = json.loads(_c)
            return AgentResponse(status=parsed.get("status", "ok"), metrics=state,
                                 summary=parsed.get("summary", ""), recommendations=parsed.get("recommendations", []))
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
