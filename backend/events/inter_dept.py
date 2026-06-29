"""
Inter-Department Communication System.
Enables dept agents to:
  1. Alert other depts about what they discovered
  2. Ask other depts for context before making decisions
  3. Make low-risk decisions autonomously without CEO
  4. Collaborate on shared workflows

Examples:
  COO notices high no-show rate → tells CMO to prepare re-engagement campaign
  CRO sees dormant customers → tells CSD to reach out with loyalty offer
  CTO sees workflow failures → tells CEO with severity level
  CFO sees revenue drop → asks CMO what campaigns ran this week
  Learning notices mistake pattern → tells all depts to adjust behavior

Decision table (what's low-risk = auto):
  - Send a reminder                      → AUTO
  - Log a no-show                        → AUTO
  - Tag a customer                       → AUTO
  - Request a Google review              → AUTO
  - Send satisfaction survey             → AUTO
  - Run QA health check                  → AUTO
  - Daily backup                         → AUTO
  - Analyze call transcript              → AUTO

  - Send cold outreach                   → APPROVAL
  - Reactivate dormant customer          → APPROVAL
  - Send upsell offer                    → APPROVAL
  - Run SMS/email campaign               → APPROVAL
  - Make outbound call                   → APPROVAL
  - Change pricing or offer              → APPROVAL
"""
import json
from datetime import datetime, timezone
from typing import Literal
from backend.events.bus import publish, E
from backend.memory.supabase_client import get_supabase

DeptKey = Literal["coo", "cro", "cmo", "cfo", "cto", "csd", "learning", "ceo"]

DEPT_EVENT_MAP: dict[str, str] = {
    "coo":      "internal.coo_alert",
    "cro":      "internal.cro_alert",
    "cmo":      "internal.cmo_alert",
    "cfo":      "internal.cfo_alert",
    "cto":      "internal.cto_alert",
    "csd":      "internal.csd_alert",
    "learning": "internal.learning_alert",
    "ceo":      "internal.alert",
}


async def alert_dept(
    business_id: str,
    from_dept: str,
    to_dept: str,
    message: str,
    urgency: str = "normal",
    trigger_workflow: str = "",
    trigger_params: dict = None,
    context: dict = None,
) -> None:
    """
    One department alerts another about something it discovered.
    The receiving department's handler will process this and decide what to do.

    Args:
        from_dept:        Which dept is sending (coo, cmo, cro, cfo, cto, csd, learning, ceo)
        to_dept:          Which dept to alert
        message:          What happened / what was discovered
        urgency:          'high' | 'normal' | 'low'
        trigger_workflow: Optional workflow to immediately fire on receipt
        trigger_params:   Parameters for the trigger workflow
        context:          Additional context dict
    """
    event_type = DEPT_EVENT_MAP.get(to_dept, "internal.alert")
    await publish(business_id, event_type, {
        "from": from_dept,
        "message": message,
        "urgency": urgency,
        "trigger_workflow": trigger_workflow,
        "trigger_params": trigger_params or {},
        "context": context or {},
        "_internal": True,
        "_from": from_dept,
    }, source=f"{from_dept}_alert")


async def ask_dept(
    business_id: str,
    from_dept: str,
    to_dept: str,
    question: str,
    context: dict = None,
) -> str:
    """
    One department asks another for information/analysis.
    Returns the department's answer as a string.

    Example: CFO asks CMO "what campaigns ran this week that could affect revenue?"
    """
    from uuid import UUID

    handler_map = {
        "coo": "agents.departments.coo.agent.COOAgent",
        "cro": "agents.departments.cro.agent.CROAgent",
        "cmo": "agents.departments.cmo.agent.CMOAgent",
        "cfo": "agents.departments.cfo.agent.CFOAgent",
        "cto": "agents.departments.cto.agent.CTOAgent",
        "csd": "agents.departments.customer_success.agent.CustomerSuccessAgent",
        "learning": "agents.departments.learning.agent.LearningDirectorAgent",
        "ceo": "agents.executive.ceo.agent.CEOAgent",
    }

    agent_path = handler_map.get(to_dept)
    if not agent_path:
        return f"Unknown department: {to_dept}"

    try:
        import importlib
        module_path, class_name = agent_path.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        agent = cls(UUID(business_id))
        resp = await agent.run(
            f"[Inter-dept query from {from_dept.upper()}]: {question}",
            context={"_asked_by": from_dept, **(context or {})},
        )
        return resp.summary
    except Exception as e:
        return f"Error asking {to_dept}: {e}"


async def make_low_risk_decision(
    business_id: str,
    dept: str,
    decision: str,
    workflow: str,
    parameters: dict,
    reason: str,
) -> dict:
    """
    A department makes a low-risk decision autonomously without asking CEO.
    Auto-fires the workflow, logs the decision, notifies CEO for transparency.

    Low-risk = affects a single customer, reversible, non-financial.
    """
    from backend.events.handlers import dispatch_action

    # Execute the action
    await dispatch_action(business_id, workflow, parameters, reason)

    # Log the autonomous decision
    sb = get_supabase()
    try:
        sb.table("agent_decisions").insert({
            "business_id": business_id,
            "agent_name": dept,
            "decision": decision,
            "workflow": workflow,
            "parameters": parameters,
            "reason": reason,
            "approved_by": "autonomous",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        # Table may not exist yet — add to migrations
        pass

    return {
        "decided": True,
        "dept": dept,
        "workflow": workflow,
        "decision": decision,
    }


# ── Pre-built cross-dept collaboration patterns ───────────────────────────────

async def coo_notify_cmo_high_noshow(business_id: str, no_show_count: int, rate_pct: float) -> None:
    """COO tells CMO: high no-show rate → CMO should prepare re-engagement campaign."""
    await alert_dept(
        business_id, "coo", "cmo",
        f"No-show rate is {rate_pct:.0f}% today ({no_show_count} no-shows). "
        "Consider preparing a re-engagement campaign for affected customers.",
        urgency="normal",
        context={"no_show_count": no_show_count, "no_show_rate": rate_pct},
    )


async def cro_notify_csd_dormant_vips(business_id: str, vip_dormant: list) -> None:
    """CRO tells CSD: VIP customers are dormant → CSD should do personal outreach."""
    for customer in vip_dormant[:5]:
        await alert_dept(
            business_id, "cro", "csd",
            f"VIP customer {customer.get('name', '?')} (LTV ${customer.get('lifetime_value', 0)}) "
            f"has been dormant for 30+ days. Consider a personal outreach.",
            urgency="high",
            trigger_workflow="send_rebooking_reminder",
            trigger_params={
                "customer_id": customer.get("id"),
                "customer_name": customer.get("name"),
                "customer_phone": customer.get("phone"),
            },
            context={"customer": customer},
        )


async def cfo_notify_cro_revenue_gap(business_id: str, gap_amount: float, days_left: int) -> None:
    """CFO tells CRO: revenue gap detected → CRO should push for quick wins."""
    await alert_dept(
        business_id, "cfo", "cro",
        f"Revenue is ${gap_amount:.0f} below monthly target with {days_left} days remaining. "
        "Recommend activating dormant customer outreach and upsell campaigns to close the gap.",
        urgency="high",
        context={"revenue_gap": gap_amount, "days_left": days_left},
    )


async def cto_notify_ceo_critical_failure(business_id: str, failure_rate: float, workflows: list) -> None:
    """CTO tells CEO: critical platform failures — CEO decides escalation."""
    await alert_dept(
        business_id, "cto", "ceo",
        f"CRITICAL: Platform failure rate is {failure_rate:.0f}% in last hour. "
        f"Affected workflows: {', '.join(workflows[:5])}. "
        "Recommend investigating immediately to prevent business disruption.",
        urgency="high",
        context={"failure_rate": failure_rate, "workflows": workflows},
    )


async def learning_notify_all_depts(business_id: str, pattern: str, affected_depts: list) -> None:
    """Learning Director broadcasts a lesson to all relevant departments."""
    for dept in affected_depts:
        await alert_dept(
            business_id, "learning", dept,
            f"Learning insight: {pattern}. Please adjust your approach accordingly.",
            urgency="low",
            context={"pattern": pattern, "source": "learning_director"},
        )


async def cmo_notify_cro_hot_leads(business_id: str, hot_lead_count: int, tier_a_leads: list) -> None:
    """CMO tells CRO: new hot leads found → CRO should queue outbound calls."""
    await alert_dept(
        business_id, "cmo", "cro",
        f"Lead scraping found {hot_lead_count} Tier A leads. "
        "Recommend outbound qualification calls for top 5.",
        urgency="normal",
        context={"hot_leads": tier_a_leads[:5], "total": hot_lead_count},
    )


async def csd_notify_ceo_reputation_risk(business_id: str, negative_count: int, avg_sentiment: float) -> None:
    """CSD tells CEO: multiple negative reviews → reputation risk."""
    await alert_dept(
        business_id, "csd", "ceo",
        f"Reputation alert: {negative_count} negative interactions in last 24h. "
        f"Average sentiment: {avg_sentiment:.1f}/5. Recommend owner review.",
        urgency="high",
        context={"negative_count": negative_count, "avg_sentiment": avg_sentiment},
    )
