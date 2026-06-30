"""
Manager Pulse — gives every manager its own heartbeat.

Instead of only waking up when their department head runs, each manager
periodically (on its own staggered cadence) does a short "shift":

    1. recalls what it remembers about its area
    2. proactively thinks about whether anything needs attention right now
    3. if so, flags it to its department head in the team chat
    4. remembers what it observed so the team has shared context tomorrow

This is what makes the org feel alive — 32 managers each on their own clock,
not 7 departments waking once a day.

COST NOTE: each pulse makes one cheap LLM call (gpt-4o-mini by default). Cost is
controlled by the cadence (MANAGER_PULSE_INTERVAL_MINUTES) and the global switch
MANAGER_AUTONOMY=false. Disabled managers are skipped entirely (no LLM call).
"""
from __future__ import annotations
import importlib
from datetime import datetime, timezone
from uuid import UUID


# Every manager -> the agent class that does its thinking.
MANAGER_REGISTRY: dict[str, str] = {
    # COO
    "coo.appointments": "agents.departments.coo.managers.appointment_manager.AppointmentManager",
    "coo.staff": "agents.departments.coo.managers.staff_manager.StaffManager",
    "coo.inventory": "agents.departments.coo.managers.inventory_manager.InventoryManager",
    "coo.procurement": "agents.departments.coo.managers.procurement_manager.ProcurementManager",
    "coo.compliance": "agents.departments.coo.managers.compliance_manager.ComplianceManager",
    "coo.crm": "agents.departments.coo.managers.crm_manager.CRMManager",
    # CMO
    "cmo.lead": "agents.departments.cmo.managers.lead_manager.LeadManager",
    "cmo.campaign": "agents.departments.cmo.managers.campaign_manager.CampaignManager",
    "cmo.content": "agents.departments.cmo.managers.content_manager.ContentManager",
    "cmo.customer_insights": "agents.departments.cmo.managers.customer_insights_manager.CustomerInsightsManager",
    "cmo.experiment": "agents.departments.cmo.managers.experiment_manager.ExperimentManager",
    # CRO
    "cro.revenue_recovery": "agents.departments.cro.managers.revenue_recovery_manager.RevenueRecoveryManager",
    "cro.upsell": "agents.departments.cro.managers.upsell_manager.UpsellManager",
    "cro.membership": "agents.departments.cro.managers.membership_manager.MembershipManager",
    "cro.pricing": "agents.departments.cro.managers.pricing_manager.PricingManager",
    "cro.goal": "agents.departments.cro.managers.goal_manager.GoalManager",
    # CFO
    "cfo.analytics": "agents.departments.cfo.managers.analytics_manager.AnalyticsManager",
    "cfo.business_planner": "agents.departments.cfo.managers.business_planner.BusinessPlanner",
    "cfo.risk": "agents.departments.cfo.managers.risk_manager.RiskManager",
    # CTO
    "cto.devops": "agents.departments.cto.managers.devops.devops_manager.DevOpsManager",
    "cto.documentation": "agents.departments.cto.managers.documentation.documentation_manager.DocumentationManager",
    "cto.engineering": "agents.departments.cto.managers.engineering.engineering_manager.EngineeringManager",
    "cto.performance": "agents.departments.cto.managers.performance.performance_manager.PerformanceManager",
    "cto.qa": "agents.departments.cto.managers.qa.qa_manager.QAManager",
    "cto.security": "agents.departments.cto.managers.security.security_manager.SecurityManager",
    # CSD
    "csd.customer_success": "agents.departments.customer_success.managers.customer_success_manager.CustomerSuccessManager",
    "csd.loyalty": "agents.departments.customer_success.managers.loyalty_manager.LoyaltyManager",
    "csd.reputation": "agents.departments.customer_success.managers.reputation_manager.ReputationManager",
    # Learning
    "learning.reflection": "agents.departments.learning.managers.reflection_manager.ReflectionManager",
    "learning.knowledge": "agents.departments.learning.managers.knowledge_manager.KnowledgeManager",
    "learning.innovation": "agents.departments.learning.managers.innovation_manager.InnovationManager",
    "learning.prompt_improvement": "agents.departments.learning.managers.prompt_improvement_manager.PromptImprovementManager",
}

# Phrases that mean "nothing needed" — we won't spam the team chat for these.
_QUIET = ("all clear", "no action", "nothing needed", "nothing to report",
          "all good", "all is well", "no issues", "looks healthy", "no concerns")


def all_manager_keys() -> list[str]:
    return list(MANAGER_REGISTRY.keys())


def _load_class(path: str):
    module_path, class_name = path.rsplit(".", 1)
    return getattr(importlib.import_module(module_path), class_name)


def _is_quiet(text: str) -> bool:
    t = (text or "").lower()
    return any(p in t for p in _QUIET)


async def run_manager_pulse(business_id: str, manager_key: str) -> dict:
    """One autonomous 'shift' for a single manager. Best-effort; never raises."""
    from backend.engines.business_blueprint import (
        is_manager_enabled, member_display, MANAGER_DESCRIPTIONS, HEAD_NAMES,
    )
    bid = str(business_id)
    dept = manager_key.split(".", 1)[0]
    manager = manager_key.split(".", 1)[1] if "." in manager_key else ""

    # Load this business's config and skip if the manager is switched off.
    try:
        from backend.memory.supabase_client import get_supabase
        _biz = get_supabase().table("businesses").select("config").eq("id", bid).limit(1).execute().data
        config = (_biz[0].get("config") if _biz else {}) or {}
    except Exception:
        config = {}
    if not is_manager_enabled(config, dept, manager):
        return {"manager": manager_key, "skipped": True, "reason": "disabled"}

    name = member_display(manager_key)
    desc = MANAGER_DESCRIPTIONS.get(manager_key, "your area")
    head = HEAD_NAMES.get(dept, dept.upper())
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 1) Recall what this manager remembers.
    try:
        from backend.autonomous.work_memory import recall_block
        recalled = await recall_block(bid, name, f"{desc} {manager}")
    except Exception:
        recalled = ""

    # 2) Proactively think about the area.
    cls_path = MANAGER_REGISTRY.get(manager_key)
    if not cls_path:
        return {"manager": manager_key, "skipped": True, "reason": "no_agent"}

    question = (
        f"Proactive check ({date}): you are the {name}. Your job: {desc} "
        f"Review your area for this business right now. If something needs attention, "
        f"say briefly what it is and recommend ONE specific next step. "
        f"If everything is fine, reply exactly 'All clear'. Keep it to 1-2 sentences."
        f"{recalled}"
    )
    try:
        agent = _load_class(cls_path)(UUID(bid))
        resp = await agent.run(question)
        thought = (getattr(resp, "summary", "") or "").strip()
    except Exception as e:
        return {"manager": manager_key, "error": str(e)}

    if not thought:
        return {"manager": manager_key, "quiet": True}

    quiet = _is_quiet(thought)

    # 3) Remember the observation (only when there's something worth keeping).
    if not quiet:
        try:
            from backend.autonomous.work_memory import remember_summary
            await remember_summary(bid, name, f"Proactive note: {thought}", category="manager_pulse")
        except Exception:
            pass

        # 4) Flag it to the department head in the team chat.
        try:
            from backend.events.agent_chat import post_team_message
            await post_team_message(
                bid, from_agent=name,
                message=f"@{head} {thought}",
                to_agent=head, category="alert",
            )
        except Exception:
            pass

    return {"manager": manager_key, "quiet": quiet, "thought": thought[:200]}
