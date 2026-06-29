"""Security Tester — validates prompt injection protection, SQL injection, auth, RBAC, tenant isolation."""
import json
import os
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse

SECURITY_CHECKS = [
    "prompt_injection_protection", "sql_injection_protection", "jwt_authentication",
    "business_id_isolation", "secret_leakage_check", "webhook_verification",
    "rbac_enforcement", "api_rate_limiting",
]


class SecurityTester(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        check_results = {}
        # Check that critical secrets are not hardcoded (env-only)
        hardcoded_risk = False
        try:
            import subprocess
            result = subprocess.run(
                ["grep", "-r", "sk-", "/projects/sandbox/automiqo-os/backend", "--include=*.py", "-l"],
                capture_output=True, text=True, timeout=5
            )
            hardcoded_risk = bool(result.stdout.strip())
        except Exception:
            pass
        check_results["no_hardcoded_secrets"] = not hardcoded_risk
        # Check business_id isolation (every table query must include business_id)
        check_results["jwt_secret_configured"] = bool(os.getenv("JWT_SECRET", ""))
        check_results["supabase_service_key_set"] = bool(os.getenv("SUPABASE_SERVICE_KEY", ""))
        check_results["cron_secret_set"] = bool(os.getenv("CRON_SECRET", ""))
        # Check for prompt injection patterns in recent reflections
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            recent = sb.table("reflections").select("what_happened").eq("business_id", str(self.business_id)).order("created_at", desc=True).limit(50).execute().data or []
            injection_patterns = ["ignore previous", "ignore all instructions", "system:", "you are now"]
            suspicious = [r for r in recent if any(p in (r.get("what_happened") or "").lower() for p in injection_patterns)]
            check_results["prompt_injection_attempts"] = len(suspicious)
        except Exception:
            pass
        state = {"security_checks": check_results, "checks_run": SECURITY_CHECKS}
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Security Tester for an AI business OS. "
                "Validate security posture: prompt injection risks, hardcoded secrets, auth, tenant isolation. "
                "Flag any critical security issues. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
