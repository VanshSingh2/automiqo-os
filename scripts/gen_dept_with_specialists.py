"""Regenerate dept agents with specialists consulted BEFORE building messages."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATE = '''import os
import json
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
{imports}


class {class_name}(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        managers = [{manager_list}]
        tasks = [m(self.business_id).run(question, state) for m in managers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged = {{}}
        summaries = []
        for r in results:
            if isinstance(r, AgentResponse):
                summaries.append(r.summary)
                merged.update(r.metrics or {{}})
        merged["manager_insights"] = " | ".join(s for s in summaries if s)
        return merged

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
{fetch_state}
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("{prompt_name}")
        except Exception:
            prompt = "You are the {role}. Respond with JSON: {{status, summary, metrics, recommendations}}."
        # Consult specialists before LLM call
        _q = question.lower()
        _consultations = []
{specialist_checks}        if _consultations:
            _insights = await self.consult_specialists_parallel(_consultations)
            _specialist_block = "\\n\\n## Specialist Insights\\n" + "\\n".join(
                f"### {{k.replace('_', ' ').title()}}\\n{{v}}" for k, v in _insights.items()
            )
        else:
            _specialist_block = ""
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {{json.dumps(state)}}{{_specialist_block}}\\n\\nQuestion: {{question}}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {{**state, **result.metrics}}
        return result
'''

def checks(mappings):
    lines = ""
    for keywords, specialist in mappings:
        kws = ", ".join(f'"{k}"' for k in keywords)
        lines += f'        if any(w in _q for w in [{kws}]):\n'
        lines += f'            _consultations.append({{"specialist": "{specialist}", "task": question}})\n'
    return lines

depts = [
    {
        "class_name": "COOAgent", "prompt_name": "coo", "role": "COO",
        "out": "agents/departments/coo/agent.py",
        "imports": """from agents.departments.coo.managers.appointment_manager import AppointmentManager
from agents.departments.coo.managers.crm_manager import CRMManager
from agents.departments.coo.managers.staff_manager import StaffManager
from agents.departments.coo.managers.inventory_manager import InventoryManager
from agents.departments.coo.managers.procurement_manager import ProcurementManager
from agents.departments.coo.managers.compliance_manager import ComplianceManager
from backend.memory.company import get_company_state""",
        "manager_list": "AppointmentManager, CRMManager, StaffManager, InventoryManager, ProcurementManager, ComplianceManager",
        "fetch_state": "        state = await get_company_state(self.business_id)",
        "specialists": [
            (["appointment", "booking", "schedule", "slot", "calendar", "reschedule"], "appointment_optimizer"),
            (["staff", "capacity", "workload", "utilization", "shift"], "operations_manager"),
            (["workflow", "process", "efficiency", "optimize", "operations"], "workflow_optimizer"),
        ],
    },
    {
        "class_name": "CROAgent", "prompt_name": "cro", "role": "CRO",
        "out": "agents/departments/cro/agent.py",
        "imports": """from agents.departments.cro.managers.revenue_recovery_manager import RevenueRecoveryManager
from agents.departments.cro.managers.pricing_manager import PricingManager
from agents.departments.cro.managers.membership_manager import MembershipManager
from agents.departments.cro.managers.upsell_manager import UpsellManager
from agents.departments.cro.managers.goal_manager import GoalManager
from backend.memory.customer import get_dormant_customers
from backend.memory.supabase_client import get_supabase""",
        "manager_list": "RevenueRecoveryManager, PricingManager, MembershipManager, UpsellManager, GoalManager",
        "fetch_state": """        dormant = await get_dormant_customers(self.business_id, inactive_days=30)
        sb = get_supabase()
        all_customers = sb.table("customers").select("id,tags").eq("business_id", str(self.business_id)).execute().data or []
        at_risk = [c for c in all_customers if "churn_risk" in (c.get("tags") or [])]
        state = {"dormant_30d": len(dormant), "churn_risk_count": len(at_risk)}""",
        "specialists": [
            (["price", "pricing", "discount", "offer", "package", "cost"], "pricing_analyst"),
            (["dormant", "inactive", "reactivate", "recover", "lapsed", "lost"], "sales_outbound_strategist"),
            (["membership", "renewal", "subscription", "retain", "churn"], "offer_lead_gen_strategist"),
            (["upsell", "upgrade", "cross-sell", "revenue", "increase"], "deal_strategist"),
        ],
    },
    {
        "class_name": "CMOAgent", "prompt_name": "cmo", "role": "CMO",
        "out": "agents/departments/cmo/agent.py",
        "imports": """from agents.departments.cmo.managers.campaign_manager import CampaignManager
from agents.departments.cmo.managers.content_manager import ContentManager
from agents.departments.cmo.managers.lead_manager import LeadManager
from agents.departments.cmo.managers.experiment_manager import ExperimentManager
from agents.departments.cmo.managers.customer_insights_manager import CustomerInsightsManager
from backend.memory.supabase_client import get_supabase""",
        "manager_list": "CampaignManager, ContentManager, LeadManager, ExperimentManager, CustomerInsightsManager",
        "fetch_state": """        sb = get_supabase()
        bid = str(self.business_id)
        campaigns = sb.table("campaigns").select("id,name,status,sent_count,response_count,booking_count").eq("business_id", bid).limit(10).execute().data or []
        active = [c for c in campaigns if c["status"] == "running"]
        state = {
            "active_campaigns": len(active),
            "total_campaigns": len(campaigns),
            "total_sent": sum(c.get("sent_count") or 0 for c in campaigns),
            "total_bookings_from_campaigns": sum(c.get("booking_count") or 0 for c in campaigns),
        }""",
        "specialists": [
            (["email", "campaign", "message", "sms", "send", "outreach"], "email_marketing_strategist"),
            (["lead", "prospect", "acquire", "scrape", "find"], "sales_outbound_strategist"),
            (["social", "instagram", "content", "post", "tiktok"], "content_creator"),
            (["grow", "conversion", "viral", "referral", "traffic"], "growth_hacker"),
        ],
    },
    {
        "class_name": "CFOAgent", "prompt_name": "cfo", "role": "CFO",
        "out": "agents/departments/cfo/agent.py",
        "imports": """from agents.departments.cfo.managers.analytics_manager import AnalyticsManager
from agents.departments.cfo.managers.business_planner import BusinessPlanner
from agents.departments.cfo.managers.risk_manager import RiskManager
from backend.memory.supabase_client import get_supabase
from datetime import datetime, timezone, timedelta""",
        "manager_list": "AnalyticsManager, BusinessPlanner, RiskManager",
        "fetch_state": """        sb = get_supabase()
        bid = str(self.business_id)
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()
        appts_week = sb.table("appointments").select("revenue,status").eq("business_id", bid).gte("scheduled_at", week_ago).execute().data or []
        appts_month = sb.table("appointments").select("revenue,status").eq("business_id", bid).gte("scheduled_at", month_ago).execute().data or []
        state = {
            "revenue_7d": sum(a.get("revenue") or 0 for a in appts_week if a["status"] == "completed"),
            "revenue_30d": sum(a.get("revenue") or 0 for a in appts_month if a["status"] == "completed"),
            "appts_week": len(appts_week),
            "no_shows_week": len([a for a in appts_week if a["status"] == "no_show"]),
        }""",
        "specialists": [
            (["forecast", "predict", "trend", "projection", "next month"], "fpa_analyst"),
            (["analyze", "revenue", "profit", "margin", "performance", "report"], "financial_analyst"),
            (["strategy", "decision", "invest", "allocate", "budget"], "chief_financial_officer"),
        ],
    },
    {
        "class_name": "CustomerSuccessAgent", "prompt_name": "customer_success_director", "role": "Customer Success Director",
        "out": "agents/departments/customer_success/agent.py",
        "imports": """from agents.departments.customer_success.managers.reputation_manager import ReputationManager
from agents.departments.customer_success.managers.customer_success_manager import CustomerSuccessManager
from agents.departments.customer_success.managers.loyalty_manager import LoyaltyManager
from backend.memory.supabase_client import get_supabase""",
        "manager_list": "ReputationManager, CustomerSuccessManager, LoyaltyManager",
        "fetch_state": """        sb = get_supabase()
        bid = str(self.business_id)
        open_complaints = sb.table("calls").select("id,sentiment").eq("business_id", bid).eq("sentiment", "negative").execute().data or []
        all_customers = sb.table("customers").select("id,tags").eq("business_id", bid).execute().data or []
        churn_risk = [c for c in all_customers if "churn_risk" in (c.get("tags") or [])]
        state = {"open_complaints": len(open_complaints), "churn_risk": len(churn_risk)}""",
        "specialists": [
            (["complaint", "unhappy", "refund", "issue", "problem", "angry"], "customer_service"),
            (["review", "reputation", "rating", "google", "feedback"], "pr_communications_manager"),
            (["retain", "churn", "loyalty", "returning", "rebook"], "customer_success_manager"),
            (["experience", "satisfaction", "survey", "nps", "feeling"], "hospitality_guest_services"),
        ],
    },
    {
        "class_name": "LearningDirectorAgent", "prompt_name": "learning_director", "role": "Learning Director",
        "out": "agents/departments/learning/agent.py",
        "imports": """from agents.departments.learning.managers.reflection_manager import ReflectionManager
from agents.departments.learning.managers.knowledge_manager import KnowledgeManager
from agents.departments.learning.managers.prompt_improvement_manager import PromptImprovementManager
from agents.departments.learning.managers.innovation_manager import InnovationManager
from backend.memory.supabase_client import get_supabase
from datetime import datetime, timezone, timedelta""",
        "manager_list": "ReflectionManager, KnowledgeManager, PromptImprovementManager, InnovationManager",
        "fetch_state": """        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        reflections = sb.table("reflections").select("what_happened,lesson,mistake").eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        failed_tasks = sb.table("tasks").select("workflow,error").eq("business_id", bid).eq("status", "failed").gte("created_at", week_ago).execute().data or []
        state = {
            "reflections_7d": len(reflections),
            "mistakes_7d": len([r for r in reflections if r.get("mistake")]),
            "failed_workflows_7d": len(failed_tasks),
        }""",
        "specialists": [
            (["prompt", "improve", "optimize", "hallucination", "ai response"], "prompt_engineer"),
            (["agent", "multi-agent", "pipeline", "orchestration", "delegation"], "multi_agent_systems_architect"),
            (["workflow", "n8n", "automation", "process", "failure"], "workflow_optimizer"),
        ],
    },
]

for dept in depts:
    content = TEMPLATE.format(
        class_name=dept["class_name"],
        prompt_name=dept["prompt_name"],
        role=dept["role"],
        imports=dept["imports"],
        manager_list=dept["manager_list"],
        fetch_state=dept["fetch_state"],
        specialist_checks=checks(dept["specialists"]),
    )
    path = os.path.join(BASE, dept["out"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  {dept['out']}")

print("All dept agents regenerated with specialists")
