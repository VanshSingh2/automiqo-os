"""Leads API — Lead Intelligence Engine REST endpoints."""
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/leads", tags=["leads"])


class PipelineRunRequest(BaseModel):
    business_id: str
    industry: str = "medspa"
    locations: list[str] = []
    limit_per_location: int = 20
    skip_enrichment: bool = False
    include_social: bool = False


@router.post("/pipeline/run")
async def run_pipeline(req: PipelineRunRequest):
    """Run the full Lead Intelligence Pipeline: discover → enrich → score → store."""
    from backend.integrations.lead_intelligence import run_full_pipeline
    return await run_full_pipeline(
        business_id=UUID(req.business_id),
        industry=req.industry,
        locations=req.locations if req.locations else None,
        limit_per_location=req.limit_per_location,
        skip_enrichment=req.skip_enrichment,
        include_social=req.include_social,
    )


@router.post("/pipeline/discover-only")
async def discover_only(req: PipelineRunRequest):
    """Fast discovery only — no enrichment. Returns raw counts."""
    from backend.integrations.lead_intelligence import run_full_pipeline
    return await run_full_pipeline(
        business_id=UUID(req.business_id),
        industry=req.industry,
        locations=req.locations if req.locations else None,
        limit_per_location=req.limit_per_location,
        skip_enrichment=True,
        include_social=False,
    )


@router.get("/{business_id}/intelligence-summary")
async def intelligence_summary(business_id: UUID):
    """Get lead pipeline summary with tier breakdown and top leads."""
    from backend.integrations.lead_pipeline import get_pipeline_stats
    from backend.memory.supabase_client import get_supabase
    stats = await get_pipeline_stats(str(business_id))
    sb = get_supabase()
    top_leads = sb.table("leads").select("company_name,score,tier,phone,email,booking_platform,notes") \
        .eq("business_id", str(business_id)).eq("tier", "A") \
        .order("score", desc=True).limit(5).execute().data or []
    return {"pipeline_stats": stats, "top_5_leads": top_leads}


class EnrichOneRequest(BaseModel):
    lead_id: str
    website_url: str


@router.post("/enrich-one")
async def enrich_single_lead(req: EnrichOneRequest):
    """Enrich a single lead with website data (Scrapling + Crawl4AI fallback)."""
    from backend.integrations.scrapling_enricher import enrich_with_fallback
    from backend.memory.supabase_client import get_supabase
    result = await enrich_with_fallback(req.website_url)
    if result.get("enrichment_failed"):
        return {"enriched": False, "reason": result.get("reason")}
    sb = get_supabase()
    update = {}
    if result.get("email"):
        update["email"] = result["email"]
    if result.get("has_online_booking") is not None:
        update["has_booking_system"] = result["has_online_booking"]
    if result.get("booking_platform"):
        update["booking_platform"] = result["booking_platform"]
    if result.get("enrichment_method"):
        update["enrichment_method"] = result["enrichment_method"]
    if update:
        sb.table("leads").update(update).eq("id", req.lead_id).execute()
    return {"enriched": bool(update), "method": result.get("enrichment_method"), "data": result}


@router.post("/{business_id}/enrich-batch")
async def enrich_batch(business_id: UUID, limit: int = 20):
    """Enrich a batch of leads that are missing enrichment data."""
    from backend.integrations.scrapling_enricher import enrich_with_fallback
    from backend.memory.supabase_client import get_supabase
    import asyncio
    sb = get_supabase()
    leads = sb.table("leads").select("id,website,email").eq("business_id", str(business_id)) \
        .eq("status", "new").is_("email", "null").limit(limit).execute().data or []
    if not leads:
        return {"message": "No leads need enrichment", "processed": 0}
    semaphore = asyncio.Semaphore(5)
    updated = 0
    for lead in leads:
        if not lead.get("website"):
            continue
        async with semaphore:
            result = await enrich_with_fallback(lead["website"])
            if result.get("enriched"):
                upd = {k: result[k] for k in ("email", "has_online_booking", "booking_platform", "enrichment_method") if result.get(k) is not None}
                if upd:
                    sb.table("leads").update(upd).eq("id", lead["id"]).execute()
                    updated += 1
    return {"processed": len(leads), "enriched": updated}


@router.get("/{business_id}/stats")
async def lead_stats(business_id: str):
    """Get lead pipeline stats."""
    from backend.integrations.lead_pipeline import get_pipeline_stats
    return await get_pipeline_stats(business_id)
