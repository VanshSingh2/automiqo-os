"""
Opportunity Engine — continuously identifies upsell, retention, and growth opportunities.
Runs during hourly heartbeat and daily loops to surface actionable opportunities.
"""
from datetime import datetime, timezone, timedelta
from backend.memory.supabase_client import get_supabase


class OpportunityEngine:
    async def scan(self, business_id: str) -> list[dict]:
        """
        Scan for all current opportunities. Returns prioritized list.
        Each opportunity has: type, title, description, potential_value, action, parameters, priority.
        """
        sb = get_supabase()
        bid = business_id
        now = datetime.now(timezone.utc)
        opportunities = []

        # ── Upsell opportunities ─────────────────────────────────────────────
        # Customers who visited in last 7 days but haven't rebooked
        completed_7d = sb.table("appointments").select("customer_id,service,revenue")\
            .eq("business_id", bid).eq("status", "completed")\
            .gte("scheduled_at", (now - timedelta(days=7)).isoformat()).execute().data or []
        visited_ids = {a["customer_id"] for a in completed_7d if a.get("customer_id")}

        # Check which don't have a future booking
        future = sb.table("appointments").select("customer_id")\
            .eq("business_id", bid).in_("status", ["scheduled", "confirmed"])\
            .gte("scheduled_at", now.isoformat()).execute().data or []
        future_ids = {a["customer_id"] for a in future if a.get("customer_id")}

        upsell_candidates = visited_ids - future_ids
        if upsell_candidates:
            opportunities.append({
                "type": "upsell",
                "title": f"Upsell opportunity: {len(upsell_candidates)} recent visitors",
                "description": f"{len(upsell_candidates)} customers visited in last 7 days with no future booking.",
                "potential_value": len(upsell_candidates) * 120,
                "action": "send_upsell_offer",
                "priority": "high",
                "count": len(upsell_candidates),
            })

        # ── Retention opportunities ───────────────────────────────────────────
        dormant = sb.table("customers").select("id,name,phone,lifetime_value")\
            .eq("business_id", bid).eq("opt_out_sms", False)\
            .lt("last_visit", (now - timedelta(days=30)).isoformat()).limit(20).execute().data or []
        if dormant:
            avg_ltv = sum(float(c.get("lifetime_value") or 0) for c in dormant) / len(dormant)
            opportunities.append({
                "type": "retention",
                "title": f"Reactivate {len(dormant)} dormant customers",
                "description": f"Avg LTV ${avg_ltv:.0f}. Win-back potential: ${len(dormant) * avg_ltv * 0.3:.0f}.",
                "potential_value": len(dormant) * avg_ltv * 0.3,
                "action": "reactivate_dormant_member",
                "priority": "high",
                "count": len(dormant),
            })

        # ── Lead pipeline opportunities ───────────────────────────────────────
        tier_a_untouched = sb.table("leads").select("id,score,company_name")\
            .eq("business_id", bid).eq("tier", "A").eq("status", "new").execute().data or []
        if tier_a_untouched:
            opportunities.append({
                "type": "lead_outreach",
                "title": f"{len(tier_a_untouched)} Tier A leads need first contact",
                "description": "High-fit leads with no outreach yet.",
                "potential_value": len(tier_a_untouched) * 500,
                "action": "send_cold_outreach",
                "priority": "high",
                "count": len(tier_a_untouched),
            })

        # ── Referral opportunities ────────────────────────────────────────────
        vip_no_code = sb.table("customers").select("id,name,phone,lifetime_value")\
            .eq("business_id", bid).gt("lifetime_value", 1000).execute().data or []
        # Check which don't have referral codes
        refs = sb.table("referrals").select("referrer_id").eq("business_id", bid).execute().data or []
        ref_ids = {r["referrer_id"] for r in refs}
        vip_no_referral = [c for c in vip_no_code if c["id"] not in ref_ids]
        if vip_no_referral:
            opportunities.append({
                "type": "referral",
                "title": f"{len(vip_no_referral)} VIP customers without referral codes",
                "description": "High-LTV customers who haven't been enrolled in referral program.",
                "potential_value": len(vip_no_referral) * 75,
                "action": "track_referral",
                "priority": "medium",
                "count": len(vip_no_referral),
            })

        # ── Review opportunities ──────────────────────────────────────────────
        completed_no_review = sb.table("appointments").select("id,customer_id")\
            .eq("business_id", bid).eq("status", "completed")\
            .gte("scheduled_at", (now - timedelta(days=3)).isoformat())\
            .lte("scheduled_at", (now - timedelta(days=1)).isoformat()).execute().data or []
        if completed_no_review:
            opportunities.append({
                "type": "review",
                "title": f"Request reviews from {len(completed_no_review)} recent visitors",
                "description": "Completed visits in last 1-3 days — optimal review request window.",
                "potential_value": len(completed_no_review) * 50,
                "action": "request_google_review",
                "priority": "medium",
                "count": len(completed_no_review),
            })

        # Sort by potential value
        opportunities.sort(key=lambda x: x.get("potential_value", 0), reverse=True)
        return opportunities

    async def get_top_opportunity(self, business_id: str) -> dict:
        """Get the single highest-value opportunity right now."""
        opps = await self.scan(business_id)
        return opps[0] if opps else {}


# Singleton
opportunity_engine = OpportunityEngine()
