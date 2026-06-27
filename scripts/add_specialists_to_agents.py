"""Inject specialist consultation into each dept agent's run() method."""
import os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# For each dept agent: (path, keyword→specialist mapping)
AGENTS = {
    "agents/departments/coo/agent.py": [
        (["appointment", "booking", "schedule", "slot", "calendar", "reschedule"], "appointment_optimizer"),
        (["staff", "capacity", "workload", "utilization", "shift"], "operations_manager"),
        (["workflow", "process", "efficiency", "optimize", "operations"], "workflow_optimizer"),
    ],
    "agents/departments/cro/agent.py": [
        (["price", "pricing", "discount", "offer", "package", "cost"], "pricing_analyst"),
        (["dormant", "inactive", "reactivate", "recover", "lapsed", "lost"], "sales_outbound_strategist"),
        (["membership", "renewal", "subscription", "retain", "churn"], "offer_lead_gen_strategist"),
        (["upsell", "upgrade", "cross-sell", "revenue", "increase"], "deal_strategist"),
    ],
    "agents/departments/cmo/agent.py": [
        (["email", "campaign", "message", "sms", "send", "outreach"], "email_marketing_strategist"),
        (["lead", "prospect", "acquire", "scrape", "find"], "sales_outbound_strategist"),
        (["social", "instagram", "content", "post", "tiktok"], "content_creator"),
        (["grow", "conversion", "viral", "referral", "traffic"], "growth_hacker"),
    ],
    "agents/departments/cfo/agent.py": [
        (["forecast", "predict", "trend", "projection", "next month"], "fpa_analyst"),
        (["analyze", "revenue", "profit", "margin", "performance", "report"], "financial_analyst"),
        (["strategy", "decision", "invest", "allocate", "budget"], "chief_financial_officer"),
    ],
    "agents/departments/customer_success/agent.py": [
        (["complaint", "unhappy", "refund", "issue", "problem", "angry"], "customer_service"),
        (["review", "reputation", "rating", "google", "feedback"], "pr_communications_manager"),
        (["retain", "churn", "loyalty", "returning", "rebook"], "customer_success_manager"),
        (["experience", "satisfaction", "survey", "nps", "feeling"], "hospitality_guest_services"),
    ],
    "agents/departments/learning/agent.py": [
        (["prompt", "improve", "optimize", "hallucination", "ai response"], "prompt_engineer"),
        (["agent", "multi-agent", "pipeline", "orchestration", "delegation"], "multi_agent_systems_architect"),
        (["workflow", "n8n", "automation", "process", "failure"], "workflow_optimizer"),
    ],
    "agents/departments/cto/agent.py": [
        (["slow", "query", "database", "index", "performance", "latency"], "database_optimizer"),
        (["deploy", "docker", "vps", "server", "infrastructure", "ci"], "devops_automator"),
        (["incident", "outage", "down", "error", "critical", "crash"], "incident_response_commander"),
        (["security", "vulnerability", "breach", "credential", "leak"], "security_architect"),
        (["compliance", "hipaa", "gdpr", "tcpa", "legal", "audit"], "compliance_auditor"),
    ],
}

SPECIALIST_BLOCK_TEMPLATE = '''
        # Consult relevant specialists based on question keywords
        _q = question.lower()
        _consultations = []
{keyword_checks}        if _consultations:
            _insights = await self.consult_specialists_parallel(_consultations)
            _specialist_block = "\\n\\n## Specialist Insights\\n" + "\\n".join(
                f"### {{k.replace('_', ' ').title()}}\\n{{v}}" for k, v in _insights.items()
            )
        else:
            _specialist_block = ""
'''

INSERT_BEFORE = '        response = await self.llm.ainvoke(messages)'
INJECT_INTO_MSG = 'HumanMessage(content=f"Data: {json.dumps(state)}\\n\\nQuestion: {question}")'
INJECT_REPLACED = 'HumanMessage(content=f"Data: {json.dumps(state)}{_specialist_block}\\n\\nQuestion: {question}")'

for rel_path, mappings in AGENTS.items():
    path = os.path.join(BASE, rel_path)
    txt = open(path, encoding='utf-8').read()

    # Skip if already patched
    if '_consultations' in txt:
        print(f"  skip (already patched): {rel_path}")
        continue

    # Build keyword checks
    checks = ""
    for keywords, specialist in mappings:
        kw_list = ", ".join(f'"{k}"' for k in keywords)
        checks += f'        if any(w in _q for w in [{kw_list}]):\n'
        checks += f'            _consultations.append({{"specialist": "{specialist}", "task": question}})\n'

    specialist_block = SPECIALIST_BLOCK_TEMPLATE.format(keyword_checks=checks)

    # Insert specialist block before the LLM call
    if INSERT_BEFORE not in txt:
        print(f"  skip (no LLM call found): {rel_path}")
        continue

    txt = txt.replace(INSERT_BEFORE, specialist_block + "        " + INSERT_BEFORE)
    # Inject specialist block into the HumanMessage
    txt = txt.replace(INJECT_INTO_MSG, INJECT_REPLACED)

    open(path, 'w', encoding='utf-8').write(txt)
    print(f"  patched: {rel_path}")

print("Done")
