"""Scenario Simulator — simulates complete customer journeys end-to-end."""
import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse

CUSTOMER_JOURNEYS = [
    "Lead discovery → Cold outreach → Booking → Appointment reminder → Visit → Review request → Referral",
    "Missed call → Vapi callback → Booking → 2h reminder → Visit → Satisfaction survey",
    "Dormant customer → Reactivation SMS → Rebook → Loyalty reward",
    "New lead → Score → Tier A → AI SDR outreach → Booking",
    "Failed payment → Recovery workflow → Retry → Success → Membership renewal",
]


class ScenarioSimulator(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            customers = sb.table("customers").select("id,name,tags").eq("business_id", str(self.business_id)).limit(5).execute().data or []
            appointments = sb.table("appointments").select("id,status").eq("business_id", str(self.business_id)).limit(20).execute().data or []
            leads = sb.table("leads").select("id,status,score").eq("business_id", str(self.business_id)).limit(10).execute().data or []
        except Exception:
            customers, appointments, leads = [], [], []
        state = {
            "journeys_to_test": CUSTOMER_JOURNEYS,
            "sample_customers": len(customers),
            "recent_appointments": len(appointments),
            "active_leads": len(leads),
            "simulation_mode": "dry_run",
        }
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Scenario Simulator for an AI business OS. "
                "Evaluate whether all customer journey touchpoints are connected and working. "
                "Identify broken handoffs between workflows. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
