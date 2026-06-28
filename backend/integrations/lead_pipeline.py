"""
Full Lead Pipeline: Discover → Enrich → Score → Store → Report
One function call runs the entire pipeline.
"""
import asyncio
from uuid import UUID
from datetime import datetime, timezone

from backend.integrations.lead_discovery import discover_leads
from backend.integrations.lead_enricher import enrich_leads_batch
from backend.integrations.lead_scorer import score_and_prioritize
from backend.memory.supabase_client import get_supabase


async def run_pipeline(
    business_id: str,
    query: str,
    location: str,
    industry: str = "med spa",
    count: int = 50,
    enrich: bool = True,
    min_score: int = 40,
) -> dict:
    """
    Full lead generation pipeline.

    1. Discover via Serper.dev Google Maps + organic
    2. Enrich websites with Scrapling (email, services, booking system)
    3. Score each lead 0-100
    4. Store in Supabase leads table (dedup by phone/website)
    5. Return summary

    Args:
        business_id: UUID of the business running the campaign
        query: search query e.g. "med spa" or "hair salon"
        location: e.g. "New Jersey" or "Hoboken NJ"
        industry: for scoring fit e.g. "med spa", "salon", "gym"
        count: how many leads to find
        enrich: whether to scrape websites (adds ~2-5s per lead)
        min_score: only store leads above this score
    """
    started_at = datetime.now(timezone.utc)

    # Step 1: Discover
    print(f"[pipeline] Discovering leads: {query} in {location}...")
    leads = await discover_leads(query, location, count)
    print(f"[pipeline] Found {len(leads)} raw leads")

    # Step 2: Enrich
    if enrich and leads:
        print(f"[pipeline] Enriching {len(leads)} leads with Scrapling...")
        leads = await enrich_leads_batch(leads, max_concurrent=5)
        enriched_count = sum(1 for l in leads if l.get("enriched"))
        print(f"[pipeline] Enriched {enriched_count} leads")

    # Step 3: Score
    leads = score_and_prioritize(leads, industry)
    high_score = [l for l in leads if l.get("score", 0) >= min_score]
    print(f"[pipeline] {len(high_score)} leads scored >= {min_score}")

    # Step 4: Store in Supabase
    sb = get_supabase()
    stored = skipped = 0

    for lead in leads:
        # Dedup by website or phone
        existing = None
        website = lead.get("website", "")
        phone = lead.get("phone", "")

        if website:
            r = sb.table("leads").select("id").eq("business_id", business_id) \
                .eq("website", website).limit(1).execute()
            existing = r.data[0] if r.data else None

        if not existing and phone:
            r = sb.table("leads").select("id").eq("business_id", business_id) \
                .eq("phone", phone).limit(1).execute()
            existing = r.data[0] if r.data else None

        if existing:
            # Update score if improved
            if lead.get("score", 0) > 0:
                sb.table("leads").update({
                    "score": lead.get("score", 0),
                    "score_reasons": lead.get("score_reasons", ""),
                    "has_booking_system": lead.get("has_booking_system", False),
                    "email": lead.get("email"),
                }).eq("id", existing["id"]).execute()
            skipped += 1
            continue

        # Insert new lead
        try:
            sb.table("leads").insert({
                "business_id": business_id,
                "company_name": lead.get("company_name", ""),
                "industry": industry,
                "phone": lead.get("phone") or lead.get("phone_from_web"),
                "email": lead.get("email"),
                "website": lead.get("website"),
                "address": lead.get("address"),
                "google_rating": lead.get("google_rating"),
                "review_count": lead.get("review_count") or 0,
                "has_booking_system": lead.get("has_booking_system", False),
                "has_website": lead.get("has_website", bool(lead.get("website"))),
                "score": lead.get("score", 0),
                "notes": lead.get("score_reasons", ""),
                "source": lead.get("source", "google_maps"),
                "status": "new",
            }).execute()
            stored += 1
        except Exception:
            skipped += 1

    elapsed = round((datetime.now(timezone.utc) - started_at).total_seconds(), 1)

    return {
        "status": "ok",
        "found": len(leads),
        "stored": stored,
        "skipped_duplicates": skipped,
        "high_score_leads": len(high_score),
        "top_leads": [
            {
                "company_name": l.get("company_name"),
                "score": l.get("score"),
                "reason": l.get("score_reasons"),
                "phone": l.get("phone"),
                "website": l.get("website"),
            }
            for l in high_score[:5]
        ],
        "elapsed_seconds": elapsed,
    }


async def get_pipeline_stats(business_id: str) -> dict:
    """Get current lead pipeline stats for a business."""
    sb = get_supabase()
    all_leads = sb.table("leads").select("id,status,score,has_booking_system,email") \
        .eq("business_id", business_id).execute().data or []

    return {
        "total": len(all_leads),
        "new": sum(1 for l in all_leads if l.get("status") == "new"),
        "contacted": sum(1 for l in all_leads if l.get("status") == "contacted"),
        "converted": sum(1 for l in all_leads if l.get("status") == "converted"),
        "high_score": sum(1 for l in all_leads if (l.get("score") or 0) >= 70),
        "with_email": sum(1 for l in all_leads if l.get("email")),
        "no_booking_system": sum(1 for l in all_leads if not l.get("has_booking_system")),
        "avg_score": round(sum(l.get("score") or 0 for l in all_leads) / max(len(all_leads), 1)),
    }
