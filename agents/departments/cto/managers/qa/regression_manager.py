"""Regression Manager — blocks deployment on critical regressions after any change."""
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class RegressionManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            # Check task success rate trend
            recent_tasks = sb.table("tasks").select("status,workflow,created_at").eq("business_id", str(self.business_id)).gte("created_at", since).execute().data or []
            failed = [t for t in recent_tasks if t["status"] == "failed"]
            completed = [t for t in recent_tasks if t["status"] == "completed"]
            # Check for new failures in reflections
            reflections = sb.table("reflections").select("what_happened,mistake").eq("business_id", str(self.business_id)).eq("mistake", True).gte("created_at", since).execute().data or []
            state = {
                "window_hours": 24,
                "tasks_run": len(recent_tasks),
                "failed": len(failed),
                "completed": len(completed),
                "failure_rate_pct": round(len(failed) / max(len(recent_tasks), 1) * 100, 1),
                "regression_detected": len(failed) / max(len(recent_tasks), 1) > 0.20,
                "mistake_reflections": len(reflections),
                "failed_workflows": list({t["workflow"] for t in failed}),
            }
        except Exception as e:
            state = {"error": str(e), "regression_detected": False}
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Regression Manager for an AI business OS. "
                "Detect regressions in task success rates and AI behavior. "
                "If failure rate > 20% in last 24h, flag as critical regression and block deployment. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
