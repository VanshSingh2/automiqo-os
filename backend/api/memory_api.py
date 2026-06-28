"""Memory API — knowledge base CRUD + semantic search + lead enrichment."""
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


# ── Knowledge Base ────────────────────────────────────────────

class KnowledgeItem(BaseModel):
    business_id: str
    category: str
    title: str
    content: str
    source: str = "manual"

class BulkKnowledgeRequest(BaseModel):
    business_id: str
    items: list


@router.post("/knowledge/add")
async def add_knowledge(req: KnowledgeItem):
    from backend.memory.semantic import embed_and_store
    item_id = await embed_and_store(UUID(req.business_id), req.category, req.title, req.content, req.source)
    return {"id": item_id, "stored": True}


@router.post("/knowledge/bulk")
async def bulk_knowledge(req: BulkKnowledgeRequest):
    from backend.memory.semantic import load_business_knowledge
    return await load_business_knowledge(UUID(req.business_id), req.items)


@router.get("/knowledge/search/{business_id}")
async def search_kb(business_id: str, q: str, category: str = None, limit: int = 5):
    from backend.memory.semantic import semantic_search
    results = await semantic_search(UUID(business_id), q, category, limit)
    return {"results": results, "count": len(results)}


# ── Lead Enrichment ───────────────────────────────────────────

class EnrichRequest(BaseModel):
    lead_id: str
    website_url: str


@router.post("/leads/enrich-one")
async def enrich_single_lead(req: EnrichRequest):
    from backend.integrations.scrapegraph import extract_business_info
    from backend.memory.supabase_client import get_supabase
    info = await extract_business_info(req.website_url)
    if info.get("error"):
        return {"enriched": False, "error": info["error"]}
    sb = get_supabase()
    update = {}
    if info.get("email"):
        update["email"] = info["email"]
    if info.get("has_booking_system") is not None:
        update["has_booking_system"] = info["has_booking_system"]
    if info.get("services"):
        update["notes"] = f"Services: {', '.join(info['services'][:5])}"
    if update:
        sb.table("leads").update(update).eq("id", req.lead_id).execute()
    return {"enriched": bool(update), "data": info}


@router.post("/leads/{business_id}/enrich-batch")
async def enrich_batch(business_id: UUID, limit: int = 20):
    from backend.integrations.scrapegraph import enrich_leads_batch
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    result = sb.table("leads").select("id,company_name,website,email") \
        .eq("business_id", str(business_id)).eq("status", "new") \
        .is_("email", "null").limit(limit).execute()
    leads = result.data or []
    if not leads:
        return {"message": "No leads need enrichment", "processed": 0}
    enriched = await enrich_leads_batch(leads)
    updated = 0
    for lead in enriched:
        if lead.get("enriched"):
            upd = {}
            if lead.get("email"):
                upd["email"] = lead["email"]
            if lead.get("has_booking_system") is not None:
                upd["has_booking_system"] = lead["has_booking_system"]
            if upd:
                sb.table("leads").update(upd).eq("id", lead["id"]).execute()
                updated += 1
    return {"processed": len(leads), "enriched": updated}
