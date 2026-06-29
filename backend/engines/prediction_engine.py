"""
Prediction Engine — forecasts revenue, no-shows, lead volume, call volume, and churn.
Uses simple trend extrapolation + LLM analysis.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


class PredictionEngine:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def predict_revenue(self, business_id: str, days_ahead: int = 7) -> dict:
        """Forecast revenue for the next N days based on historical trend."""
        sb = get_supabase()
        now = datetime.now(timezone.utc)

        # Get last 30 days of daily revenue
        daily_revenue = []
        for i in range(30, 0, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0).isoformat()
            day_end = (now - timedelta(days=i-1)).replace(hour=0, minute=0, second=0).isoformat()
            appts = sb.table("appointments").select("revenue").eq("business_id", business_id)\
                .eq("status", "completed").gte("scheduled_at", day_start)\
                .lt("scheduled_at", day_end).execute().data or []
            daily_revenue.append(sum(float(a.get("revenue") or 0) for a in appts))

        if not any(daily_revenue):
            return {"forecast": [], "confidence": 0.3, "method": "insufficient_data"}

        # Simple 7-day moving average forecast
        window = 7
        recent_avg = sum(daily_revenue[-window:]) / window
        trend = (daily_revenue[-1] - daily_revenue[-window]) / window if len(daily_revenue) >= window else 0

        forecast = []
        for d in range(1, days_ahead + 1):
            predicted = max(0, recent_avg + (trend * d * 0.5))  # dampen trend
            forecast.append({
                "date": (now + timedelta(days=d)).strftime("%Y-%m-%d"),
                "predicted_revenue": round(predicted, 2),
            })

        return {
            "forecast": forecast,
            "total_predicted": round(sum(f["predicted_revenue"] for f in forecast), 2),
            "daily_avg_recent": round(recent_avg, 2),
            "trend_direction": "up" if trend > 0 else "down" if trend < 0 else "flat",
            "confidence": 0.7 if len(daily_revenue) >= 14 else 0.5,
            "method": "moving_average",
        }

    async def predict_no_shows(self, business_id: str) -> dict:
        """Predict tomorrow's no-show probability based on historical rate."""
        sb = get_supabase()
        now = datetime.now(timezone.utc)
        month_ago = (now - timedelta(days=30)).isoformat()

        appts = sb.table("appointments").select("status,scheduled_at")\
            .eq("business_id", business_id).gte("scheduled_at", month_ago).execute().data or []

        total = len(appts)
        no_shows = sum(1 for a in appts if a["status"] == "no_show")
        rate = no_shows / total if total > 0 else 0.1

        tomorrow = sb.table("appointments").select("id").eq("business_id", business_id)\
            .eq("status", "scheduled").gte("scheduled_at", now.replace(hour=0, minute=0, second=0).isoformat())\
            .lt("scheduled_at", (now + timedelta(days=2)).replace(hour=0, minute=0, second=0).isoformat())\
            .execute().data or []

        expected_no_shows = round(len(tomorrow) * rate)
        return {
            "historical_no_show_rate": round(rate * 100, 1),
            "appointments_tomorrow": len(tomorrow),
            "predicted_no_shows_tomorrow": expected_no_shows,
            "recommendation": "Send reminder calls" if rate > 0.15 else "Reminders sufficient",
        }

    async def predict_churn(self, business_id: str) -> dict:
        """Identify customers at risk of churning in the next 30 days."""
        sb = get_supabase()
        now = datetime.now(timezone.utc)

        customers = sb.table("customers").select("id,name,phone,last_visit,visit_count,lifetime_value,tags")\
            .eq("business_id", business_id).execute().data or []

        churn_risk = []
        for c in customers:
            score = 0
            reasons = []
            last_visit = c.get("last_visit")
            if last_visit:
                days_inactive = (now - datetime.fromisoformat(
                    last_visit.replace("Z", "+00:00")
                )).days
                if days_inactive > 60: score += 40; reasons.append(f"{days_inactive}d inactive")
                elif days_inactive > 30: score += 20; reasons.append(f"{days_inactive}d inactive")
            visit_count = c.get("visit_count", 0) or 0
            if visit_count <= 2: score += 20; reasons.append("low visit count")
            if "churn_risk" in (c.get("tags") or []): score += 30; reasons.append("tagged churn_risk")
            if score >= 40:
                churn_risk.append({
                    "customer_id": c["id"],
                    "name": c.get("name"),
                    "churn_score": score,
                    "reasons": reasons,
                    "ltv": c.get("lifetime_value", 0),
                })

        churn_risk.sort(key=lambda x: x["churn_score"], reverse=True)
        return {
            "churn_risk_customers": len(churn_risk),
            "top_at_risk": churn_risk[:5],
            "total_ltv_at_risk": sum(float(c.get("ltv") or 0) for c in churn_risk),
        }

    async def full_forecast(self, business_id: str) -> dict:
        """Run all predictions — used by CEO standup and morning briefing."""
        import asyncio
        revenue, no_shows, churn = await asyncio.gather(
            self.predict_revenue(business_id),
            self.predict_no_shows(business_id),
            self.predict_churn(business_id),
        )
        return {"revenue_forecast": revenue, "no_show_forecast": no_shows, "churn_forecast": churn}


# Singleton
prediction_engine = PredictionEngine()
