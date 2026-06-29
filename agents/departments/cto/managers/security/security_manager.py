"""
Security Manager — tenant isolation, credential health, RBAC, prompt injection detection.
Runs real Supabase checks and coordinates security sub-agents.
"""
import json
import asyncio
import os
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from backend.memory.supabase_client import get_supabase

REQUIRED_SECRETS = [
    "OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
    "REDIS_URL", "JWT_SECRET", "CRON_SECRET",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
    "VAPI_API_KEY", "CAL_COM_API_KEY", "STRIPE_SECRET_KEY",
]
INJECTION_PATTERNS = [
    "ignore previous", "ignore all instructions", "you are now",
    "forget your instructions", "system:", "act as", "jailbreak",
    "disregard", "bypass", "override instructions",
]


class SecurityManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # 1. Env var / secret health
        missing_secrets = [k for k in REQUIRED_SECRETS if not os.getenv(k)]
        configured_secrets = len(REQUIRED_SECRETS) - len(missing_secrets)

        # 2. Tenant isolation check — sample each critical table
        isolation_results = {}
        for table in ["customers", "appointments", "tasks", "leads", "calls"]:
            try:
                rows = sb.table(table).select("id,business_id")\
                    .neq("business_id", bid).limit(1).execute().data or []
                isolation_results[table] = "other_tenants_exist" if rows else "isolated"
            except Exception:
                isolation_results[table] = "check_failed"

        # 3. Prompt injection scan in recent reflections
        recent = sb.table("reflections").select("what_happened")\
            .eq("business_id", bid).order("created_at", desc=True).limit(100).execute().data or []
        injection_attempts = [
            r["what_happened"][:120] for r in recent
            if any(p in (r.get("what_happened") or "").lower() for p in INJECTION_PATTERNS)
        ]

        # 4. Hardcoded secret scan (check Python files for raw keys)
        hardcoded_risk = False
        try:
            import subprocess
            res = subprocess.run(
                ["grep", "-r", "--include=*.py", "-l",
                 "-e", "sk-", "-e", "key_live", "-e", "whsec_",
                 "/projects/sandbox/automiqo-os/backend"],
                capture_output=True, text=True, timeout=5
            )
            hardcoded_risk = bool(res.stdout.strip())
        except Exception:
            pass

        # 5. Failed auth attempts
        failed_auth = sb.table("tasks").select("id").eq("business_id", bid)\
            .eq("workflow", "auth_failed").gte("created_at", week_ago).execute().data or []

        state = {
            **(context or {}),
            "missing_secrets":          missing_secrets,
            "configured_secrets":       configured_secrets,
            "total_required_secrets":   len(REQUIRED_SECRETS),
            "tenant_isolation":         isolation_results,
            "prompt_injection_attempts": len(injection_attempts),
            "injection_samples":        injection_attempts[:3],
            "hardcoded_secret_risk":    hardcoded_risk,
            "failed_auth_7d":           len(failed_auth),
            "security_score":           max(0, 100
                - len(missing_secrets) * 10
                - len(injection_attempts) * 5
                - (20 if hardcoded_risk else 0)
                - len(failed_auth) * 2),
        }

        # Sub-agents in parallel
        sub_reports = await self._run_sub_agents(question, state)
        state["sub_agent_reports"] = sub_reports

        try:
            prompt = self._load_prompt("cto/security_manager")
        except Exception:
            prompt = (
                "You are the Security Manager for {business_name}. "
                "Enforce tenant isolation (every query must have business_id), monitor credentials, "
                "detect prompt injection, manage RBAC. Flag all security risks. "
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

    async def _run_sub_agents(self, question: str, state: dict) -> dict:
        from agents.departments.cto.managers.security.agents.tenant_isolation_agent import TenantIsolationAgent
        from agents.departments.cto.managers.security.agents.credential_rotation_agent import CredentialRotationAgent
        from agents.departments.cto.managers.security.agents.security_monitor_agent import SecurityMonitorAgent
        from agents.departments.cto.managers.security.agents.rbac_agent import RBACAgent

        reports = {}
        async def _safe(name, coro):
            try:
                r = await coro
                reports[name] = r.summary if hasattr(r, "summary") else str(r)
            except Exception as e:
                reports[name] = f"skipped: {e}"

        await asyncio.gather(
            _safe("tenant_isolation", TenantIsolationAgent(self.business_id).run(
                f"Verify tenant isolation. Results: {state.get('tenant_isolation',{})}",
                state
            )),
            _safe("credentials", CredentialRotationAgent(self.business_id).run(
                f"Check credential health. Missing secrets: {state.get('missing_secrets',[])}. "
                f"Configured: {state.get('configured_secrets',0)}/{state.get('total_required_secrets',0)}",
                state
            )),
            _safe("monitoring", SecurityMonitorAgent(self.business_id).run(
                f"Security monitor. Injection attempts: {state.get('prompt_injection_attempts',0)}. "
                f"Hardcoded risk: {state.get('hardcoded_secret_risk',False)}. Failed auth: {state.get('failed_auth_7d',0)}",
                state
            )),
            _safe("rbac", RBACAgent(self.business_id).run(question, state)),
        )
        return reports
