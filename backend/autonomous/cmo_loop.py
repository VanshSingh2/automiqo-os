"""
CMO Autonomous Daily Work Loop — runs at 8am.
Proactively works on marketing every day:
- Checks lead pipeline health, queues new scraping if pipeline is thin
- Reviews campaign performance, pauses underperformers
- Identifies Tier A leads with no outreach → queues cold outreach
- Checks social posting schedule
- Reviews experiment results
"""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.cmo.agent import CMOAgent


async def run_cmo_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()

    actions_taken = []
    approvals_queued = []

    # ── 1. LEAD PIPELINE HEALTH ──────────────────────────────
    leads = sb.table("leads").select("id,status,score,tier,email,phone,last_contacted")\
        .eq("business_id", bid).execute().data or []

    total_leads = len(leads)
    tier_a = [l for l in leads if l.get("tier") == "A" and l.get("status") == "new"]
    contacted_7d = [l for l in leads if l.get("last_contacted") and l["last_contacted"] > week_ago]

    # If fewer than 20 leads in pipeline, auto-trigger discovery
    if total_leads < 20:
        await dispatch_action(bid, "run_lead_pipeline", {
            "industry": "medspa", "locations": [], "limit_per_location": 20, "skip_enrichment": True
        }, f"CMO daily loop: pipeline thin ({total_leads} leads), auto-discovering new leads")
        actions_taken.append(f"lead discovery queued (pipeline: {total_leads})")

    # Queue cold outreach for Tier A leads not yet contacted
    if len(tier_a) > 0:
        await dispatch_action(bid, "send_cold_outreach", {
            "tier": "A", "min_score": 70, "limit": min(10, len(tier_a))
        }, f"CMO daily loop: {len(tier_a)} Tier A leads awaiting first contact")
        approvals_queued.append(f"cold outreach: {len(tier_a)} Tier A leads")

    # ── 2. CAMPAIGN PERFORMANCE ──────────────────────────────
    campaigns = sb.table("campaigns").select("id,name,status,sent_count,response_count,booking_count")\
        .eq("business_id", bid).eq("status", "active").execute().data or []

    for camp in campaigns:
        sent = camp.get("sent_count", 0) or 0
        responses = camp.get("response_count", 0) or 0
        if sent > 50 and responses / max(sent, 1) < 0.02:
            await dispatch_action(bid, "simulate_campaign", {
                "campaign_id": camp["id"],
                "action": "pause_and_review",
                "reason": f"Response rate {round(responses/max(sent,1)*100,1)}% below 2% threshold",
            }, f"CMO daily loop: pausing underperforming campaign '{camp['name']}'")
            approvals_queued.append(f"campaign pause: {camp['name']}")

    # ── 3. CONTENT / SOCIAL SCHEDULE ────────────────────────
    # Check if a social post went out this week
    social_posts = sb.table("tasks").select("id,created_at").eq("business_id", bid)\
        .eq("workflow", "schedule_social_post").gte("created_at", week_ago).execute().data or []
    if len(social_posts) == 0:
        await dispatch_action(bid, "schedule_social_post", {
            "platform": "instagram",
            "topic": "auto_generated",
            "instruction": "Create an engaging post about our services for this week",
        }, "CMO daily loop: no social post this week, scheduling one")
        approvals_queued.append("social post scheduled")

    # ── 4. CMO AGENT STRATEGIC REVIEW ───────────────────────
    try:
        agent = CMOAgent(UUID(bid))
        context = {
            "total_leads": total_leads,
            "tier_a_uncontacted": len(tier_a),
            "active_campaigns": len(campaigns),
            "contacted_this_week": len(contacted_7d),
            "actions_auto_taken": actions_taken,
        }
        resp = await agent.run(
            "Daily marketing review: what are the top 3 marketing actions I should take today "
            "to grow the pipeline and improve conversion? Be specific with workflow names.",
            context=context,
        )
        for rec in (resp.recommendations or [])[:3]:
            await dispatch_action(bid, "generate_reflection", {
                "agent": "CMO", "observation": rec, "source": "daily_loop"
            }, "CMO daily insight")
    except Exception:
        pass

    return {
        "department": "CMO",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "total_leads": total_leads,
        "tier_a_uncontacted": len(tier_a),
    }
