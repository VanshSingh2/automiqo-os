"""
Risk Manager — assesses operational risk before any action executes.
Blocks or flags high-risk actions before they reach the dispatcher.

Risk factors:
  - Action type (policy risk level)
  - Number of customers affected
  - Financial exposure
  - Time sensitivity
  - Business hours (some actions only safe during business hours)
  - Recent failure rate for this workflow
"""
from dataclasses import dataclass
from datetime import datetime, timezone, time
from backend.engines.policy_engine import POLICIES
from backend.memory.supabase_client import get_supabase


@dataclass
class RiskAssessment:
    workflow: str
    risk_level: str          # low | medium | high | critical
    risk_score: float        # 0-100
    factors: list[str]
    recommendation: str
    block: bool
    require_approval: bool


FINANCIAL_WORKFLOWS = {
    "process_deposit_refund", "generate_invoice", "create_purchase_order",
    "recover_failed_payment", "send_payment_link", "send_renewal_reminder",
}
MASS_OUTREACH_WORKFLOWS = {
    "send_sms_campaign", "send_email_campaign", "send_whatsapp_campaign",
    "send_cold_outreach", "reactivate_dormant_member", "win_back_sequence",
}
IRREVERSIBLE_WORKFLOWS = {
    "execute_deployment", "rollback_to_version", "archive_lead",
}


class RiskManager:
    async def assess(
        self,
        business_id: str,
        workflow: str,
        parameters: dict = None,
        context: dict = None,
    ) -> RiskAssessment:
        """Full risk assessment for an action before dispatch."""
        params = parameters or {}
        factors = []
        risk_score = 0.0

        # 1. Base risk from policy table
        policy_entry = POLICIES.get(workflow)
        base_risk = policy_entry[0] if policy_entry else "medium"
        base_scores = {"low": 10, "medium": 30, "high": 60, "critical": 85}
        risk_score += base_scores.get(base_risk, 30)
        factors.append(f"Base policy risk: {base_risk}")

        # 2. Financial risk
        if workflow in FINANCIAL_WORKFLOWS:
            amount = float(params.get("amount") or params.get("reward_amount") or 0)
            if amount > 100:
                risk_score += 20
                factors.append(f"Financial exposure: ${amount:.0f}")
            elif amount > 0:
                risk_score += 10
                factors.append(f"Financial action: ${amount:.0f}")

        # 3. Mass outreach risk
        if workflow in MASS_OUTREACH_WORKFLOWS:
            limit = int(params.get("limit") or params.get("count") or 50)
            if limit > 100:
                risk_score += 25
                factors.append(f"Mass outreach: {limit} recipients")
            elif limit > 20:
                risk_score += 10
                factors.append(f"Batch outreach: {limit} recipients")

        # 4. Irreversible action
        if workflow in IRREVERSIBLE_WORKFLOWS:
            risk_score += 30
            factors.append("Irreversible action")

        # 5. Business hours check
        now_hour = datetime.now(timezone.utc).hour
        est_hour = (now_hour - 5) % 24
        if workflow in MASS_OUTREACH_WORKFLOWS and not (8 <= est_hour <= 20):
            risk_score += 15
            factors.append(f"Outside business hours ({est_hour}:00 EST)")

        # 6. Recent failure rate for this workflow
        try:
            sb = get_supabase()
            from datetime import timedelta
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            tasks = sb.table("tasks").select("status").eq("business_id", business_id)\
                .eq("workflow", workflow).gte("created_at", since).execute().data or []
            if tasks:
                fail_rate = sum(1 for t in tasks if t["status"] == "failed") / len(tasks)
                if fail_rate > 0.3:
                    risk_score += 20
                    factors.append(f"Recent failure rate: {fail_rate:.0%}")
        except Exception:
            pass

        # Cap at 100
        risk_score = min(risk_score, 100)

        # Determine final risk level
        if risk_score >= 80:
            final_risk = "critical"
        elif risk_score >= 60:
            final_risk = "high"
        elif risk_score >= 30:
            final_risk = "medium"
        else:
            final_risk = "low"

        block = risk_score >= 95
        require_approval = risk_score >= 60

        if block:
            recommendation = "BLOCKED — risk score too high. Manual review required."
        elif require_approval:
            recommendation = f"Requires owner approval before execution (risk: {final_risk})."
        else:
            recommendation = f"Safe to proceed automatically (risk: {final_risk})."

        return RiskAssessment(
            workflow=workflow,
            risk_level=final_risk,
            risk_score=round(risk_score, 1),
            factors=factors,
            recommendation=recommendation,
            block=block,
            require_approval=require_approval,
        )

    async def assess_batch(self, business_id: str, actions: list[dict]) -> list[RiskAssessment]:
        """Assess multiple actions at once."""
        import asyncio
        return list(await asyncio.gather(*[
            self.assess(business_id, a.get("workflow", ""), a.get("parameters", {}))
            for a in actions
        ]))


# Singleton
risk_manager = RiskManager()
