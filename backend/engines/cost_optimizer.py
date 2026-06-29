"""
Cost Optimizer — optimizes model routing, latency, token usage, and infrastructure cost.
Decides which model to use for each task based on complexity vs cost tradeoff.
"""
import os
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase

# Model cost tiers (USD per 1M tokens)
MODEL_COSTS = {
    "gpt-4.1":       {"input": 2.0,   "output": 8.0,   "quality": 0.95},
    "gpt-4o":        {"input": 2.5,   "output": 10.0,  "quality": 0.90},
    "gpt-4o-mini":   {"input": 0.15,  "output": 0.60,  "quality": 0.75},
    "claude-sonnet": {"input": 3.0,   "output": 15.0,  "quality": 0.95},
    "claude-haiku":  {"input": 0.25,  "output": 1.25,  "quality": 0.70},
}

# Task complexity → model recommendation
TASK_MODEL_MAP = {
    "ceo_response":          "gpt-4.1",
    "dept_agent":            "gpt-4o-mini",
    "manager_agent":         "gpt-4o-mini",
    "strategy_planning":     "gpt-4.1",
    "executive_briefing":    "gpt-4.1",
    "sdr_conversation":      "gpt-4o-mini",
    "lead_scoring":          "gpt-4o-mini",
    "knowledge_gap":         "gpt-4o-mini",
    "prediction":            "gpt-4o-mini",
    "simulation":            "gpt-4o-mini",
    "ai_mentor":             "gpt-4o-mini",
}


class CostOptimizer:
    def recommend_model(self, task_type: str, context_size: int = 0) -> str:
        """Recommend the most cost-effective model for a task."""
        base_model = TASK_MODEL_MAP.get(task_type, "gpt-4o-mini")
        # Downgrade if context is small and task is simple
        if context_size < 500 and task_type not in ("ceo_response", "strategy_planning", "executive_briefing"):
            return "gpt-4o-mini"
        return base_model

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a specific model call."""
        costs = MODEL_COSTS.get(model, MODEL_COSTS["gpt-4o-mini"])
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000

    async def get_weekly_spend_report(self, business_id: str) -> dict:
        """Analyze AI spending patterns and identify optimization opportunities."""
        sb = get_supabase()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        costs = sb.table("ai_costs").select("model,cost_usd,tokens_used,agent_name")\
            .eq("business_id", business_id).gte("created_at", week_ago).execute().data or []

        if not costs:
            return {"total_cost": 0, "by_model": {}, "by_agent": {}, "recommendations": []}

        by_model: dict[str, float] = {}
        by_agent: dict[str, float] = {}
        for c in costs:
            m = c.get("model", "unknown")
            a = c.get("agent_name", "unknown")
            cost = float(c.get("cost_usd") or 0)
            by_model[m] = by_model.get(m, 0) + cost
            by_agent[a] = by_agent.get(a, 0) + cost

        total = sum(by_model.values())
        recommendations = []

        # Flag expensive models for low-complexity tasks
        if by_model.get("gpt-4o", 0) > 1.0:
            recommendations.append("Consider downgrading dept agents from gpt-4o to gpt-4o-mini (saves ~80%)")
        if by_model.get("gpt-4.1", 0) > 2.0:
            recommendations.append("CEO agent spend high — review prompt length and response caching")
        if total > 5.0:
            recommendations.append(f"Total AI spend ${total:.2f}/week is above $5 threshold — review usage")

        return {
            "total_cost_7d": round(total, 4),
            "by_model": {k: round(v, 4) for k, v in sorted(by_model.items(), key=lambda x: -x[1])},
            "by_agent": {k: round(v, 4) for k, v in sorted(by_agent.items(), key=lambda x: -x[1])},
            "most_expensive_model": max(by_model, key=by_model.get) if by_model else None,
            "most_expensive_agent": max(by_agent, key=by_agent.get) if by_agent else None,
            "recommendations": recommendations,
            "projected_monthly": round(total * 4, 2),
        }

    async def log_usage(self, business_id: str, model: str, agent_name: str,
                         input_tokens: int, output_tokens: int) -> None:
        """Log a model usage event for cost tracking."""
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        try:
            sb = get_supabase()
            sb.table("ai_costs").insert({
                "business_id": business_id,
                "model": model,
                "agent_name": agent_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tokens_used": input_tokens + output_tokens,
                "cost_usd": cost,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass


# Singleton
cost_optimizer = CostOptimizer()
