"""Engines API — exposes all 18 advanced architecture engines via REST."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/engines", tags=["engines"])


@router.get("/kpi/{business_id}")
async def get_kpi_snapshot(business_id: str):
    from backend.engines.kpi_engine import kpi_engine
    return await kpi_engine.snapshot(business_id)


@router.get("/goals/{business_id}/{dept}")
async def get_dept_goals(business_id: str, dept: str):
    from backend.engines.goal_engine import goal_engine
    return await goal_engine.check_goal_progress(business_id, dept)


@router.get("/opportunities/{business_id}")
async def get_opportunities(business_id: str):
    from backend.engines.opportunity_engine import opportunity_engine
    return await opportunity_engine.scan(business_id)


@router.get("/predictions/{business_id}")
async def get_predictions(business_id: str):
    from backend.engines.prediction_engine import prediction_engine
    return await prediction_engine.full_forecast(business_id)


@router.get("/briefing/{business_id}")
async def get_briefing(business_id: str):
    from backend.engines.executive_briefing import executive_briefing
    return await executive_briefing.generate(business_id)


@router.get("/strategy/{business_id}")
async def get_strategy(business_id: str):
    from backend.engines.strategy_planner import strategy_planner
    return await strategy_planner.generate_daily_plan(business_id)


@router.get("/bi/{business_id}")
async def run_bi(business_id: str):
    from backend.engines.business_intelligence import business_intelligence
    return await business_intelligence.run_nightly_analysis(business_id)


@router.get("/knowledge-graph/{business_id}")
async def get_business_graph(business_id: str):
    from backend.engines.knowledge_graph import knowledge_graph
    return await knowledge_graph.get_business_graph(business_id)


@router.get("/knowledge-graph/{business_id}/customer/{customer_id}")
async def get_customer_graph(business_id: str, customer_id: str):
    from backend.engines.knowledge_graph import knowledge_graph
    return await knowledge_graph.get_customer_graph(business_id, customer_id)


@router.get("/costs/{business_id}")
async def get_cost_report(business_id: str):
    from backend.engines.cost_optimizer import cost_optimizer
    return await cost_optimizer.get_weekly_spend_report(business_id)


@router.get("/gaps/{business_id}")
async def get_knowledge_gaps(business_id: str):
    from backend.engines.knowledge_gap_detector import knowledge_gap_detector
    return await knowledge_gap_detector.detect_from_failures(business_id)


class PolicyCheckRequest(BaseModel):
    action: str
    business_id: str
    parameters: dict = {}


@router.post("/policy/check")
async def check_policy(req: PolicyCheckRequest):
    from backend.engines.policy_engine import policy
    result = policy.check(req.action, req.parameters, req.business_id)
    return {"action": result.action, "allowed": result.allowed, "auto_approved": result.auto_approved,
            "risk_level": result.risk_level, "requires_approval": result.requires_approval, "reason": result.reason}


class RiskRequest(BaseModel):
    business_id: str
    workflow: str
    parameters: dict = {}


@router.post("/risk/assess")
async def assess_risk(req: RiskRequest):
    from backend.engines.risk_manager import risk_manager
    r = await risk_manager.assess(req.business_id, req.workflow, req.parameters)
    return {"workflow": r.workflow, "risk_level": r.risk_level, "risk_score": r.risk_score,
            "factors": r.factors, "recommendation": r.recommendation, "block": r.block}


class SimulateRequest(BaseModel):
    business_id: str
    type: str  # pricing_change | staffing_change | campaign
    params: dict = {}


@router.post("/simulate")
async def simulate(req: SimulateRequest):
    from backend.engines.business_simulator import business_simulator
    if req.type == "pricing_change":
        return await business_simulator.simulate_pricing_change(req.business_id, **req.params)
    elif req.type == "staffing_change":
        return await business_simulator.simulate_staffing_change(req.business_id, **req.params)
    elif req.type == "campaign":
        return await business_simulator.simulate_campaign(req.business_id, **req.params)
    return {"error": f"Unknown simulation type: {req.type}"}


@router.get("/capabilities/{dept}")
async def get_capabilities(dept: str):
    from backend.engines.capability_registry import capability_registry
    return capability_registry.get_dept_capabilities(dept)


@router.get("/audit/{business_id}")
async def get_audit_trail(business_id: str, agent: Optional[str] = None, limit: int = 50):
    from backend.engines.audit_manager import audit
    return await audit.get_audit_trail(business_id, agent, limit)


@router.get("/compliance/sms")
async def check_sms_compliance(phone: str, business_id: str, opt_out: bool = False):
    from backend.engines.compliance_manager import compliance_manager
    r = compliance_manager.check_sms(phone, business_id, opt_out)
    return {"compliant": r.compliant, "violations": r.violations, "warnings": r.warnings}


@router.post("/mentor/{business_id}/{dept}")
async def coach_dept(business_id: str, dept: str):
    from backend.engines.ai_mentor import ai_mentor
    return await ai_mentor.coach_department(business_id, dept)
