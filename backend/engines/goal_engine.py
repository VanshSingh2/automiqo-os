"""
Goal Engine — every department optimizes measurable goals instead of isolated tasks.
Each dept has goals. Every action is evaluated against whether it moves the needle.
"""
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase


DEFAULT_GOALS = {
    "coo": [
        {"metric": "appointment_completion_rate", "target": 0.85, "unit": "pct", "period": "daily"},
        {"metric": "no_show_rate", "target": 0.10, "unit": "pct", "period": "daily", "lower_is_better": True},
        {"metric": "staff_utilization", "target": 0.80, "unit": "pct", "period": "daily"},
    ],
    "cmo": [
        {"metric": "leads_discovered_weekly", "target": 50, "unit": "count", "period": "weekly"},
        {"metric": "tier_a_leads_contacted", "target": 10, "unit": "count", "period": "weekly"},
        {"metric": "campaign_response_rate", "target": 0.05, "unit": "pct", "period": "weekly"},
    ],
    "cro": [
        {"metric": "monthly_revenue", "target": 15000, "unit": "usd", "period": "monthly"},
        {"metric": "churn_rate", "target": 0.05, "unit": "pct", "period": "monthly", "lower_is_better": True},
        {"metric": "missed_call_recovery_rate", "target": 0.80, "unit": "pct", "period": "weekly"},
    ],
    "cfo": [
        {"metric": "revenue_vs_goal", "target": 1.0, "unit": "ratio", "period": "monthly"},
        {"metric": "ai_cost_per_booking", "target": 0.50, "unit": "usd", "period": "monthly", "lower_is_better": True},
        {"metric": "gross_margin", "target": 0.70, "unit": "pct", "period": "monthly"},
    ],
    "csd": [
        {"metric": "customer_satisfaction", "target": 4.5, "unit": "rating", "period": "monthly"},
        {"metric": "churn_risk_resolved", "target": 0.60, "unit": "pct", "period": "weekly"},
        {"metric": "google_reviews_requested", "target": 20, "unit": "count", "period": "monthly"},
    ],
    "cto": [
        {"metric": "workflow_success_rate", "target": 0.95, "unit": "pct", "period": "daily"},
        {"metric": "p99_latency_ms", "target": 2000, "unit": "ms", "period": "daily", "lower_is_better": True},
        {"metric": "uptime_pct", "target": 0.999, "unit": "pct", "period": "monthly"},
    ],
    "learning": [
        {"metric": "agent_accuracy", "target": 0.85, "unit": "pct", "period": "weekly"},
        {"metric": "failed_patterns_documented", "target": 5, "unit": "count", "period": "weekly"},
        {"metric": "knowledge_gaps_closed", "target": 3, "unit": "count", "period": "weekly"},
    ],
}


class GoalEngine:
    async def get_dept_goals(self, business_id: str, dept: str) -> list[dict]:
        """Get current goals for a department with progress."""
        sb = get_supabase()
        db_goals = sb.table("goals").select("*").eq("business_id", business_id)\
            .eq("department", dept).eq("active", True).execute().data or []

        if not db_goals:
            # Seed default goals
            await self._seed_default_goals(business_id, dept)
            db_goals = sb.table("goals").select("*").eq("business_id", business_id)\
                .eq("department", dept).execute().data or []

        return db_goals

    async def check_goal_progress(self, business_id: str, dept: str) -> dict:
        """Check all goals for a dept and return on/off track status."""
        goals = await self.get_dept_goals(business_id, dept)
        results = {"on_track": [], "off_track": [], "at_risk": []}

        for goal in goals:
            target = float(goal.get("target") or 0)
            current = float(goal.get("current") or 0)
            lower_better = goal.get("lower_is_better", False)

            if target == 0:
                continue

            progress = current / target if not lower_better else (target / current if current > 0 else 0)

            goal_with_progress = {**goal, "progress_pct": round(progress * 100, 1)}

            if progress >= 1.0:
                results["on_track"].append(goal_with_progress)
            elif progress >= 0.7:
                results["at_risk"].append(goal_with_progress)
            else:
                results["off_track"].append(goal_with_progress)

        return results

    async def update_goal_progress(self, business_id: str, dept: str, metric: str, value: float) -> None:
        """Update a specific goal's current value."""
        sb = get_supabase()
        sb.table("goals").update({"current": value, "updated_at": datetime.now(timezone.utc).isoformat()})\
            .eq("business_id", business_id).eq("department", dept).eq("metric", metric).execute()

    async def get_off_track_goals(self, business_id: str) -> list[dict]:
        """Get all off-track goals across all depts — used by CEO standup."""
        all_off_track = []
        for dept in DEFAULT_GOALS.keys():
            progress = await self.check_goal_progress(business_id, dept)
            for goal in progress["off_track"]:
                all_off_track.append({**goal, "department": dept})
        return all_off_track

    async def _seed_default_goals(self, business_id: str, dept: str) -> None:
        sb = get_supabase()
        defaults = DEFAULT_GOALS.get(dept, [])
        for g in defaults:
            try:
                sb.table("goals").insert({
                    "business_id": business_id,
                    "department": dept,
                    "title": g["metric"].replace("_", " ").title(),
                    "metric": g["metric"],
                    "target": g["target"],
                    "current": 0,
                    "period": g.get("period", "monthly"),
                    "active": True,
                }).execute()
            except Exception:
                pass


# Singleton
goal_engine = GoalEngine()
