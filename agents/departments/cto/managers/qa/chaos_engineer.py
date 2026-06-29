"""Chaos Engineer — simulates Redis down, LLM timeout, queue failure, worker crash scenarios."""
import json
import os
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse

CHAOS_SCENARIOS = [
    {"name": "redis_down", "description": "Redis connection failure — tasks queue blocked"},
    {"name": "llm_timeout", "description": "OpenAI/LLM API timeout — agent responses hang"},
    {"name": "supabase_down", "description": "Supabase unreachable — all data reads fail"},
    {"name": "twilio_failure", "description": "Twilio SMS delivery failure — notifications stop"},
    {"name": "calendar_down", "description": "Cal.com API down — booking confirmations fail"},
    {"name": "worker_crash", "description": "Redis worker loop crash — tasks pile up"},
    {"name": "queue_overflow", "description": "High-priority queue overwhelmed"},
    {"name": "n8n_webhook_timeout", "description": "n8n webhook not responding — tasks fail"},
]


class ChaosEngineer(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        # Check current resilience indicators
        resilience = {}
        try:
            import redis as redis_lib
            r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), socket_timeout=2)
            r.ping()
            resilience["redis_alive"] = True
        except Exception:
            resilience["redis_alive"] = False
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            # Check stuck tasks (pending > 1 hour)
            from datetime import datetime, timezone, timedelta
            one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            stuck = sb.table("tasks").select("id,workflow").eq("business_id", str(self.business_id)).eq("status", "pending").lt("created_at", one_hour_ago).execute().data or []
            resilience["stuck_tasks"] = len(stuck)
            resilience["stuck_workflows"] = [t["workflow"] for t in stuck[:5]]
        except Exception:
            resilience["stuck_tasks"] = "unknown"
        # Check retry configuration
        resilience["retry_configured"] = os.path.exists(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "backend", "dispatcher", "retry.py")
        )
        state = {
            "chaos_scenarios": CHAOS_SCENARIOS,
            "resilience_indicators": resilience,
            "simulation_mode": "analysis_only",
        }
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Chaos Engineer for an AI business OS. "
                "Evaluate system resilience against failure scenarios: Redis down, LLM timeout, queue overflow, worker crash. "
                "Identify single points of failure and missing retry/fallback logic. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
