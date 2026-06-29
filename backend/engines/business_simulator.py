"""
Business Simulator — simulate pricing, staffing, expansion, marketing decisions before implementing.
"What if we raised prices 10%?" → simulate impact on bookings, revenue, churn.
"What if we added a 3rd staff member?" → simulate utilization and ROI.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from backend.memory.supabase_client import get_supabase


class BusinessSimulator:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def simulate_pricing_change(self, business_id: str, change_pct: float, service: str = "all") -> dict:
        """Simulate a pricing change and forecast impact."""
        sb = get_supabase()
        now = datetime.now(timezone.utc)
        month_ago = (now - timedelta(days=30)).isoformat()

        appts = sb.table("appointments").select("revenue,status,service")\
            .eq("business_id", business_id).gte("scheduled_at", month_ago).execute().data or []
        completed = [a for a in appts if a["status"] == "completed" and
                     (service == "all" or a.get("service", "").lower() == service.lower())]
        if not completed:
            return {"error": "insufficient_data"}

        current_avg_ticket = sum(float(a.get("revenue") or 0) for a in completed) / len(completed)
        current_monthly_revenue = sum(float(a.get("revenue") or 0) for a in completed)
        current_bookings = len(completed)

        # Estimate elasticity: price-sensitive industry
        elasticity = -0.8  # 10% price increase → ~8% volume decrease
        new_price = current_avg_ticket * (1 + change_pct / 100)
        volume_change = elasticity * (change_pct / 100)
        new_bookings = max(0, current_bookings * (1 + volume_change))
        new_revenue = new_price * new_bookings

        return {
            "scenario": f"{change_pct:+.0f}% price change on {service} services",
            "current": {
                "avg_ticket": round(current_avg_ticket, 2),
                "monthly_bookings": current_bookings,
                "monthly_revenue": round(current_monthly_revenue, 2),
            },
            "projected": {
                "avg_ticket": round(new_price, 2),
                "monthly_bookings": round(new_bookings, 1),
                "monthly_revenue": round(new_revenue, 2),
                "revenue_change": round(new_revenue - current_monthly_revenue, 2),
                "revenue_change_pct": round((new_revenue - current_monthly_revenue) / max(current_monthly_revenue, 1) * 100, 1),
            },
            "recommendation": "Proceed" if new_revenue > current_monthly_revenue else "Reconsider — revenue may drop",
            "confidence": 0.65,
            "method": "price_elasticity_model",
        }

    async def simulate_staffing_change(self, business_id: str, staff_delta: int) -> dict:
        """Simulate adding or removing staff members."""
        sb = get_supabase()
        staff = sb.table("staff").select("id").eq("business_id", business_id).eq("active", True).execute().data or []
        current_staff = len(staff)
        new_staff = max(1, current_staff + staff_delta)

        now = datetime.now(timezone.utc)
        appts = sb.table("appointments").select("revenue,status")\
            .eq("business_id", business_id).eq("status", "completed")\
            .gte("scheduled_at", (now - timedelta(days=30)).isoformat()).execute().data or []
        avg_revenue_per_booking = sum(float(a.get("revenue") or 0) for a in appts) / max(len(appts), 1)
        monthly_bookings = len(appts)

        capacity_multiplier = new_staff / max(current_staff, 1)
        projected_bookings = monthly_bookings * capacity_multiplier * 0.85  # 85% utilization
        projected_revenue = projected_bookings * avg_revenue_per_booking
        staff_cost = new_staff * 3500  # Avg monthly staff cost
        current_staff_cost = current_staff * 3500
        net_change = (projected_revenue - monthly_bookings * avg_revenue_per_booking) - (staff_cost - current_staff_cost)

        return {
            "scenario": f"{staff_delta:+d} staff member(s)",
            "current_staff": current_staff,
            "proposed_staff": new_staff,
            "projected_monthly_bookings": round(projected_bookings, 1),
            "projected_monthly_revenue": round(projected_revenue, 2),
            "additional_staff_cost": round((staff_cost - current_staff_cost), 2),
            "net_impact_monthly": round(net_change, 2),
            "roi_months": round(abs(staff_cost - current_staff_cost) / max(abs(net_change), 1), 1) if net_change > 0 else None,
            "recommendation": "Worthwhile" if net_change > 0 else "Not profitable at current booking volume",
        }

    async def simulate_campaign(self, business_id: str, channel: str, audience_size: int,
                                  cost_per_send: float = 0.01) -> dict:
        """Simulate a marketing campaign's expected ROI."""
        conversion_rates = {"sms": 0.08, "email": 0.04, "whatsapp": 0.06, "outbound_call": 0.15}
        rate = conversion_rates.get(channel, 0.05)

        sb = get_supabase()
        appts = sb.table("appointments").select("revenue").eq("business_id", business_id)\
            .eq("status", "completed").limit(50).execute().data or []
        avg_booking = sum(float(a.get("revenue") or 0) for a in appts) / max(len(appts), 1) if appts else 120

        sends = audience_size
        conversions = round(sends * rate)
        revenue = conversions * avg_booking
        cost = sends * cost_per_send
        roi = (revenue - cost) / max(cost, 0.01) * 100

        return {
            "channel": channel,
            "audience_size": sends,
            "expected_conversions": conversions,
            "expected_revenue": round(revenue, 2),
            "estimated_cost": round(cost, 2),
            "expected_roi_pct": round(roi, 1),
            "recommendation": "Launch" if roi > 200 else "Review" if roi > 50 else "Reconsider",
        }


# Singleton
business_simulator = BusinessSimulator()
