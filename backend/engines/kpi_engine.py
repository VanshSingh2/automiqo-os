"""
KPI Engine — tracks all business metrics in one place.
Revenue, bookings, conversions, AI accuracy, latency, workflow success,
customer satisfaction, token cost. All queryable.
"""
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase


class KPIEngine:
    async def snapshot(self, business_id: str) -> dict:
        """Full KPI snapshot — called by CEO standup, morning briefing, reports."""
        sb = get_supabase()
        bid = business_id
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0).isoformat()
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        # Revenue
        completed = sb.table("appointments").select("revenue").eq("business_id", bid)\
            .eq("status", "completed").gte("scheduled_at", today).execute().data or []
        mtd = sb.table("appointments").select("revenue").eq("business_id", bid)\
            .eq("status", "completed").gte("scheduled_at",
            now.replace(day=1, hour=0, minute=0, second=0).isoformat()).execute().data or []

        revenue_today = sum(float(a.get("revenue") or 0) for a in completed)
        revenue_mtd = sum(float(a.get("revenue") or 0) for a in mtd)

        # Bookings
        appts_today = sb.table("appointments").select("id,status").eq("business_id", bid)\
            .gte("scheduled_at", today).execute().data or []
        no_shows = [a for a in appts_today if a["status"] == "no_show"]
        no_show_rate = len(no_shows) / max(len(appts_today), 1)

        # Leads
        leads = sb.table("leads").select("id,tier,status").eq("business_id", bid).execute().data or []
        tier_a = sum(1 for l in leads if l.get("tier") == "A")

        # Workflows
        tasks_7d = sb.table("tasks").select("status").eq("business_id", bid)\
            .gte("created_at", week_ago).execute().data or []
        wf_success = sum(1 for t in tasks_7d if t["status"] == "completed") / max(len(tasks_7d), 1)
        wf_failed = sum(1 for t in tasks_7d if t["status"] == "failed")

        # AI costs
        ai_costs = sb.table("ai_costs").select("cost_usd,tokens_used,model")\
            .eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        ai_cost_7d = sum(float(c.get("cost_usd") or 0) for c in ai_costs)
        tokens_7d = sum(int(c.get("tokens_used") or 0) for c in ai_costs)

        # Customer health
        customers = sb.table("customers").select("id,tags").eq("business_id", bid).execute().data or []
        churn_risk = sum(1 for c in customers if "churn_risk" in (c.get("tags") or []))

        # Conversations
        convs = sb.table("conversations").select("state").eq("business_id", bid)\
            .gte("created_at", week_ago).execute().data or []
        booked_convs = sum(1 for c in convs if c.get("state") == "booked")
        conv_rate = booked_convs / max(len(convs), 1)

        # Pending approvals
        pending = sb.table("recommendations").select("id").eq("business_id", bid)\
            .eq("status", "pending").execute().data or []

        return {
            "timestamp": now.isoformat(),
            "revenue": {
                "today": round(revenue_today, 2),
                "mtd": round(revenue_mtd, 2),
            },
            "bookings": {
                "today": len(appts_today),
                "no_show_rate": round(no_show_rate * 100, 1),
            },
            "leads": {
                "total": len(leads),
                "tier_a": tier_a,
            },
            "workflows": {
                "success_rate_7d": round(wf_success * 100, 1),
                "failed_7d": wf_failed,
                "total_7d": len(tasks_7d),
            },
            "ai_costs": {
                "cost_7d_usd": round(ai_cost_7d, 4),
                "tokens_7d": tokens_7d,
                "cost_per_booking": round(ai_cost_7d / max(len(appts_today) * 7, 1), 4),
            },
            "customers": {
                "total": len(customers),
                "churn_risk": churn_risk,
            },
            "conversations": {
                "total_7d": len(convs),
                "booked_7d": booked_convs,
                "conversion_rate": round(conv_rate * 100, 1),
            },
            "pending_approvals": len(pending),
        }

    async def track_event(self, business_id: str, metric: str, value: float,
                          dept: str = "", metadata: dict = None) -> None:
        """Record a KPI data point."""
        try:
            sb = get_supabase()
            sb.table("kpi_events").insert({
                "business_id": business_id,
                "metric": metric,
                "value": value,
                "department": dept,
                "metadata": metadata or {},
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass  # kpi_events table added in migration

    async def get_trend(self, business_id: str, metric: str, days: int = 7) -> list[dict]:
        """Get daily trend for a metric."""
        try:
            sb = get_supabase()
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            return sb.table("kpi_events").select("value,recorded_at")\
                .eq("business_id", business_id).eq("metric", metric)\
                .gte("recorded_at", since).order("recorded_at").execute().data or []
        except Exception:
            return []


# Singleton
kpi_engine = KPIEngine()
