"""Performance Monitor — tracks runtime, queue depth, AI latency, token usage, CPU/RAM."""
import json
import os
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class PerformanceMonitor(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        metrics = {}
        # Redis queue depth
        try:
            import redis as redis_lib
            r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            metrics["redis_queue_high"] = r.llen("tasks:high")
            metrics["redis_queue_normal"] = r.llen("tasks:normal")
            metrics["redis_connected"] = True
        except Exception:
            metrics["redis_connected"] = False
        # AI costs from Supabase
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            costs = sb.table("ai_costs").select("tokens_used,cost_usd").eq("business_id", str(self.business_id)).gte("created_at", since).execute().data or []
            metrics["ai_tokens_24h"] = sum(c.get("tokens_used", 0) for c in costs)
            metrics["ai_cost_24h_usd"] = round(sum(c.get("cost_usd", 0) for c in costs), 4)
            # Pending tasks (queue depth)
            pending = sb.table("tasks").select("id").eq("business_id", str(self.business_id)).eq("status", "pending").execute().data or []
            metrics["pending_tasks"] = len(pending)
        except Exception as e:
            metrics["db_error"] = str(e)
        # System memory
        try:
            import psutil
            metrics["memory_percent"] = psutil.virtual_memory().percent
            metrics["cpu_percent"] = psutil.cpu_percent(interval=1)
        except Exception:
            pass
        metrics.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Performance Monitor for an AI business OS. "
                "Analyze system health: queue depths, AI costs, memory/CPU, task latency. "
                "Flag any degradation or anomalies. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(metrics, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
