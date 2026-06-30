"""
CFO Autonomous Daily Work Loop — runs at 10am.
Proactively manages finances every day:
- Reviews yesterday's revenue vs daily goal
- Flags anomalies (unusually low/high revenue)
- Checks AI cost spend vs budget
- Reviews pending purchase orders
- Generates daily financial snapshot → saves as report
- Notifies CEO if revenue is off-track
"""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.cfo.agent import CFOAgent


async def run_cfo_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat()
    yesterday_end = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    # Only run managers this business has enabled.
    from backend.engines.business_blueprint import is_manager_enabled
    try:
        _biz = sb.table("businesses").select("config").eq("id", bid).limit(1).execute().data
        config = (_biz[0].get("config") if _biz else {}) or {}
    except Exception:
        config = {}
    analytics_on = is_manager_enabled(config, "cfo", "analytics")
    planner_on = is_manager_enabled(config, "cfo", "business_planner")
    risk_on = is_manager_enabled(config, "cfo", "risk")

    actions_taken = []
    approvals_queued = []

    # ── 1. YESTERDAY REVENUE ─────────────────────────────────
    yesterday_appts = sb.table("appointments").select("id,revenue,status")\
        .eq("business_id", bid).eq("status", "completed")\
        .gte("scheduled_at", yesterday_start).lte("scheduled_at", yesterday_end).execute().data or []
    yesterday_revenue = sum(float(a.get("revenue") or 0) for a in yesterday_appts)
    yesterday_bookings = len(yesterday_appts)

    # ── 2. MONTH-TO-DATE REVENUE ─────────────────────────────
    mtd_appts = sb.table("appointments").select("id,revenue")\
        .eq("business_id", bid).eq("status", "completed")\
        .gte("scheduled_at", month_start).execute().data or []
    mtd_revenue = sum(float(a.get("revenue") or 0) for a in mtd_appts)

    # ── 3. GOALS CHECK ───────────────────────────────────────
    goals = sb.table("goals").select("id,title,metric,target,current")\
        .eq("business_id", bid).eq("department", "cfo").eq("active", True).execute().data or []
    off_track_goals = []
    for goal in goals:
        target = float(goal.get("target") or 0)
        current = float(goal.get("current") or 0)
        if target > 0 and current / target < 0.7:
            off_track_goals.append(goal["title"])

    # ── 4. AI COST MONITORING ────────────────────────────────
    ai_costs_7d = sb.table("ai_costs").select("cost_usd,model")\
        .eq("business_id", bid).gte("created_at", week_ago).execute().data or []
    total_ai_cost_7d = sum(float(c.get("cost_usd") or 0) for c in ai_costs_7d)

    # Flag if AI costs > $5/week
    if analytics_on and total_ai_cost_7d > 5.0:
        await dispatch_action(bid, "generate_cost_report", {
            "period": "7d", "total_ai_cost": total_ai_cost_7d,
            "alert": f"AI spend ${total_ai_cost_7d:.2f} this week",
        }, "CFO daily loop: AI cost alert")
        approvals_queued.append(f"AI cost alert: ${total_ai_cost_7d:.2f}/week")

    # ── 5. PENDING PURCHASE ORDERS ───────────────────────────
    pending_pos = sb.table("purchase_orders").select("id,total_amount,status")\
        .eq("business_id", bid).eq("status", "draft").execute().data or []
    for po in (pending_pos[:3] if planner_on else []):
        await dispatch_action(bid, "create_purchase_order", {
            "purchase_order_id": po["id"],
            "action": "review_and_send",
        }, f"CFO daily loop: draft PO ${po.get('total_amount',0)} awaiting action")
        approvals_queued.append(f"purchase order review: ${po.get('total_amount',0)}")

    # ── 6. SAVE DAILY FINANCIAL SNAPSHOT ─────────────────────
    snapshot = {
        "date": now.strftime("%Y-%m-%d"),
        "yesterday_revenue": yesterday_revenue,
        "yesterday_bookings": yesterday_bookings,
        "mtd_revenue": mtd_revenue,
        "ai_cost_7d": total_ai_cost_7d,
        "off_track_goals": off_track_goals,
        "pending_pos": len(pending_pos),
    }
    sb.table("reports").upsert({
        "business_id": bid,
        "report_date": now.strftime("%Y-%m-%d"),
        "report_type": "daily_financial",
        "content": snapshot,
        "summary": f"Revenue yesterday: ${yesterday_revenue:.0f} | MTD: ${mtd_revenue:.0f} | AI cost 7d: ${total_ai_cost_7d:.2f}",
    }, on_conflict="business_id,report_date,report_type").execute()
    actions_taken.append("daily financial snapshot saved")

    # ── 7. CFO AGENT STRATEGIC REVIEW ────────────────────────
    try:
        agent = CFOAgent(UUID(bid))
        resp = await agent.run(
            "Daily financial review: analyze revenue trends, cost anomalies, and forecast risk. "
            "What financial decisions should I flag for the owner today?",
            context=snapshot,
        )
        for rec in (resp.recommendations or [])[:3]:
            await dispatch_action(bid, "generate_reflection", {
                "agent": "CFO", "observation": rec, "source": "daily_loop"
            }, "CFO daily insight")

        # Notify CEO if revenue off-track
        if risk_on and (off_track_goals or yesterday_revenue == 0):
            from backend.events.bus import publish
            await publish(bid, "internal.ceo_alert", {
                "from": "CFO",
                "message": f"Revenue alert: yesterday ${yesterday_revenue:.0f}, MTD ${mtd_revenue:.0f}. Off-track goals: {off_track_goals}",
                "trigger_action": "generate_revenue_report",
                "urgency": "high",
            }, source="cfo_daily_loop")
            # Cross-dept: tell CRO to push quick-win revenue actions
            try:
                from backend.events.inter_dept import cfo_notify_cro_revenue_gap
                days_left = max(1, 30 - now.day)
                await cfo_notify_cro_revenue_gap(bid, max(yesterday_revenue, 500), days_left)
            except Exception:
                pass
            actions_taken.append("CEO + CRO alerted: revenue off-track")
    except Exception:
        pass

    return {
        "department": "CFO",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "yesterday_revenue": yesterday_revenue,
        "mtd_revenue": mtd_revenue,
        "ai_cost_7d": total_ai_cost_7d,
    }
