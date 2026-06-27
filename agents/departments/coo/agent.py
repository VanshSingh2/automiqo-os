import os
import json
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from agents.departments.coo.managers.appointment_manager import AppointmentManager
from agents.departments.coo.managers.crm_manager import CRMManager
from agents.departments.coo.managers.staff_manager import StaffManager
from agents.departments.coo.managers.inventory_manager import InventoryManager
from agents.departments.coo.managers.procurement_manager import ProcurementManager
from agents.departments.coo.managers.compliance_manager import ComplianceManager
from backend.memory.company import get_company_state


class COOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        managers = [AppointmentManager, CRMManager, StaffManager, InventoryManager, ProcurementManager, ComplianceManager]
        tasks = [m(self.business_id).run(question, state) for m in managers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged = {}
        summaries = []
        for r in results:
            if isinstance(r, AgentResponse):
                summaries.append(r.summary)
                merged.update(r.metrics or {})
        merged["manager_insights"] = " | ".join(s for s in summaries if s)
        return merged

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        state = await get_company_state(self.business_id)
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("coo")
        except Exception:
            prompt = "You are the COO. Respond with JSON: {status, summary, metrics, recommendations}."
        # Consult specialists before LLM call
        _q = question.lower()
        _consultations = []
        if any(w in _q for w in ["appointment", "booking", "schedule", "slot", "calendar", "reschedule"]):
            _consultations.append({"specialist": "appointment_optimizer", "task": question})
        if any(w in _q for w in ["staff", "capacity", "workload", "utilization", "shift"]):
            _consultations.append({"specialist": "operations_manager", "task": question})
        if any(w in _q for w in ["workflow", "process", "efficiency", "optimize", "operations"]):
            _consultations.append({"specialist": "workflow_optimizer", "task": question})
        if _consultations:
            _insights = await self.consult_specialists_parallel(_consultations)
            _specialist_block = "\n\n## Specialist Insights\n" + "\n".join(
                f"### {k.replace('_', ' ').title()}\n{v}" for k, v in _insights.items()
            )
        else:
            _specialist_block = ""
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}{_specialist_block}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
