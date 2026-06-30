"""
Weekly Executive Report — generates a comprehensive weekly summary across all
departments and emails it to the owner. Runs Sundays via the scheduler.
"""
import os
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase


class WeeklyReportGenerator:
    async def generate(self, business_id: str) -> dict:
        """Build the full weekly report payload from all engines."""
        import asyncio
        from backend.engines.kpi_engine import kpi_engine
        from backend.engines.accounting_engine import accounting_engine
        from backend.engines.cost_optimizer import cost_optimizer

        sb = get_supabase()
        biz = sb.table("businesses").select("name,email,config").eq("id", business_id).limit(1).execute().data
        if not biz:
            return {"error": "business not found"}
        name = biz[0]["name"]
        owner_email = biz[0].get("email")

        kpis, pnl, costs = await asyncio.gather(
            kpi_engine.snapshot(business_id),
            accounting_engine.profit_and_loss(business_id, 7),
            cost_optimizer.get_weekly_spend_report(business_id),
        )

        # Reputation
        try:
            from backend.integrations.reputation_monitor import get_reputation_summary
            reputation = await get_reputation_summary(business_id)
        except Exception:
            reputation = {}

        # Week-over-week appointment + lead counts
        now = datetime.now(timezone.utc)
        wk = (now - timedelta(days=7)).isoformat()
        appts = sb.table("appointments").select("id,status").eq("business_id", business_id)\
            .gte("scheduled_at", wk).execute().data or []
        leads = sb.table("leads").select("id,tier").eq("business_id", business_id)\
            .gte("scraped_at", wk).execute().data or []
        completed_convs = sb.table("conversations").select("state").eq("business_id", business_id)\
            .eq("state", "booked").gte("created_at", wk).execute().data or []

        report = {
            "business": name,
            "week_ending": now.date().isoformat(),
            "revenue_7d": pnl.get("revenue", 0),
            "expenses_7d": pnl.get("total_expenses", 0),
            "net_profit_7d": pnl.get("net_profit", 0),
            "profit_margin_pct": pnl.get("profit_margin_pct", 0),
            "appointments_7d": len(appts),
            "no_shows_7d": len([a for a in appts if a["status"] == "no_show"]),
            "new_leads_7d": len(leads),
            "tier_a_leads_7d": len([l for l in leads if l.get("tier") == "A"]),
            "bookings_from_conversations_7d": len(completed_convs),
            "ai_cost_7d": costs.get("total_cost_7d", 0),
            "avg_rating": reputation.get("avg_rating", 0),
            "negative_reviews_open": reputation.get("negative_unresponded", 0),
            "workflow_success_rate": kpis.get("workflows", {}).get("success_rate_7d", 0),
            "pending_approvals": kpis.get("pending_approvals", 0),
        }

        # Save report
        try:
            sb.table("reports").insert({
                "business_id": business_id,
                "report_date": now.date().isoformat(),
                "report_type": "weekly_executive",
                "content": report,
                "summary": f"Week ending {report['week_ending']}: ${report['revenue_7d']:.0f} revenue, "
                           f"{report['appointments_7d']} appts, {report['new_leads_7d']} new leads, "
                           f"${report['net_profit_7d']:.0f} net profit",
            }).execute()
        except Exception:
            pass

        # Email it (best-effort via Resend)
        if owner_email:
            await self._email_report(owner_email, name, report)

        return report

    async def _email_report(self, to_email: str, business_name: str, r: dict) -> None:
        import httpx
        key = os.getenv("RESEND_API_KEY", "")
        if not key:
            return
        html = (
            f"<h2>{business_name} — Weekly Report (week ending {r['week_ending']})</h2>"
            f"<ul>"
            f"<li><b>Revenue:</b> ${r['revenue_7d']:.0f} | <b>Net profit:</b> ${r['net_profit_7d']:.0f} "
            f"({r['profit_margin_pct']}% margin)</li>"
            f"<li><b>Appointments:</b> {r['appointments_7d']} ({r['no_shows_7d']} no-shows)</li>"
            f"<li><b>New leads:</b> {r['new_leads_7d']} ({r['tier_a_leads_7d']} Tier A)</li>"
            f"<li><b>Bookings from AI conversations:</b> {r['bookings_from_conversations_7d']}</li>"
            f"<li><b>Avg rating:</b> {r['avg_rating']} ({r['negative_reviews_open']} negative open)</li>"
            f"<li><b>AI cost:</b> ${r['ai_cost_7d']:.2f} | <b>Workflow success:</b> {r['workflow_success_rate']}%</li>"
            f"<li><b>Pending approvals:</b> {r['pending_approvals']}</li>"
            f"</ul>"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post("https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"from": "reports@automiqo.com", "to": [to_email],
                          "subject": f"{business_name} — Your Weekly Business Report",
                          "html": html})
        except Exception:
            pass


weekly_report = WeeklyReportGenerator()
