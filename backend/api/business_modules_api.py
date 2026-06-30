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
