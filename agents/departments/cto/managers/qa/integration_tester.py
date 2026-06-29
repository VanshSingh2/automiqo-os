"""Integration Tester — validates Twilio, Vapi, Cal.com, Stripe, Supabase, Redis, AI providers."""
import json
import os
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


INTEGRATIONS = [
    ("supabase", "SUPABASE_URL"), ("redis", "REDIS_URL"), ("openai", "OPENAI_API_KEY"),
    ("twilio", "TWILIO_ACCOUNT_SID"), ("vapi", "VAPI_API_KEY"), ("cal_com", "CAL_COM_API_KEY"),
    ("stripe", "STRIPE_SECRET_KEY"), ("serper", "SERPER_API_KEY"), ("resend", "RESEND_API_KEY"),
]


class IntegrationTester(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        # Check which integrations have keys configured
        integration_status = {}
        for name, env_var in INTEGRATIONS:
            val = os.getenv(env_var, "")
            integration_status[name] = "configured" if val and len(val) > 5 else "missing"
        missing = [k for k, v in integration_status.items() if v == "missing"]
        # Quick Supabase connectivity check
        supabase_ok = False
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            sb.table("businesses").select("id").limit(1).execute()
            supabase_ok = True
        except Exception:
            pass
        # Quick Redis check
        redis_ok = False
        try:
            import redis
            r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
            r.ping()
            redis_ok = True
        except Exception:
            pass
        state = {
            "integration_status": integration_status,
            "missing_integrations": missing,
            "supabase_connectivity": supabase_ok,
            "redis_connectivity": redis_ok,
            "critical_missing": [m for m in missing if m in ["supabase", "redis", "openai"]],
        }
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Integration Tester for an AI business OS. "
                "Check all external service integrations. Report missing configs, connectivity failures, and risks. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
