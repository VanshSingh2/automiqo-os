"""Regenerate all manager agent files cleanly with _parse_response."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AGENT_TEMPLATE = '''import os
import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class {class_name}(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        state = context or {{}}
        try:
            prompt = self._load_prompt("{prompt_path}")
        except Exception:
            prompt = "You are the {role}. Respond with JSON: {{status, summary, metrics, recommendations}}."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {{json.dumps(state)}}\\n\\nQuestion: {{question}}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
'''

managers = [
    ("agents/departments/coo/managers", "appointment_manager.py", "AppointmentManager", "managers/coo/appointment_manager", "Appointment Manager"),
    ("agents/departments/coo/managers", "crm_manager.py", "CRMManager", "managers/coo/crm_manager", "CRM Manager"),
    ("agents/departments/coo/managers", "staff_manager.py", "StaffManager", "managers/coo/staff_manager", "Staff Manager"),
    ("agents/departments/coo/managers", "inventory_manager.py", "InventoryManager", "managers/coo/inventory_manager", "Inventory Manager"),
    ("agents/departments/coo/managers", "procurement_manager.py", "ProcurementManager", "managers/coo/procurement_manager", "Procurement Manager"),
    ("agents/departments/coo/managers", "compliance_manager.py", "ComplianceManager", "managers/coo/compliance_manager", "Compliance Manager"),
    ("agents/departments/cro/managers", "revenue_recovery_manager.py", "RevenueRecoveryManager", "managers/cro/revenue_recovery_manager", "Revenue Recovery Manager"),
    ("agents/departments/cro/managers", "pricing_manager.py", "PricingManager", "managers/cro/pricing_manager", "Pricing Manager"),
    ("agents/departments/cro/managers", "membership_manager.py", "MembershipManager", "managers/cro/membership_manager", "Membership Manager"),
    ("agents/departments/cro/managers", "upsell_manager.py", "UpsellManager", "managers/cro/upsell_manager", "Upsell Manager"),
    ("agents/departments/cro/managers", "goal_manager.py", "GoalManager", "managers/cro/goal_manager", "Goal Manager"),
    ("agents/departments/cmo/managers", "campaign_manager.py", "CampaignManager", "managers/cmo/campaign_manager", "Campaign Manager"),
    ("agents/departments/cmo/managers", "content_manager.py", "ContentManager", "managers/cmo/content_manager", "Content Manager"),
    ("agents/departments/cmo/managers", "lead_manager.py", "LeadManager", "managers/cmo/lead_manager", "Lead Manager"),
    ("agents/departments/cmo/managers", "experiment_manager.py", "ExperimentManager", "managers/cmo/experiment_manager", "Experiment Manager"),
    ("agents/departments/cmo/managers", "customer_insights_manager.py", "CustomerInsightsManager", "managers/cmo/customer_insights_manager", "Customer Insights Manager"),
    ("agents/departments/cfo/managers", "analytics_manager.py", "AnalyticsManager", "managers/cfo/analytics_manager", "Analytics Manager"),
    ("agents/departments/cfo/managers", "business_planner.py", "BusinessPlanner", "managers/cfo/business_planner", "Business Planner"),
    ("agents/departments/cfo/managers", "risk_manager.py", "RiskManager", "managers/cfo/risk_manager", "Risk Manager"),
    ("agents/departments/customer_success/managers", "reputation_manager.py", "ReputationManager", "managers/csd/reputation_manager", "Reputation Manager"),
    ("agents/departments/customer_success/managers", "customer_success_manager.py", "CustomerSuccessManager", "managers/csd/customer_success_manager", "Customer Success Manager"),
    ("agents/departments/customer_success/managers", "loyalty_manager.py", "LoyaltyManager", "managers/csd/loyalty_manager", "Loyalty Manager"),
    ("agents/departments/learning/managers", "reflection_manager.py", "ReflectionManager", "managers/learning/reflection_manager", "Reflection Manager"),
    ("agents/departments/learning/managers", "knowledge_manager.py", "KnowledgeManager", "managers/learning/knowledge_manager", "Knowledge Manager"),
    ("agents/departments/learning/managers", "prompt_improvement_manager.py", "PromptImprovementManager", "managers/learning/prompt_improvement_manager", "Prompt Improvement Manager"),
    ("agents/departments/learning/managers", "innovation_manager.py", "InnovationManager", "managers/learning/innovation_manager", "Innovation Manager"),
    ("agents/departments/cto/managers/qa", "qa_manager.py", "QAManager", "cto/qa_manager", "QA Manager"),
    ("agents/departments/cto/managers/performance", "performance_manager.py", "PerformanceManager", "cto/performance_manager", "Performance Manager"),
    ("agents/departments/cto/managers/documentation", "documentation_manager.py", "DocumentationManager", "cto/documentation_manager", "Documentation Manager"),
]

for (agent_dir, filename, class_name, prompt_path, role) in managers:
    content = AGENT_TEMPLATE.format(class_name=class_name, prompt_path=prompt_path, role=role)
    path = os.path.join(BASE, agent_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print(f"Regenerated {len(managers)} manager agents cleanly")

# Also fix CTO stub agents
CTO_STUBS_DIR = os.path.join(BASE, "agents/departments/cto/managers")
cto_stubs = []
for root, dirs, files in os.walk(CTO_STUBS_DIR):
    for f in files:
        if not f.endswith('.py') or f == '__init__.py': continue
        # skip the ones we already regenerated above
        already = any(f == m[1] for m in managers)
        if already: continue
        path = os.path.join(root, f)
        txt = open(path, encoding='utf-8').read()
        # Only fix if it has the corrupted block
        if '_m=__import__' in txt or 'import re as _re' in txt:
            # Simple: just replace the entire response handling
            import re
            new = re.sub(
                r'        response = await self\.llm\.ainvoke\(messages\)\n.*',
                '        response = await self.llm.ainvoke(messages)\n        return self._parse_response(response.content)\n',
                txt, flags=re.DOTALL
            )
            if new != txt:
                open(path, 'w', encoding='utf-8').write(new)
                cto_stubs.append(f)

print(f"Fixed {len(cto_stubs)} CTO stub agents: {cto_stubs}")
