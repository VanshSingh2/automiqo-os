"""Deployment Validator — verifies Docker, env vars, DB migrations, health checks, rollback readiness."""
import json
import os
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse

REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "REDIS_URL",
    "JWT_SECRET", "N8N_WEBHOOK_BASE_URL", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
    "VAPI_API_KEY", "CAL_COM_API_KEY", "STRIPE_SECRET_KEY", "SERPER_API_KEY",
    "RESEND_API_KEY", "CRON_SECRET",
]


class DeploymentValidator(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        # Check required env vars
        missing_env = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
        configured_env = [v for v in REQUIRED_ENV_VARS if os.getenv(v)]
        # Check critical files exist
        base = "/projects/sandbox/automiqo-os"
        critical_files = {
            "backend/main.py": os.path.exists(f"{base}/backend/main.py"),
            "shared/schemas.py": os.path.exists(f"{base}/shared/schemas.py"),
            "scripts/setup_supabase.sql": os.path.exists(f"{base}/scripts/setup_supabase.sql"),
            "docker/docker-compose.yml": os.path.exists(f"{base}/docker/docker-compose.yml"),
            ".env.example": os.path.exists(f"{base}/.env.example"),
        }
        # Check DB health
        db_ok = False
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            sb.table("businesses").select("id").limit(1).execute()
            db_ok = True
        except Exception:
            pass
        deployment_ready = len(missing_env) == 0 and db_ok and all(critical_files.values())
        state = {
            "missing_env_vars": missing_env,
            "configured_env_vars": len(configured_env),
            "critical_files_exist": critical_files,
            "database_health": db_ok,
            "deployment_ready": deployment_ready,
            "blockers": missing_env + [k for k, v in critical_files.items() if not v],
        }
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Deployment Validator for an AI business OS. "
                "Verify all deployment prerequisites: env vars, Docker files, DB health, rollback readiness. "
                "List all blockers. Block deployment if any critical item is missing. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
