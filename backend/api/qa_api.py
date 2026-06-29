"""QA API — QA & Reliability Department REST endpoints."""
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/qa", tags=["qa"])


class QARunRequest(BaseModel):
    business_id: str
    phase: str = "all"  # "all" | "phase1" | "phase2" | "phase3"
    question: str = "Run full QA pipeline and report status"


@router.post("/run")
async def run_qa(req: QARunRequest):
    """Run the full QA & Reliability pipeline."""
    from agents.departments.cto.managers.qa.qa_director import QADirector
    agent = QADirector(UUID(req.business_id))
    result = await agent.run(req.question, {"phase": req.phase})
    return {
        "status": result.status,
        "summary": result.summary,
        "metrics": result.metrics,
        "recommendations": result.recommendations,
    }


@router.post("/workflow-test")
async def run_workflow_test(business_id: str, question: str = "Run workflow tests"):
    """Run only the Workflow Tester sub-agent."""
    from agents.departments.cto.managers.qa.workflow_tester import WorkflowTester
    agent = WorkflowTester(UUID(business_id))
    result = await agent.run(question)
    return {"status": result.status, "summary": result.summary, "metrics": result.metrics}


@router.post("/integration-test")
async def run_integration_test(business_id: str, question: str = "Test all integrations"):
    """Run only the Integration Tester sub-agent."""
    from agents.departments.cto.managers.qa.integration_tester import IntegrationTester
    agent = IntegrationTester(UUID(business_id))
    result = await agent.run(question)
    return {"status": result.status, "summary": result.summary, "metrics": result.metrics}


@router.post("/security-test")
async def run_security_test(business_id: str, question: str = "Run security checks"):
    """Run only the Security Tester sub-agent."""
    from agents.departments.cto.managers.qa.security_tester import SecurityTester
    agent = SecurityTester(UUID(business_id))
    result = await agent.run(question)
    return {"status": result.status, "summary": result.summary, "metrics": result.metrics}


@router.post("/deployment-check")
async def run_deployment_check(business_id: str, question: str = "Check deployment readiness"):
    """Run only the Deployment Validator sub-agent."""
    from agents.departments.cto.managers.qa.deployment_validator import DeploymentValidator
    agent = DeploymentValidator(UUID(business_id))
    result = await agent.run(question)
    return {
        "status": result.status,
        "summary": result.summary,
        "metrics": result.metrics,
        "deployment_ready": result.metrics.get("deployment_ready", False),
        "blockers": result.metrics.get("blockers", []),
    }


@router.get("/health/{business_id}")
async def qa_health(business_id: str):
    """Quick health check across all QA dimensions."""
    from agents.departments.cto.managers.qa.performance_monitor import PerformanceMonitor
    from agents.departments.cto.managers.qa.data_integrity_auditor import DataIntegrityAuditor
    import asyncio
    pm = PerformanceMonitor(UUID(business_id))
    da = DataIntegrityAuditor(UUID(business_id))
    pm_result, da_result = await asyncio.gather(
        pm.run("Quick performance check"),
        da.run("Quick integrity check"),
    )
    return {
        "performance": {"status": pm_result.status, "metrics": pm_result.metrics},
        "data_integrity": {"status": da_result.status, "metrics": da_result.metrics},
    }
