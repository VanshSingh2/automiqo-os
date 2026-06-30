"""
Onboarding v2 — captures the full business profile so every agent operates
"in accordance with THIS business". Saves rich config to businesses.config
(JSONB), seeds staff + services rows, and loads FAQs/policies into the
knowledge base (pgvector) for semantic recall.
"""
from fastapi import APIRouter, HTTPException
from uuid import UUID
from shared.schemas import OnboardRequest, OnboardUpdateRequest
from backend.memory.supabase_client import get_supabase

router = APIRouter()


def _build_config(req: OnboardRequest) -> dict:
    """Assemble the business 'brain' config stored on businesses.config."""
    return {
        "website": req.website,
        "city": req.city,
        "state": req.state,
        "services": [s.model_dump() for s in req.services],
        "business_hours": req.business_hours,
        "booking_url": req.booking_url,
        "brand_voice": req.brand_voice,
        "target_customer": req.target_customer,
        "monthly_revenue_goal": req.monthly_revenue_goal,
        "avg_ticket_value": req.avg_ticket_value,
        "policies": req.policies,
        "competitors": req.competitors,
        "unique_selling_points": req.unique_selling_points,
    }


@router.post("/onboard")
async def onboard_business(req: OnboardRequest):
    """Create a business with full profile, staff, services, and knowledge base."""
    sb = get_supabase()

    # 1. Create the business record + config brain
    biz = sb.table("businesses").insert({
        "name": req.name,
        "industry": req.industry,
        "phone": req.phone,
        "email": req.email,
        "address": req.address,
        "timezone": req.timezone,
        "config": _build_config(req),
    }).execute()
    if not biz.data:
        raise HTTPException(status_code=500, detail="Failed to create business")
    business_id = biz.data[0]["id"]

    seeded = {"staff": 0, "knowledge": 0, "goals": 0}

    # 2. Seed staff rows
    for member in req.staff:
        try:
            sb.table("staff").insert({
                "business_id": business_id,
                "name": member.name,
                "role": member.role,
                "phone": member.phone,
                "email": member.email,
                "services": member.services,
                "active": True,
            }).execute()
            seeded["staff"] += 1
        except Exception:
            pass

    # 3. Seed knowledge base: services, policies, FAQs (semantic recall for agents)
    kb_entries = []
    for s in req.services:
        kb_entries.append(("services", s.name,
            f"Service: {s.name}. Price: {s.price or 'varies'}. "
            f"Duration: {s.duration_minutes or '?'} min. {s.description or ''}"))
    for p in req.policies:
        kb_entries.append(("policy", "Policy", p))
    for f in req.faqs:
        kb_entries.append(("faq", f.question, f"Q: {f.question}\nA: {f.answer}"))
    for usp in req.unique_selling_points:
        kb_entries.append(("positioning", "USP", usp))

    for category, title, content in kb_entries:
        try:
            # Try to embed; fall back to plain storage if embeddings unavailable
            from backend.memory.semantic import embed_and_store
            await embed_and_store(business_id, category, title, content, source="onboarding")
            seeded["knowledge"] += 1
        except Exception:
            try:
                sb.table("knowledge").insert({
                    "business_id": business_id, "category": category,
                    "title": title, "content": content,
                    "source": "onboarding", "approved": True,
                }).execute()
                seeded["knowledge"] += 1
            except Exception:
                pass

    # 4. Seed revenue goal for CFO/CRO
    if req.monthly_revenue_goal:
        try:
            sb.table("goals").insert({
                "business_id": business_id, "department": "cfo",
                "title": "Monthly Revenue", "metric": "monthly_revenue",
                "target": req.monthly_revenue_goal, "current": 0,
                "period": "monthly", "active": True,
            }).execute()
            seeded["goals"] += 1
        except Exception:
            pass

    return {
        "business_id": business_id,
        "name": req.name,
        "onboarded": True,
        "seeded": seeded,
        "message": f"{req.name} is ready. Agents will now operate using this business profile.",
    }


@router.patch("/onboard/update")
async def update_business(req: OnboardUpdateRequest):
    """Update business profile fields (merges into config)."""
    sb = get_supabase()
    bid = str(req.business_id)
    current = sb.table("businesses").select("config").eq("id", bid).limit(1).execute().data
    if not current:
        raise HTTPException(status_code=404, detail="Business not found")
    config = current[0].get("config") or {}
    # Split top-level columns vs config keys
    top_level = {}
    for k, v in req.updates.items():
        if k in ("name", "industry", "phone", "email", "address", "timezone"):
            top_level[k] = v
        else:
            config[k] = v
    payload = {**top_level, "config": config}
    sb.table("businesses").update(payload).eq("id", bid).execute()
    return {"updated": True, "business_id": bid}


@router.get("/onboard/{business_id}/profile")
async def get_profile(business_id: str):
    """Return the full business profile + config brain."""
    sb = get_supabase()
    biz = sb.table("businesses").select("*").eq("id", business_id).limit(1).execute().data
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    staff = sb.table("staff").select("name,role,services").eq("business_id", business_id).execute().data or []
    kb = sb.table("knowledge").select("category,title").eq("business_id", business_id).execute().data or []
    return {"business": biz[0], "staff": staff, "knowledge_items": len(kb)}
