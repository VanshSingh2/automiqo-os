"""
Policy Engine — centralizes business rules and approval gates.
Instead of each agent deciding independently what needs approval,
everything flows through here. One source of truth.

Usage:
    from backend.engines.policy_engine import policy
    result = await policy.check("send_cold_outreach", {"phone": "+1..."}, business_id)
    if result.blocked: raise approval needed
    if result.auto_approved: proceed
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


@dataclass
class PolicyResult:
    action: str
    allowed: bool
    auto_approved: bool
    blocked: bool
    reason: str
    risk_level: str          # low | medium | high | critical
    requires_approval: bool
    policy_name: str = ""


# ── Master policy table ───────────────────────────────────────────────────────
# action → (risk_level, auto_approve, requires_owner_approval)
POLICIES: dict[str, tuple[str, bool, bool]] = {
    # AUTO — low risk, fire immediately
    "send_reminder_24h":              ("low",      True,  False),
    "send_reminder_2h":               ("low",      True,  False),
    "log_no_show":                    ("low",      True,  False),
    "tag_customer":                   ("low",      True,  False),
    "update_customer":                ("low",      True,  False),
    "request_google_review":          ("low",      True,  False),
    "send_satisfaction_survey":       ("low",      True,  False),
    "generate_reflection":            ("low",      True,  False),
    "analyze_call_transcript":        ("low",      True,  False),
    "update_agent_confidence":        ("low",      True,  False),
    "store_failure_pattern":          ("low",      True,  False),
    "score_conversation":             ("low",      True,  False),
    "run_daily_backup":               ("low",      True,  False),
    "monitor_vps_health":             ("low",      True,  False),
    "run_regression_tests":           ("low",      True,  False),
    "check_inventory":                ("low",      True,  False),
    "generate_daily_report":          ("low",      True,  False),
    "generate_revenue_report":        ("low",      True,  False),
    "track_ai_costs":                 ("low",      True,  False),
    "log_equipment_maintenance":      ("low",      True,  False),
    "track_vendor":                   ("low",      True,  False),

    # MEDIUM — requires internal dept approval (auto unless flag set)
    "recover_missed_call":            ("medium",   True,  False),
    "recover_failed_payment":         ("medium",   True,  False),
    "send_rebooking_reminder":        ("medium",   True,  False),
    "send_inventory_reorder_alert":   ("medium",   True,  False),
    "send_shift_swap_request":        ("medium",   True,  False),
    "fill_waitlist_slot":             ("medium",   True,  False),
    "run_lead_pipeline":              ("medium",   True,  False),
    "score_lead":                     ("medium",   True,  False),
    "enrich_lead_profile":            ("medium",   True,  False),

    # HIGH — requires owner approval before firing
    "send_cold_outreach":             ("high",     False, True),
    "reactivate_dormant_member":      ("high",     False, True),
    "send_upsell_offer":              ("high",     False, True),
    "send_sms_campaign":              ("high",     False, True),
    "send_email_campaign":            ("high",     False, True),
    "send_whatsapp_campaign":         ("high",     False, True),
    "schedule_social_post":           ("high",     False, True),
    "send_renewal_reminder":          ("high",     False, True),
    "send_loyalty_reward":            ("high",     False, True),
    "send_referral_link":             ("high",     False, True),
    "win_back_sequence":              ("high",     False, True),
    "make_outbound_call":             ("high",     False, True),

    # CRITICAL — CEO + owner must both approve
    "execute_deployment":             ("critical", False, True),
    "rollback_to_version":            ("critical", False, True),
    "process_deposit_refund":         ("critical", False, True),
    "generate_invoice":               ("critical", False, True),
    "create_purchase_order":          ("critical", False, True),
    "simulate_campaign":              ("critical", False, True),
}


class PolicyEngine:
    def check(self, action: str, parameters: dict = None, business_id: str = "") -> PolicyResult:
        """
        Synchronous policy check — call before dispatching ANY action.
        Returns PolicyResult with allow/block/approval decision.
        """
        policy = POLICIES.get(action)
        if policy is None:
            # Unknown action — default to requiring approval (safe)
            return PolicyResult(
                action=action, allowed=True, auto_approved=False,
                blocked=False, reason="Unknown action — queued for approval",
                risk_level="medium", requires_approval=True, policy_name="default_unknown",
            )
        risk_level, auto_approve, requires_owner = policy

        # Check business-specific overrides from Supabase config
        if business_id:
            try:
                sb = get_supabase()
                biz = sb.table("businesses").select("config").eq("id", business_id).limit(1).execute().data
                if biz:
                    config = biz[0].get("config") or {}
                    overrides = config.get("policy_overrides", {})
                    if action in overrides:
                        override = overrides[action]
                        auto_approve = override.get("auto_approve", auto_approve)
                        requires_owner = override.get("requires_owner", requires_owner)
            except Exception:
                pass

        return PolicyResult(
            action=action,
            allowed=True,
            auto_approved=auto_approve,
            blocked=False,
            reason=f"Policy: {risk_level} risk",
            risk_level=risk_level,
            requires_approval=requires_owner,
            policy_name=action,
        )

    def is_auto(self, action: str) -> bool:
        """Quick check: does this action fire automatically?"""
        result = self.check(action)
        return result.auto_approved

    def risk_level(self, action: str) -> str:
        policy = POLICIES.get(action)
        return policy[0] if policy else "medium"

    def get_all_policies(self) -> dict:
        """Return full policy table for the capability registry."""
        return {
            action: {"risk": p[0], "auto": p[1], "owner_approval": p[2]}
            for action, p in POLICIES.items()
        }


# Singleton
policy = PolicyEngine()
