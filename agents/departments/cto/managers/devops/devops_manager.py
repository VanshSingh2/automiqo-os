"""
DevOps Manager — deployment, backup, rollback, infrastructure monitoring.
Queries real task history, Redis queue depth, and coordinates DevOps sub-agents.
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


class DevOpsManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        day_ago  = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Deployment/backup history from tasks
        deployments = sb.table("tasks").select("workflow,status,created_at,error")\
            .eq("business_id", bid).in_("workflow", ["execute_deployment","run_daily_backup","rollback_to_version","monitor_vps_health"])\
            .gte("created_at", week_ago).order("created_at", desc=True).limit(20).execute().data or []

        last_backup = next((t for t in deployments if t["workflow"] == "run_daily_backup" and t["status"] == "completed"), None)
        last_deploy = next((t for t in deployments if t["workflow"] == "execute_deployment"), None)
        failed_deploys = [t for t in deployments if t["workflow"] == "execute_deployment" and t["status"] == "failed"]

        # Redis queue depth
        redis_info = {}
        try:
            import redis as redis_lib
            r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), socket_timeout=2)
            redis_info = {
                "tasks_high_queue":   r.llen("tasks:high"),
                "tasks_normal_queue": r.llen("tasks:normal"),
                "events_queue":       r.llen("events:queue"),
                "redis_connected":    True,
            }
        except Exception:
            redis_info = {"redis_connected": False}

        # Pending tasks (potential queue bloat)
        pending = sb.table("tasks").select("id,workflow,created_at")\
            .eq("business_id", bid).eq("status", "pending").execute().data or []
        stuck = [t for t in pending if t.get("created_at","") < day_ago]

        state = {
            **(context or {}),
            "last_backup_at":     last_backup["created_at"] if last_backup else "never",
            "last_deploy_at":     last_deploy["created_at"] if last_deploy else "never",
            "failed_deployments": len(failed_deploys),
            "pending_tasks":      len(pending),
            "stuck_tasks_24h":    len(stuck),
            "stuck_workflows":    [t["workflow"] for t in stuck[:5]],
            **redis_info,
        }

        # Run sub-agents in parallel
        sub_reports = await self._run_sub_agents(question, state, stuck)
        state["sub_agent_reports"] = sub_reports

        try:
            prompt = self._load_prompt("cto/devops_manager")
        except Exception:
            prompt = (
                "You are the DevOps Manager for {business_name}. "
                "Manage Docker deployments, daily backups, rollbacks, Redis queue, and VPS health. "
                "Flag stuck tasks, missing backups, and deployment failures immediately. "
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

    async def _run_sub_agents(self, question: str, state: dict, stuck_tasks: list) -> dict:
        from agents.departments.cto.managers.devops.agents.backup_agent import BackupAgent
        from agents.departments.cto.managers.devops.agents.infrastructure_monitor_agent import InfrastructureMonitorAgent
        from agents.departments.cto.managers.devops.agents.deployment_agent import DeploymentAgent
        from agents.departments.cto.managers.devops.agents.rollback_agent import RollbackAgent

        reports = {}
        async def _safe(name, coro):
            try:
                r = await coro
                reports[name] = r.summary if hasattr(r, "summary") else str(r)
            except Exception as e:
                reports[name] = f"skipped: {e}"

        tasks = [
            _safe("backup",    BackupAgent(self.business_id).run(
                f"Backup status: last_backup={state.get('last_backup_at','never')}. Assess backup health and recommend actions.",
                state
            )),
            _safe("infra",     InfrastructureMonitorAgent(self.business_id).run(
                f"Infrastructure check: redis={state.get('redis_connected')}, queues={state.get('tasks_high_queue',0)}+{state.get('tasks_normal_queue',0)}, stuck={state.get('stuck_tasks_24h',0)}",
                state
            )),
        ]
        if any(w in question.lower() for w in ["deploy","deployment","release","push"]):
            tasks.append(_safe("deployment", DeploymentAgent(self.business_id).run(question, state)))
        if any(w in question.lower() for w in ["rollback","revert","undo","broken"]):
            tasks.append(_safe("rollback", RollbackAgent(self.business_id).run(question, state)))

        await asyncio.gather(*tasks)
        return reports
