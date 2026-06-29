"""
Performance Manager — query latency, token cost, workflow speed, AI spend.
Queries real ai_costs + task timing data, coordinates 4 performance sub-agents.
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


class PerformanceManager(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        day_ago  = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        # AI cost per model
        ai_costs = sb.table("ai_costs").select("model,cost_usd,input_tokens,output_tokens,agent_name")\
            .eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        cost_by_model = {}
        for c in ai_costs:
            m = c.get("model","unknown")
            cost_by_model[m] = cost_by_model.get(m, 0) + float(c.get("cost_usd") or 0)
        total_ai_cost = sum(cost_by_model.values())
        total_tokens  = sum((c.get("input_tokens") or 0) + (c.get("output_tokens") or 0) for c in ai_costs)

        # Task execution timing (slow tasks = workflows taking long)
        completed = sb.table("tasks").select("workflow,created_at,completed_at")\
            .eq("business_id", bid).eq("status","completed")\
            .gte("created_at", week_ago).not_.is_("completed_at","null").execute().data or []
        slow_tasks = []
        for t in completed:
            try:
                from datetime import datetime as dt
                start = dt.fromisoformat(t["created_at"].replace("Z","+00:00"))
                end   = dt.fromisoformat(t["completed_at"].replace("Z","+00:00"))
                secs  = (end - start).total_seconds()
                if secs > 30:
                    slow_tasks.append({"workflow": t["workflow"], "duration_seconds": round(secs,1)})
            except Exception:
                pass
        slow_tasks.sort(key=lambda x: x["duration_seconds"], reverse=True)

        # Redis queue depth as perf indicator
        redis_queue_depth = 0
        try:
            import redis as rl
            r = rl.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), socket_timeout=2)
            redis_queue_depth = r.llen("tasks:high") + r.llen("tasks:normal")
        except Exception:
            pass

        state = {
            **(context or {}),
            "total_ai_cost_7d_usd":  round(total_ai_cost, 4),
            "total_tokens_7d":       total_tokens,
            "cost_by_model":         {k: round(v,4) for k,v in cost_by_model.items()},
            "expensive_model":       max(cost_by_model, key=cost_by_model.get) if cost_by_model else None,
            "tasks_completed_7d":    len(completed),
            "slow_tasks_over30s":    len(slow_tasks),
            "slowest_workflows":     slow_tasks[:5],
            "redis_queue_depth":     redis_queue_depth,
            "perf_score":            max(0, 100
                - min(len(slow_tasks), 10) * 5
                - (20 if total_ai_cost > 10 else 0)
                - min(redis_queue_depth, 5) * 5),
        }

        # Sub-agents in parallel
        sub_reports = await self._run_sub_agents(question, state, slow_tasks)
        state["sub_agent_reports"] = sub_reports

        try:
            prompt = self._load_prompt("cto/performance_manager")
        except Exception:
            prompt = (
                "You are the Performance Manager for {business_name}. "
                "Monitor AI token costs, query latency, workflow execution time, and Redis queue depth. "
                "Flag cost anomalies and slow workflows. Suggest optimisations. "
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

    async def _run_sub_agents(self, question: str, state: dict, slow_tasks: list) -> dict:
        from agents.departments.cto.managers.performance.agents.token_cost_optimizer_agent import TokenCostOptimizerAgent
        from agents.departments.cto.managers.performance.agents.workflow_speed_agent import WorkflowSpeedAgent
        from agents.departments.cto.managers.performance.agents.latency_monitor_agent import LatencyMonitorAgent
        from agents.departments.cto.managers.performance.agents.db_query_optimizer_agent import DBQueryOptimizerAgent

        reports = {}
        async def _safe(name, coro):
            try:
                r = await coro
                reports[name] = r.summary if hasattr(r, "summary") else str(r)
            except Exception as e:
                reports[name] = f"skipped: {e}"

        await asyncio.gather(
            _safe("token_cost", TokenCostOptimizerAgent(self.business_id).run(
                f"AI cost this week: ${state.get('total_ai_cost_7d_usd',0)}. "
                f"Cost by model: {state.get('cost_by_model',{})}. "
                f"Expensive model: {state.get('expensive_model','?')}. Suggest optimisations.",
                state
            )),
            _safe("workflow_speed", WorkflowSpeedAgent(self.business_id).run(
                f"{len(slow_tasks)} workflows took >30s. "
                f"Slowest: {slow_tasks[:3] if slow_tasks else 'none'}. Identify bottlenecks.",
                state
            )),
            _safe("latency", LatencyMonitorAgent(self.business_id).run(
                f"Redis queue depth: {state.get('redis_queue_depth',0)}. "
                f"Tasks completed 7d: {state.get('tasks_completed_7d',0)}. Assess latency health.",
                state
            )),
            _safe("db_optimizer", DBQueryOptimizerAgent(self.business_id).run(question, state)),
        )
        return reports
