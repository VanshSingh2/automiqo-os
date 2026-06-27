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
        """Run all sub-managers in parallel and merge their summaries."""
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
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
