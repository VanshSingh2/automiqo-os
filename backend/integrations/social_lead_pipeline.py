"""
Social Lead Pipeline — orchestrates Agent-Reach social scraping
and feeds results into the existing lead intelligence scoring + CRM.

Flow:
  Agent-Reach (Twitter + Reddit + Instagram)
      ↓ raw social leads
  Merge + dedup with existing pipeline format
      ↓
  score_lead_v2() — full scoring with social signals already present
      ↓
  save_leads_to_crm() — upsert to Supabase leads table
"""
import asyncio
from uuid import UUID

from backend.integrations.agent_reach_scraper import (
    check_agent_reach_tools,
    search_twitter_all_queries,
    search_reddit_all_queries,
    search_instagram_leads,
)
from backend.integrations.lead_scorer import score_lead_v2, segment_leads
from backend.integrations.lead_intelligence import save_leads_to_crm


INSTAGRAM_QUERIES = {
    "medspa":   ["med spa New Jersey", "medspa NJ aesthetics", "NJ botox"],
    "salon":    ["hair salon NJ", "nail salon New Jersey"],
    "gym":      ["gym NJ", "fitness studio New Jersey"],
    "dental":   ["dentist NJ", "dental New Jersey"],
    "wellness": ["wellness NJ", "massage New Jersey"],
}


async def run_social_lead_pipeline(
    business_id: UUID,
    industry: str = "medspa",
    platforms: list[str] = None,
    limit_per_platform: int = 30,
) -> dict:
    """
    Run the Agent-Reach social scraping pipeline.
    Complements the Serper/Scrapling pipeline with social-sourced leads.

    Args:
        business_id:        Automiqo client business ID
        industry:           medspa | salon | gym | dental | wellness
        platforms:          list of "twitter" | "reddit" | "instagram" | None = all available
        limit_per_platform: max leads per platform

    Returns:
        Summary dict with counts and top leads
    """
    # Check what tools are available
    tools = check_agent_reach_tools()
    if not tools["any_available"]:
        return {
            "error": "No Agent-Reach tools installed",
            "fix": "Run: agent-reach install --channels=twitter,reddit",
            "twitter_cli": tools["twitter_cli"],
            "rdt_cli": tools["rdt_cli"],
            "opencli": tools["opencli"],
        }

    # Default to all available platforms
    if platforms is None:
        platforms = []
        if tools["twitter_cli"]: platforms.append("twitter")
        if tools["rdt_cli"]:     platforms.append("reddit")
        if tools["opencli"]:     platforms.append("instagram")

    all_leads = []
    stats = {"twitter": 0, "reddit": 0, "instagram": 0}

    # ── Twitter ───────────────────────────────────────────────────────────
    if "twitter" in platforms and tools["twitter_cli"]:
        print(f"[social_pipeline] Twitter scraping ({industry})...")
        try:
            twitter_leads = await search_twitter_all_queries(industry)
            # Normalise to common lead schema
            for lead in twitter_leads[:limit_per_platform]:
                lead["industry"] = industry
                lead["city"] = _extract_nj_city(
                    lead.get("twitter_location", "") + " " + lead.get("twitter_bio", "")
                )
                lead["state"] = "NJ"
                all_leads.append(lead)
            stats["twitter"] = len(twitter_leads)
            print(f"[social_pipeline] Twitter: {len(twitter_leads)} leads")
        except Exception as e:
            print(f"[social_pipeline] Twitter error: {e}")

    # ── Reddit ────────────────────────────────────────────────────────────
    if "reddit" in platforms and tools["rdt_cli"]:
        print(f"[social_pipeline] Reddit scraping ({industry})...")
        try:
            reddit_leads = await search_reddit_all_queries(industry)
            for lead in reddit_leads[:limit_per_platform]:
                lead["industry"] = industry
                lead["city"] = _extract_nj_city(
                    lead.get("reddit_title", "") + " " + (lead.get("reddit_post_url") or "")
                )
                lead["state"] = "NJ"
                all_leads.append(lead)
            stats["reddit"] = len(reddit_leads)
            print(f"[social_pipeline] Reddit: {len(reddit_leads)} leads")
        except Exception as e:
            print(f"[social_pipeline] Reddit error: {e}")

    # ── Instagram ─────────────────────────────────────────────────────────
    if "instagram" in platforms and tools["opencli"]:
        print(f"[social_pipeline] Instagram scraping ({industry})...")
        try:
            ig_queries = INSTAGRAM_QUERIES.get(industry.lower(), [f"{industry} NJ"])
            ig_leads = []
            for query in ig_queries[:2]:
                results = await search_instagram_leads(query, limit=limit_per_platform)
                ig_leads.extend(results)
                await asyncio.sleep(2)
            for lead in ig_leads[:limit_per_platform]:
                lead["industry"] = industry
                lead["city"] = "New Jersey"
                lead["state"] = "NJ"
                all_leads.append(lead)
            stats["instagram"] = len(ig_leads)
            print(f"[social_pipeline] Instagram: {len(ig_leads)} leads")
        except Exception as e:
            print(f"[social_pipeline] Instagram error: {e}")

    if not all_leads:
        return {
            "pipeline_complete": True,
            "source": "social_agent_reach",
            "total_found": 0,
            "stats": stats,
            "tools": tools,
            "message": "No leads found. Check tool auth status with: agent-reach doctor",
        }

    # ── Dedup by company name / handle ───────────────────────────────────
    deduped = []
    seen = set()
    for lead in all_leads:
        key = (
            lead.get("company_name", "").lower().strip()
            or lead.get("twitter_username", "").lower()
            or lead.get("instagram_username", "").lower()
        )
        if key and key not in seen and len(key) > 2:
            seen.add(key)
            deduped.append(lead)

    # ── Score using full scorer (social signals already in lead dict) ─────
    scored = [score_lead_v2(lead) for lead in deduped]
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    segments = segment_leads(scored)

    # ── Save to Supabase ──────────────────────────────────────────────────
    save_result = await save_leads_to_crm(business_id, scored)
    print(f"[social_pipeline] Saved {save_result['saved']} leads, {save_result['skipped']} skipped")

    return {
        "pipeline_complete": True,
        "source": "social_agent_reach",
        "industry": industry,
        "platforms_used": platforms,
        "total_found": len(all_leads),
        "total_deduped": len(deduped),
        "total_saved": save_result["saved"],
        "stats": stats,
        "segments": {
            "tier_a_count": segments["tier_a"]["count"],
            "tier_b_count": segments["tier_b"]["count"],
            "tier_c_count": segments["tier_c"]["count"],
            "no_booking_system": segments["segments"]["no_booking_system"]["count"],
        },
        "top_10_leads": [
            {
                "name": l.get("company_name"),
                "score": l.get("score"),
                "tier": l.get("tier"),
                "source": l.get("source"),
                "platform": _lead_platform(l),
                "email": l.get("email"),
                "phone": l.get("phone"),
                "website": l.get("website"),
                "score_reason": l.get("score_reason", ""),
            }
            for l in scored[:10]
        ],
        "tools_available": tools,
    }


def _extract_nj_city(text: str) -> str:
    """Try to extract a NJ city from text."""
    nj_cities = [
        "newark", "jersey city", "paterson", "elizabeth", "edison",
        "woodbridge", "lakewood", "toms river", "hamilton", "trenton",
        "clifton", "camden", "cherry hill", "passaic", "bergen",
        "essex", "hudson", "middlesex", "union", "monmouth",
        "hackensack", "hoboken", "morristown", "princeton", "parsippany",
    ]
    text_lower = text.lower()
    for city in nj_cities:
        if city in text_lower:
            return city.title()
    return "New Jersey"


def _lead_platform(lead: dict) -> str:
    """Get platform label from a lead."""
    source = lead.get("source", "")
    if "twitter" in source:   return "Twitter"
    if "reddit" in source:    return "Reddit"
    if "instagram" in source: return "Instagram"
    return source
