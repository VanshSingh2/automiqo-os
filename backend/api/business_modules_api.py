"""Business modules API — reputation, accounting, HR, weekly reports."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["business-modules"])


# ── Reputation ────────────────────────────────────────────────────────────
@router.post("/reputation/{business_id}/ingest")
async def ingest_reviews(business_id: str):
    from backend.integrations.reputation_monitor import ingest_reviews
    return await ingest_reviews(business_id)


@router.get("/reputation/{business_id}/summary")
async def reputation_summary(business_id: str):
    from backend.integrations.reputation_monitor import get_reputation_summary
    return await get_reputation_summary(business_id)


# ── Accounting ────────────────────────────────────────────────────────────
class ExpenseRequest(BaseModel):
    business_id: str
    amount: float
    category: str
    description: str = ""
    vendor: str = ""
    date: Optional[str] = None


@router.post("/accounting/expense")
async def log_expense(req: ExpenseRequest):
    from backend.engines.accounting_engine import accounting_engine
    return await accounting_engine.log_expense(
        req.business_id, req.amount, req.category, req.description, req.vendor, req.date)


@router.get("/accounting/{business_id}/pnl")
async def profit_and_loss(business_id: str, period_days: int = 30):
    from backend.engines.accounting_engine import accounting_engine
    return await accounting_engine.profit_and_loss(business_id, period_days)


@router.get("/accounting/{business_id}/tax-summary")
async def tax_summary(business_id: str, year: Optional[int] = None):
    from backend.engines.accounting_engine import accounting_engine
    return await accounting_engine.tax_summary(business_id, year)


# ── HR ────────────────────────────────────────────────────────────────────
class ApplicantRequest(BaseModel):
    business_id: str
    name: str
    role: str
    email: str = ""
    phone: str = ""
    resume_text: str = ""


@router.post("/hr/applicant")
async def add_applicant(req: ApplicantRequest):
    from backend.engines.hr_manager import hr_manager
    return await hr_manager.add_applicant(
        req.business_id, req.name, req.role, req.email, req.phone, req.resume_text)


@router.post("/hr/{business_id}/applicant/{applicant_id}/screen")
async def screen_applicant(business_id: str, applicant_id: str):
    from backend.engines.hr_manager import hr_manager
    return await hr_manager.screen_applicant(business_id, applicant_id)


@router.get("/hr/{business_id}/pipeline")
async def hiring_pipeline(business_id: str):
    from backend.engines.hr_manager import hr_manager
    return await hr_manager.hiring_pipeline(business_id)


@router.get("/hr/{business_id}/coverage")
async def coverage_check(business_id: str):
    from backend.engines.hr_manager import hr_manager
    return await hr_manager.coverage_check(business_id)


# ── Weekly report ─────────────────────────────────────────────────────────
@router.post("/reports/{business_id}/weekly")
async def weekly_report(business_id: str):
    from backend.engines.weekly_report import weekly_report
    return await weekly_report.generate(business_id)


# ── Memory ────────────────────────────────────────────────────────────────
class RememberRequest(BaseModel):
    business_id: str
    content: str
    title: str = ""
    category: str = "general"


@router.post("/memory/remember-fact")
async def remember_fact(req: RememberRequest):
    from backend.memory.memory_service import memory_for
    await memory_for(req.business_id).remember_fact(req.content, req.title, req.category)
    return {"remembered": True}


@router.get("/memory/{business_id}/recall")
async def recall(business_id: str, query: str, limit: int = 5):
    from backend.memory.memory_service import memory_for
    mem = memory_for(business_id)
    facts = await mem.recall_facts(query, limit)
    events = await mem.recall_events(query, limit)
    return {"facts": facts, "events": events}


@router.get("/memory/{business_id}/context")
async def memory_context(business_id: str, query: str, customer_id: Optional[str] = None):
    from backend.memory.memory_service import memory_for
    ctx = await memory_for(business_id).build_context(query, customer_id)
    return {"context": ctx}


# ── Module blueprint (which departments / managers run for this business) ───
@router.get("/modules/registry")
async def modules_registry():
    """Full catalog of departments + managers + available profiles (for the UI)."""
    from backend.engines.business_blueprint import DEPARTMENTS, PROFILES, SCHEDULABLE_DEPTS
    return {
        "departments": [
            {
                "key": d,
                "label": meta["label"],
                "schedulable": d in SCHEDULABLE_DEPTS,
                "managers": [{"key": mk, "label": ml} for mk, ml in meta["managers"].items()],
            }
            for d, meta in DEPARTMENTS.items() if d != "ceo"
        ],
        "profiles": list(PROFILES.keys()),
    }


@router.get("/modules/{business_id}")
async def get_modules(business_id: str):
    """Resolved module tree for a business (profile defaults + owner overrides)."""
    from backend.engines.business_blueprint import summary
    sb = get_supabase()
    biz = sb.table("businesses").select("config,industry").eq("id", business_id).limit(1).execute().data
    if not biz:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Business not found")
    config = biz[0].get("config") or {}
    config.setdefault("industry", biz[0].get("industry"))
    return summary(config)


class ModuleToggleRequest(BaseModel):
    # Either toggle a department (manager=None) or a single manager.
    department: str
    manager: Optional[str] = None
    enabled: bool


@router.put("/modules/{business_id}")
async def set_module(business_id: str, req: ModuleToggleRequest):
    """Turn a department or a single manager on/off for this business."""
    from backend.engines.business_blueprint import summary, DEPARTMENTS
    from fastapi import HTTPException
    if req.department not in DEPARTMENTS or req.department == "ceo":
        raise HTTPException(status_code=400, detail=f"Unknown department '{req.department}'")
    if req.manager and req.manager not in DEPARTMENTS[req.department]["managers"]:
        raise HTTPException(status_code=400, detail=f"Unknown manager '{req.manager}'")

    sb = get_supabase()
    biz = sb.table("businesses").select("config,industry").eq("id", business_id).limit(1).execute().data
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    config = biz[0].get("config") or {}
    config.setdefault("industry", biz[0].get("industry"))
    overrides = config.get("module_overrides") or {}

    key = f"{req.department}.{req.manager}" if req.manager else req.department
    overrides[key] = bool(req.enabled)
    config["module_overrides"] = overrides

    sb.table("businesses").update({"config": config}).eq("id", business_id).execute()
    return {"updated": True, "key": key, "enabled": bool(req.enabled), "modules": summary(config)}
