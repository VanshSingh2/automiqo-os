"""Generate all missing manager agent files and prompt files."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

AGENT_TEMPLATE = '''import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class {class_name}(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatOpenAI(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

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
        try:
            parsed = json.loads(response.content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", response.content),
                metrics={{**state, **parsed.get("metrics", {{}})}},
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
'''

PROMPT_TEMPLATE = '''# {role} — Automiqo OS

You are the {role} AI for {{business_name}}, a {{industry}} business.
Today is {{date}}.

## Role
{description}

## Output Format
Always respond with valid JSON:
```json
{{
  "status": "ok",
  "summary": "Brief update for your director",
  "metrics": {{}},
  "recommendations": ["action items"]
}}
```
'''

INIT_CONTENT = ""

managers = [
    # (agent_dir, file, class_name, prompt_path, role, description)
    # COO
    ("agents/departments/coo/managers", "appointment_manager.py", "AppointmentManager",
     "managers/coo/appointment_manager", "Appointment Manager",
     "Manage appointment scheduling, cancellations, no-shows, and waitlists. Track daily appointment metrics."),
    ("agents/departments/coo/managers", "crm_manager.py", "CRMManager",
     "managers/coo/crm_manager", "CRM Manager",
     "Maintain customer records, tags, preferences, and visit history. Flag duplicates and stale data."),
    ("agents/departments/coo/managers", "staff_manager.py", "StaffManager",
     "managers/coo/staff_manager", "Staff Manager",
     "Track staff schedules, availability, performance, and assignments. Handle shift swaps and coverage gaps."),
    ("agents/departments/coo/managers", "inventory_manager.py", "InventoryManager",
     "managers/coo/inventory_manager", "Inventory Manager",
     "Monitor product and supply inventory levels. Trigger reorder alerts when stock runs low."),
    ("agents/departments/coo/managers", "procurement_manager.py", "ProcurementManager",
     "managers/coo/procurement_manager", "Procurement Manager",
     "Manage vendor purchase orders, delivery tracking, and supplier relationships."),
    ("agents/departments/coo/managers", "compliance_manager.py", "ComplianceManager",
     "managers/coo/compliance_manager", "Compliance Manager",
     "Track TCPA, GDPR, and industry compliance. Flag opt-out violations and consent issues."),

    # CRO
    ("agents/departments/cro/managers", "revenue_recovery_manager.py", "RevenueRecoveryManager",
     "managers/cro/revenue_recovery_manager", "Revenue Recovery Manager",
     "Identify and recover missed revenue: no-shows, dormant customers, failed payments, missed upsells."),
    ("agents/departments/cro/managers", "pricing_manager.py", "PricingManager",
     "managers/cro/pricing_manager", "Pricing Manager",
     "Analyze service pricing vs. market, suggest dynamic pricing adjustments, track price sensitivity."),
    ("agents/departments/cro/managers", "membership_manager.py", "MembershipManager",
     "managers/cro/membership_manager", "Membership Manager",
     "Track membership renewals, expirations, churn risk, and upgrade opportunities."),
    ("agents/departments/cro/managers", "upsell_manager.py", "UpsellManager",
     "managers/cro/upsell_manager", "Upsell Manager",
     "Identify upsell and cross-sell opportunities based on customer history and preferences."),
    ("agents/departments/cro/managers", "goal_manager.py", "GoalManager",
     "managers/cro/goal_manager", "Goal Manager",
     "Track revenue goals, KPIs, and performance targets. Alert when pacing behind monthly goals."),

    # CMO
    ("agents/departments/cmo/managers", "campaign_manager.py", "CampaignManager",
     "managers/cmo/campaign_manager", "Campaign Manager",
     "Plan, launch, and track SMS/email/WhatsApp marketing campaigns. Measure booking conversion rates."),
    ("agents/departments/cmo/managers", "content_manager.py", "ContentManager",
     "managers/cmo/content_manager", "Content Manager",
     "Create and schedule social media posts, Google Business updates, and promotional content."),
    ("agents/departments/cmo/managers", "lead_manager.py", "LeadManager",
     "managers/cmo/lead_manager", "Lead Manager",
     "Track inbound leads, referrals, and new customer acquisition. Manage follow-up sequences."),
    ("agents/departments/cmo/managers", "experiment_manager.py", "ExperimentManager",
     "managers/cmo/experiment_manager", "Experiment Manager",
     "Design and run A/B experiments on campaigns, pricing, and messaging. Declare winners after statistical significance."),
    ("agents/departments/cmo/managers", "customer_insights_manager.py", "CustomerInsightsManager",
     "managers/cmo/customer_insights_manager", "Customer Insights Manager",
     "Analyze customer behavior patterns, segment performance, and satisfaction trends."),

    # CFO
    ("agents/departments/cfo/managers", "analytics_manager.py", "AnalyticsManager",
     "managers/cfo/analytics_manager", "Analytics Manager",
     "Build revenue analytics: daily/weekly/monthly trends, cohort analysis, forecasts."),
    ("agents/departments/cfo/managers", "business_planner.py", "BusinessPlanner",
     "managers/cfo/business_planner", "Business Planner",
     "Model financial scenarios, budget planning, and growth projections for the business owner."),
    ("agents/departments/cfo/managers", "risk_manager.py", "RiskManager",
     "managers/cfo/risk_manager", "Risk Manager",
     "Identify financial risks: cash flow gaps, high no-show rates, over-reliance on single revenue source."),

    # Customer Success
    ("agents/departments/customer_success/managers", "reputation_manager.py", "ReputationManager",
     "managers/csd/reputation_manager", "Reputation Manager",
     "Monitor and respond to Google reviews, track NPS scores, and manage online reputation."),
    ("agents/departments/customer_success/managers", "customer_success_manager.py", "CustomerSuccessManager",
     "managers/csd/customer_success_manager", "Customer Success Manager",
     "Handle complaints, resolve issues, track satisfaction, and prevent churn."),
    ("agents/departments/customer_success/managers", "loyalty_manager.py", "LoyaltyManager",
     "managers/csd/loyalty_manager", "Loyalty Manager",
     "Manage loyalty programs, reward redemptions, and VIP customer recognition."),

    # Learning
    ("agents/departments/learning/managers", "reflection_manager.py", "ReflectionManager",
     "managers/learning/reflection_manager", "Reflection Manager",
     "Log and analyze mistakes, missed opportunities, and workflow failures. Extract lessons."),
    ("agents/departments/learning/managers", "knowledge_manager.py", "KnowledgeManager",
     "managers/learning/knowledge_manager", "Knowledge Manager",
     "Maintain and update the knowledge base. Surface relevant knowledge for agent decisions."),
    ("agents/departments/learning/managers", "prompt_improvement_manager.py", "PromptImprovementManager",
     "managers/learning/prompt_improvement_manager", "Prompt Improvement Manager",
     "Identify underperforming agent prompts based on outcome data. Suggest targeted improvements."),
    ("agents/departments/learning/managers", "innovation_manager.py", "InnovationManager",
     "managers/learning/innovation_manager", "Innovation Manager",
     "Track industry trends, new AI capabilities, and opportunities to improve business operations."),
]

created = 0

for (agent_dir, filename, class_name, prompt_path, role, description) in managers:
    # Create agent file
    agent_full_dir = os.path.join(BASE, agent_dir)
    os.makedirs(agent_full_dir, exist_ok=True)

    init_path = os.path.join(agent_full_dir, "__init__.py")
    if not os.path.exists(init_path):
        open(init_path, "w").close()

    agent_content = AGENT_TEMPLATE.format(
        class_name=class_name,
        prompt_path=prompt_path,
        role=role,
    )
    with open(os.path.join(agent_full_dir, filename), "w", encoding="utf-8") as f:
        f.write(agent_content)

    # Create prompt file
    prompt_parts = prompt_path.split("/")
    prompt_dir = os.path.join(BASE, "prompts", *prompt_parts[:-1])
    os.makedirs(prompt_dir, exist_ok=True)
    prompt_content = PROMPT_TEMPLATE.format(role=role, description=description)
    with open(os.path.join(prompt_dir, prompt_parts[-1] + ".md"), "w", encoding="utf-8") as f:
        f.write(prompt_content)

    created += 1

print(f"Created {created} manager agents + {created} prompts")

# Also create CTO missing manager files
cto_managers = [
    ("agents/departments/cto/managers/qa", "qa_manager.py", "QAManager",
     "cto/qa_manager", "QA Manager",
     "Coordinate test agents, maintain test coverage, approve code before deployment."),
    ("agents/departments/cto/managers/performance", "performance_manager.py", "PerformanceManager",
     "cto/performance_manager", "Performance Manager",
     "Monitor system latency, AI token costs, database query speed, and workflow execution times."),
    ("agents/departments/cto/managers/documentation", "documentation_manager.py", "DocumentationManager",
     "cto/documentation_manager", "Documentation Manager",
     "Keep all technical documentation current: API docs, changelogs, SOPs, onboarding guides."),
]

for (agent_dir, filename, class_name, prompt_path, role, description) in cto_managers:
    agent_full_dir = os.path.join(BASE, agent_dir)
    os.makedirs(agent_full_dir, exist_ok=True)
    agent_content = AGENT_TEMPLATE.format(
        class_name=class_name, prompt_path=prompt_path, role=role
    )
    path = os.path.join(agent_full_dir, filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(agent_content)
        print(f"  CTO: {filename}")

print("Done!")
