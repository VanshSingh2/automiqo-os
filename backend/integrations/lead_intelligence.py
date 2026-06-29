"""
Lead Intelligence Engine — orchestrates all 5 stages.
Stage 1: Discovery (Serper.dev)
Stage 2: Website enrichment (Scrapling + Crawl4AI fallback)
Stage 3: Social enrichment (Instagram, Facebook, LinkedIn)
Stage 4: Scoring + Segmentation
Stage 5: CRM storage (Supabase)
"""
import asyncio
from uuid import UUID

INDUSTRY_QUERIES = {
    "medspa": ["med spa", "medical spa", "aesthetics clinic", "botox clinic", "laser aesthetics"],
    "gym": ["gym", "fitness center", "personal training studio", "crossfit", "yoga studio"],
    "salon": ["hair salon", "beauty salon", "nail salon", "barber shop", "blowout bar"],
    "dental": ["dental office", "dentist", "dental clinic", "cosmetic dentist"],
    "wellness": ["wellness center", "chiropractic", "massage therapy", "physical therapy", "acupuncture"],
    "med spa": ["med spa", "medspa", "medical spa", "aesthetics clinic"],
}

NJ_CITIES = [
    "Newark NJ", "Jersey City NJ", "Paterson NJ", "Elizabeth NJ",
    "Edison NJ", "Toms River NJ", "Hamilton NJ", "Trenton NJ",
    "Clifton NJ", "Camden NJ", "Cherry Hill NJ", "Bergen County NJ",
    "Essex County NJ", "Hudson County NJ", "Middlesex County NJ",
]


async def run_discovery(business_id: UUID, industry: str, locations: list[str],
                        limit_per_location: int = 20) -> list[dict]:
    """Stage 1: Discover businesses via Serper.dev Google Maps."""
    from backend.integrations.serper_client import search_google_maps_paginated, normalize_serper_result
    queries = INDUSTRY_QUERIES.get(industry.lower().replace(" ", ""), INDUSTRY_QUERIES.get(industry.lower(), [industry]))
    all_leads = []
    seen_names = set()
    for location in locations:
        for query in queries[:2]:
            results = await search_google_maps_paginated(query=query, location=location, total_results=limit_per_location)
            for raw in results:
                name = raw.get("title", "").lower().strip()
                if name and name not in seen_names:
                    seen_names.add(name)
                    all_leads.append(normalize_serper_result(raw, industry, location))
            await asyncio.sleep(0.5)
    return all_leads


async def run_enrichment(leads: list[dict], include_social: bool = False) -> list[dict]:
    """Stage 2+3: Website enrichment (Scrapling->Crawl4AI) + optional social."""
    from backend.integrations.scrapling_enricher import enrich_with_fallback
    with_website = [l for l in leads if l.get("website")]
    without_website = [l for l in leads if not l.get("website")]
    semaphore = asyncio.Semaphore(5)

    async def enrich_one(lead: dict) -> dict:
        async with semaphore:
            result = await enrich_with_fallback(lead["website"])
            lead.update(result)
            return lead

    enriched = list(await asyncio.gather(*[enrich_one(l) for l in with_website]))
    all_leads = enriched + without_website

    if include_social:
        from backend.integrations.social_scrapers import enrich_social_batch
        top_leads = sorted(all_leads, key=lambda x: x.get("score", 0), reverse=True)[:50]
        rest_leads = all_leads[50:]
        enriched_social = await enrich_social_batch(top_leads, max_concurrent=2, delay_between=2.0)
        all_leads = enriched_social + rest_leads

    return all_leads


async def run_scoring(leads: list[dict], industry: str = "med spa") -> tuple[list[dict], dict]:
    """Stage 4: Score and segment all leads."""
    from backend.integrations.lead_scorer import score_lead_v2, segment_leads
    scored = [score_lead_v2(l) for l in leads]
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    segments = segment_leads(scored)
    return scored, segments


async def save_leads_to_crm(business_id: UUID, leads: list[dict]) -> dict:
    """Stage 5: Upsert leads to Supabase with dedup by website/phone."""
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    saved = skipped = 0
    for lead in leads:
        try:
            existing = None
            website = lead.get("website", "")
            phone = lead.get("phone", "")
            if website:
                r = sb.table("leads").select("id").eq("business_id", str(business_id)).eq("website", website).limit(1).execute()
                existing = r.data[0] if r.data else None
            if not existing and phone:
                r = sb.table("leads").select("id").eq("business_id", str(business_id)).eq("phone", phone).limit(1).execute()
                existing = r.data[0] if r.data else None
            if existing:
                sb.table("leads").update({
                    "score": lead.get("score", 0),
                    "tier": lead.get("tier", "C"),
                    "score_reasons": lead.get("score_reason", ""),
                    "has_booking_system": lead.get("has_online_booking", False),
                    "enrichment_method": lead.get("enrichment_method"),
                }).eq("id", existing["id"]).execute()
                skipped += 1
                continue
            sb.table("leads").insert({
                "business_id": str(business_id),
                "company_name": lead.get("company_name", ""),
                "industry": lead.get("industry", ""),
                "phone": lead.get("phone") or lead.get("phone_from_site"),
                "email": lead.get("email"),
                "website": lead.get("website"),
                "address": lead.get("address"),
                "city": lead.get("city"),
                "state": lead.get("state", "NJ"),
                "google_rating": lead.get("google_rating"),
                "review_count": lead.get("review_count") or 0,
                "has_website": lead.get("has_website", bool(lead.get("website"))),
                "has_booking_system": lead.get("has_online_booking", False),
                "booking_platform": lead.get("booking_platform"),
                "score": lead.get("score", 0),
                "tier": lead.get("tier", "C"),
                "notes": lead.get("score_reason", ""),
                "source": lead.get("source", "google_maps_serper"),
                "status": "new",
                "enriched": lead.get("enriched", False),
                "enrichment_method": lead.get("enrichment_method"),
                "tech_stack": lead.get("tech_stack", []),
                "instagram_username": lead.get("instagram_username"),
                "instagram_followers": lead.get("instagram_followers"),
                "instagram_email": lead.get("instagram_email"),
                "facebook_page_name": lead.get("facebook_page_name"),
                "facebook_url": lead.get("facebook_url"),
                "linkedin_company_url": lead.get("linkedin_company_url"),
            }).execute()
            saved += 1
        except Exception:
            skipped += 1
    return {"saved": saved, "skipped": skipped}



async def run_full_pipeline(business_id: UUID, industry: str, locations: list[str] = None,
                            limit_per_location: int = 20, skip_enrichment: bool = False,
                            include_social: bool = False) -> dict:
    """
    Run the complete Lead Intelligence Pipeline.
    Called by Lead Manager agent and /leads/pipeline/run API endpoint.
    """
    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc)
    if locations is None:
        locations = NJ_CITIES[:5]

    print(f"[Lead Intelligence] {industry} in {locations}")

    # Stage 1: Discovery
    raw_leads = await run_discovery(business_id, industry, locations, limit_per_location)
    print(f"[Stage 1] Found {len(raw_leads)} unique businesses")

    # Stage 2+3: Enrichment
    if not skip_enrichment:
        leads = await run_enrichment(raw_leads, include_social=include_social)
        enriched_count = sum(1 for l in leads if l.get("enriched"))
        print(f"[Stage 2] Enriched {enriched_count} leads")
    else:
        leads = raw_leads

    # Stage 4: Score + Segment
    scored_leads, segments = await run_scoring(leads, industry)
    print(f"[Stage 4] Tier A: {segments['tier_a']['count']}, B: {segments['tier_b']['count']}, C: {segments['tier_c']['count']}")

    # Stage 5: Save to CRM
    save_result = await save_leads_to_crm(business_id, scored_leads)
    print(f"[Stage 5] Saved {save_result['saved']}, skipped {save_result['skipped']}")

    elapsed = round((datetime.now(timezone.utc) - started_at).total_seconds(), 1)

    return {
        "pipeline_complete": True,
        "industry": industry,
        "locations": locations,
        "total_discovered": len(raw_leads),
        "total_enriched": sum(1 for l in scored_leads if l.get("enriched")),
        "total_saved": save_result["saved"],
        "elapsed_seconds": elapsed,
        "segments": {
            "tier_a_count": segments["tier_a"]["count"],
            "tier_b_count": segments["tier_b"]["count"],
            "tier_c_count": segments["tier_c"]["count"],
            "no_booking_system": segments["segments"]["no_booking_system"]["count"],
            "no_website": segments["segments"]["no_website"]["count"],
        },
        "top_20_leads": [
            {
                "name": l["company_name"], "score": l["score"], "tier": l["tier"],
                "phone": l.get("phone"), "email": l.get("email"),
                "booking_platform": l.get("booking_platform"), "score_reason": l.get("score_reason", ""),
            }
            for l in segments["outreach_priority"]
        ],
    }
