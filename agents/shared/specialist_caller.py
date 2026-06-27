"""Specialist Caller — lets any manager consult a specialist expert before deciding."""
import os
import json
import asyncio
from pathlib import Path
from typing import Optional
from openai import AsyncOpenAI


SPECIALIST_REGISTRY = {
    # Operations
    "operations_manager": {"file": "specialized/operations-manager.md", "use_when": "optimizing processes, scheduling efficiency, capacity"},
    "appointment_optimizer": {"file": "specialized/operations-manager.md", "use_when": "appointment booking, no-shows, calendar gaps"},
    "customer_success_manager": {"file": "specialized/customer-success-manager.md", "use_when": "churn, retention, rebooking, satisfaction"},
    "workflow_optimizer": {"file": "testing/testing-workflow-optimizer.md", "use_when": "workflow efficiency, process improvement, n8n"},
    # Revenue
    "pricing_analyst": {"file": "specialized/specialized-pricing-analyst.md", "use_when": "pricing, discounts, packages, upsell pricing"},
    "sales_outbound_strategist": {"file": "sales/sales-outbound-strategist.md", "use_when": "dormant customers, cold outreach, reactivation"},
    "deal_strategist": {"file": "sales/sales-deal-strategist.md", "use_when": "closing high-value leads, objections, conversion"},
    "offer_lead_gen_strategist": {"file": "sales/sales-offer-lead-gen-strategist.md", "use_when": "membership offers, promotions, lead magnets"},
    # Marketing
    "email_marketing_strategist": {"file": "marketing/marketing-email-strategist.md", "use_when": "email campaigns, drip sequences, SMS copy"},
    "content_creator": {"file": "marketing/marketing-content-creator.md", "use_when": "social posts, SMS copy, promotional content"},
    "growth_hacker": {"file": "marketing/marketing-growth-hacker.md", "use_when": "bookings growth, referrals, conversion rate"},
    "social_media_strategist": {"file": "marketing/marketing-social-media-strategist.md", "use_when": "social media, Instagram, TikTok campaigns"},
    "pr_communications_manager": {"file": "marketing/marketing-pr-communications-manager.md", "use_when": "reputation, complaints going public, crisis"},
    # Customer Success
    "customer_service": {"file": "specialized/customer-service.md", "use_when": "complaints, de-escalation, issue resolution"},
    "hospitality_guest_services": {"file": "specialized/hospitality-guest-services.md", "use_when": "med spa/salon experience, guest satisfaction"},
    # Finance
    "financial_analyst": {"file": "finance/finance-financial-analyst.md", "use_when": "revenue analysis, performance, financial trends"},
    "fpa_analyst": {"file": "finance/finance-fpa-analyst.md", "use_when": "forecasting, budgeting, variance analysis"},
    "chief_financial_officer": {"file": "specialized/chief-financial-officer.md", "use_when": "major financial decisions, cash flow strategy"},
    # Engineering
    "database_optimizer": {"file": "engineering/engineering-database-optimizer.md", "use_when": "slow queries, indexes, schema changes"},
    "devops_automator": {"file": "engineering/engineering-devops-automator.md", "use_when": "deployment, Docker, VPS, infrastructure"},
    "incident_response_commander": {"file": "engineering/engineering-incident-response-commander.md", "use_when": "outages, production incidents, critical bugs"},
    "security_architect": {"file": "security/security-architect.md", "use_when": "security architecture, threat modeling"},
    "compliance_auditor": {"file": "security/security-compliance-auditor.md", "use_when": "HIPAA, GDPR, TCPA, compliance"},
    "prompt_engineer": {"file": "engineering/engineering-prompt-engineer.md", "use_when": "agent prompts, hallucinations, LLM optimization"},
    "multi_agent_systems_architect": {"file": "engineering/engineering-multi-agent-systems-architect.md", "use_when": "agent pipelines, orchestration, failure recovery"},
    # Strategy
    "business_strategist": {"file": "specialized/business-strategist.md", "use_when": "market expansion, competitive positioning"},
    "product_manager": {"file": "product/product-manager.md", "use_when": "feature planning, product roadmap"},
    # Analytics
    "executive_summary_generator": {"file": "support/support-executive-summary-generator.md", "use_when": "morning briefing, weekly summaries, C-suite reports"},
    "analytics_reporter": {"file": "support/support-analytics-reporter.md", "use_when": "KPI tracking, dashboards, business intelligence"},
}


class SpecialistCaller:
    def __init__(self, library_path: str = "specialist_library"):
        self.library_path = Path(library_path)
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

    def _load_prompt(self, specialist_key: str) -> Optional[str]:
        if specialist_key not in SPECIALIST_REGISTRY:
            return None
        path = self.library_path / SPECIALIST_REGISTRY[specialist_key]["file"]
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def list_available(self, keyword: str = None) -> list:
        results = []
        for key, info in SPECIALIST_REGISTRY.items():
            path = self.library_path / info["file"]
            if not keyword or keyword.lower() in info["use_when"].lower():
                results.append({"key": key, "use_when": info["use_when"], "available": path.exists()})
        return results

    async def consult(self, specialist: str, task: str, context: dict = {}) -> str:
        prompt = self._load_prompt(specialist)
        if not prompt:
            return f"Specialist '{specialist}' not available."
        ctx = json.dumps(context, indent=2) if context else "No context."
        try:
            resp = await self.client.chat.completions.create(
                model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1] or "gpt-4o-mini",
                max_tokens=800,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Business Context:\n{ctx}\n\nTask:\n{task}\n\nBe concise and tactical."},
                ],
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"Specialist consultation failed: {e}"

    async def consult_multiple(self, consultations: list, context: dict = {}) -> dict:
        tasks = [self.consult(c["specialist"], c["task"], context) for c in consultations]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {c["specialist"]: (str(r) if isinstance(r, Exception) else r)
                for c, r in zip(consultations, results)}
