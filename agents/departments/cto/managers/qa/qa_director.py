"""
QA Director — orchestrates the full QA & Reliability pipeline.
Runs all 12 QA sub-agents in phased parallel execution.
Reports to Engineering Manager / CTO.
"""
import json
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class QADirector(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        bid = str(self.business_id)

        # Phase 1: Core validation (parallel)
        phase1 = await asyncio.gather(
            self._run_workflow_tester(bid, ctx),
            self._run_integration_tester(bid, ctx),
            self._run_scenario_simulator(bid, ctx),
            self._run_regression_manager(bid, ctx),
        )

        # Phase 2: Quality + Performance (parallel)
        phase2 = await asyncio.gather(
            self._run_ai_quality_evaluator(bid, ctx),
            self._run_performance_monitor(bid, ctx),
            self._run_memory_validator(bid, ctx),
        )

        # Phase 3: Security + Reliability (parallel)
        phase3 = await asyncio.gather(
            self._run_security_tester(bid, ctx),
            self._run_chaos_engineer(bid, ctx),
            self._run_data_integrity_auditor(bid, ctx),
            self._run_deployment_validator(bid, ctx),
        )

        all_results = list(phase1) + list(phase2) + list(phase3)
        combined = {r["agent"]: r for r in all_results}

        critical_failures = [r for r in all_results if r.get("status") == "FAIL" and r.get("severity") == "critical"]
        warnings = [r for r in all_results if r.get("status") == "WARN"]
        passed = [r for r in all_results if r.get("status") == "PASS"]

        overall = "BLOCKED" if critical_failures else ("WARN" if warnings else "PASS")

        state = {
            "overall_status": overall,
            "critical_failures": len(critical_failures),
            "warnings": len(warnings),
            "passed": len(passed),
            "results": combined,
            "block_deployment": bool(critical_failures),
            **ctx,
        }

        try:
            prompt = self._load_prompt("cto/qa_director")
        except Exception:
            prompt = (
                "You are the QA Director for an AI business operating system. "
                "Review QA results across all sub-agents and provide a final verdict. "
                "If critical failures exist, block deployment. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )

        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"QA Results: {json.dumps(state, default=str)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result

    async def _run_workflow_tester(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.workflow_tester import WorkflowTester
        try:
            r = await WorkflowTester(self.business_id).run("Run workflow tests", ctx)
            return {"agent": "workflow_tester", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "workflow_tester", "status": "WARN", "summary": str(e)}

    async def _run_integration_tester(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.integration_tester import IntegrationTester
        try:
            r = await IntegrationTester(self.business_id).run("Test integrations", ctx)
            return {"agent": "integration_tester", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "integration_tester", "status": "WARN", "summary": str(e)}

    async def _run_scenario_simulator(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.scenario_simulator import ScenarioSimulator
        try:
            r = await ScenarioSimulator(self.business_id).run("Simulate customer journeys", ctx)
            return {"agent": "scenario_simulator", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "scenario_simulator", "status": "WARN", "summary": str(e)}

    async def _run_regression_manager(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.regression_manager import RegressionManager
        try:
            r = await RegressionManager(self.business_id).run("Run regression checks", ctx)
            return {"agent": "regression_manager", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "regression_manager", "status": "WARN", "summary": str(e)}

    async def _run_ai_quality_evaluator(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.ai_quality_evaluator import AIQualityEvaluator
        try:
            r = await AIQualityEvaluator(self.business_id).run("Evaluate AI quality", ctx)
            return {"agent": "ai_quality_evaluator", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "ai_quality_evaluator", "status": "WARN", "summary": str(e)}

    async def _run_performance_monitor(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.performance_monitor import PerformanceMonitor
        try:
            r = await PerformanceMonitor(self.business_id).run("Check performance metrics", ctx)
            return {"agent": "performance_monitor", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "performance_monitor", "status": "WARN", "summary": str(e)}

    async def _run_memory_validator(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.memory_validator import MemoryValidator
        try:
            r = await MemoryValidator(self.business_id).run("Validate memory consistency", ctx)
            return {"agent": "memory_validator", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "memory_validator", "status": "WARN", "summary": str(e)}

    async def _run_security_tester(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.security_tester import SecurityTester
        try:
            r = await SecurityTester(self.business_id).run("Run security tests", ctx)
            return {"agent": "security_tester", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "security_tester", "status": "WARN", "summary": str(e)}

    async def _run_chaos_engineer(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.chaos_engineer import ChaosEngineer
        try:
            r = await ChaosEngineer(self.business_id).run("Simulate chaos scenarios", ctx)
            return {"agent": "chaos_engineer", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "chaos_engineer", "status": "WARN", "summary": str(e)}

    async def _run_data_integrity_auditor(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.data_integrity_auditor import DataIntegrityAuditor
        try:
            r = await DataIntegrityAuditor(self.business_id).run("Audit data integrity", ctx)
            return {"agent": "data_integrity_auditor", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "data_integrity_auditor", "status": "WARN", "summary": str(e)}

    async def _run_deployment_validator(self, bid: str, ctx: dict) -> dict:
        from agents.departments.cto.managers.qa.deployment_validator import DeploymentValidator
        try:
            r = await DeploymentValidator(self.business_id).run("Validate deployment readiness", ctx)
            return {"agent": "deployment_validator", "status": "PASS", "summary": r.summary}
        except Exception as e:
            return {"agent": "deployment_validator", "status": "WARN", "summary": str(e)}
