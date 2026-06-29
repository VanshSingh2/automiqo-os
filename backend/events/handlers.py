"""
Event Handlers — each dept agent thinks about an event and decides what to do.
The LLM decides the action, not hardcoded rules.
Handler returns: {auto_fire: [{workflow, params}], queue_for_approval: [{workflow, params, reason}]}
"""
import json
import os
from datetime import datetime, timezone, timedelta
from backend.events.router import requires_approval
from backend.memory.supabase_client import get_supabase


async def _think(agent_class, business_id: str, event_type: str, context: dict) -> dict:
    """Ask an agent to think about an event and decide what to do."""
    try:
        agent = agent_class(business_id)
        question = (
            f"EVENT: {event_type}\n"
            f"CONTEXT: {json.dumps(context, default=str)[:1000]}\n\n"
            f"You just received this business event. Think about it carefully.\n"
            f"What should you do RIGHT NOW autonomously?\n"
            f"Return JSON: {{\"decision\": \"...\", \"actions\": [{{\"workflow\": \"...\", \"parameters\": {{}}, \"reason\": \"...\", \"urgency\": \"high|normal|low\"}}], \"notify_depts\": []}}"
        )
        resp = await agent.run(question, context={"event_type": event_type, **context})
        try:
            parsed = json.loads(resp.summary) if resp.summary.strip().startswith("{") else {}
        except Exception:
            parsed = {"decision": resp.summary, "actions": []}
        return parsed
    except Exception as e:
        return {"decision": f"Error: {e}", "actions": []}


async def _check_smart_timing(business_id: str, customer_id: str, action: str) -> tuple[bool, str]:
    """
    Smart timing gate — checks if it's appropriate to contact this customer now.
    Returns (should_fire, reason).
    """
    sb = get_supabase()

    # Check opt-out
    if customer_id:
        r = sb.table("customers").select("opt_out_sms,opt_out_email,name").eq("id", customer_id).limit(1).execute()
        customer = r.data[0] if r.data else {}
        if customer.get("opt_out_sms") and "sms" in action.lower():
            return False, "customer opted out of SMS"
        if customer.get("opt_out_email") and "email" in action.lower():
            return False, "customer opted out of email"

    # Check recent contact (don't spam within 4 hours)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    r = sb.table("messages").select("id").eq("business_id", business_id) \
        .eq("customer_id", customer_id).gte("sent_at", cutoff).limit(1).execute()
    if r.data:
        return False, "contacted within last 4 hours"

    # Check business hours (6am-9pm local, default EST)
    hour = datetime.now(timezone.utc).hour - 5  # rough EST
    if hour < 6 or hour > 21:
        if "reminder" not in action and "urgent" not in action:
            return False, "outside business hours"

    return True, "ok"


async def dispatch_action(business_id: str, workflow: str, parameters: dict, reason: str = "") -> None:
    """Dispatch a workflow action — either auto-fire or queue for approval."""
    sb = get_supabase()

    if requires_approval(workflow):
        # Queue as recommendation for owner approval
        sb.table("recommendations").insert({
            "business_id": business_id,
            "generated_by": "autonomous_agent",
            "category": "auto_action",
            "title": f"Auto-action: {workflow}",
            "description": f"{reason}\nWorkflow: {workflow}\nParams: {json.dumps(parameters, default=str)[:500]}",
            "priority": "high",
            "status": "pending",
        }).execute()
    else:
        # Auto-fire via dispatcher
        from backend.dispatcher.queue import enqueue_task
        result = sb.table("tasks").insert({
            "business_id": business_id,
            "created_by": "event_bus",
            "workflow": workflow,
            "parameters": parameters,
            "priority": "high",
            "status": "queued",
        }).execute()
        task_id = result.data[0]["id"] if result.data else "unknown"
        await enqueue_task({
            "task_id": str(task_id),
            "business_id": business_id,
            "workflow": workflow,
            "parameters": parameters,
            "priority": "high",
        })


# ── Dept Handlers ─────────────────────────────────────────────

async def handle_coo(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.coo.agent import COOAgent
    from backend.events.bus import E

    if event_type == E.APPT_BOOKED:
        # COO auto-schedules reminders
        appt_id = payload.get("appointment_id")
        customer_id = payload.get("customer_id")
        scheduled_at = payload.get("scheduled_at", "")
        # Queue 24h reminder
        await dispatch_action(business_id, "send_reminder_24h", {
            "appointment_id": appt_id, "customer_id": customer_id, "scheduled_at": scheduled_at,
        }, "Auto-scheduled 24h reminder for new booking")

    elif event_type == E.APPT_NO_SHOW:
        await dispatch_action(business_id, "log_no_show", {
            "appointment_id": payload.get("appointment_id"),
            "customer_id": payload.get("customer_id"),
        }, "Auto-logged no-show")

    elif event_type == E.SMS_RECEIVED:
        # COO routes inbound SMS to conversation manager
        from backend.conversations.manager import handle_inbound_sms
        await handle_inbound_sms(business_id, payload)

    elif event_type == E.APPT_REMINDER_DUE:
        ok, reason = await _check_smart_timing(business_id, payload.get("customer_id", ""), "sms")
        if ok:
            await dispatch_action(business_id, "send_reminder_24h", payload, "Reminder due")

    else:
        # Think about other COO events
        decision = await _think(COOAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))


async def handle_cro(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.cro.agent import CROAgent
    from backend.events.bus import E

    if event_type == E.CALL_MISSED:
        customer_id = payload.get("customer_id", "")
        ok, reason = await _check_smart_timing(business_id, customer_id, "recover_missed_call")
        if ok:
            await dispatch_action(business_id, "recover_missed_call", payload, "Auto-recovering missed call")

    elif event_type == E.CUSTOMER_DORMANT:
        # Think: what's the right reactivation approach for this customer?
        decision = await _think(CROAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))

    elif event_type == E.APPT_COMPLETED:
        # Check for upsell opportunity
        await dispatch_action(business_id, "send_upsell_offer", {
            "customer_id": payload.get("customer_id"),
            "appointment_id": payload.get("appointment_id"),
            "service": payload.get("service", ""),
        }, "Post-appointment upsell opportunity")

    elif event_type == E.PAYMENT_FAILED:
        await dispatch_action(business_id, "recover_failed_payment", payload, "Auto-recovering failed payment")

    else:
        decision = await _think(CROAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))


async def handle_cmo(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.cmo.agent import CMOAgent
    from backend.events.bus import E

    if event_type == E.LEAD_DISCOVERED:
        # CMO thinks: qualify this lead and decide outreach approach
        decision = await _think(CMOAgent, business_id, event_type, {
            **payload,
            "instruction": "A new lead was discovered. Decide if we should reach out, what message to send, and when. Consider their score, industry, and pain points."
        })
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))

    elif event_type == E.LEAD_REPLIED:
        # Lead replied to our outreach — continue conversation
        from backend.conversations.manager import continue_lead_conversation
        await continue_lead_conversation(business_id, payload)

    else:
        decision = await _think(CMOAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))


async def handle_csd(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.customer_success.agent import CustomerSuccessAgent
    from backend.events.bus import E

    if event_type == E.APPT_COMPLETED:
        customer_id = payload.get("customer_id", "")
        ok, _ = await _check_smart_timing(business_id, customer_id, "survey")
        if ok:
            await dispatch_action(business_id, "send_satisfaction_survey", {
                "customer_id": customer_id,
                "appointment_id": payload.get("appointment_id"),
            }, "Auto-sending post-visit satisfaction survey")

    elif event_type == E.REVIEW_NEGATIVE:
        decision = await _think(CustomerSuccessAgent, business_id, event_type, {
            **payload,
            "instruction": "A negative review was received. Decide how to respond and what action to take to recover this customer."
        })
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))

    elif event_type == E.CUSTOMER_CHURN_RISK:
        decision = await _think(CustomerSuccessAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))

    else:
        decision = await _think(CustomerSuccessAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))


async def handle_cto(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.cto.agent import CTOAgent
    from backend.events.bus import E

    if event_type == E.WORKFLOW_FAILED:
        # CTO investigates failed workflows
        decision = await _think(CTOAgent, business_id, event_type, {
            **payload,
            "instruction": "A workflow just failed. Analyze the error and decide if it needs immediate action, retry, or escalation to the CEO."
        })
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"], action.get("parameters", {}), action.get("reason", ""))


async def handle_learning(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.learning.agent import LearningDirectorAgent
    from backend.events.bus import E

    if event_type == E.CALL_COMPLETED:
        # Learning captures insights from every call
        await dispatch_action(business_id, "analyze_call_transcript", {
            "call_id": payload.get("call_id"),
            "transcript": payload.get("transcript", ""),
            "outcome": payload.get("outcome", ""),
        }, "Auto-analyzing completed call for insights")

    elif event_type == E.WORKFLOW_COMPLETED:
        await dispatch_action(business_id, "score_conversation", payload, "Auto-scoring completed workflow")


async def handle_cfo(business_id: str, event_type: str, payload: dict) -> None:
    from agents.departments.cfo.agent import CFOAgent
    from backend.events.bus import E
    from backend.memory.supabase_client import get_supabase

    if event_type == E.PAYMENT_FAILED:
        # CFO logs the failure and queues recovery
        await dispatch_action(business_id, "recover_failed_payment", payload,
                              "CFO auto-flagged failed payment for recovery")
        # Also update the financial snapshot
        await dispatch_action(business_id, "generate_revenue_report", {
            "trigger": "payment_failed", "details": payload,
        }, "CFO: revenue report triggered by payment failure")

    elif event_type == E.APPT_COMPLETED:
        # CFO tracks every completed appointment for revenue
        sb = get_supabase()
        try:
            appt = sb.table("appointments").select("revenue,service,staff_id") \
                .eq("id", payload.get("appointment_id", "")).limit(1).execute().data
            revenue = float((appt[0].get("revenue") or 0)) if appt else 0
            if revenue > 0:
                sb.table("kpi_events").insert({
                    "business_id": business_id,
                    "metric": "appointment_revenue",
                    "value": revenue,
                    "department": "cfo",
                    "metadata": {"appointment_id": payload.get("appointment_id")},
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
        except Exception:
            pass

    elif event_type in ("internal.cfo_alert", "internal.alert") and payload.get("_internal"):
        # CFO received an internal alert from another dept (e.g. CEO says revenue is off)
        decision = await _think(CFOAgent, business_id, event_type, {
            **payload,
            "instruction": (
                f"Internal alert from {payload.get('_from','system')}: {payload.get('message','')}. "
                "Analyse the financial impact and decide what action to take immediately."
            ),
        })
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"],
                                  action.get("parameters", {}), action.get("reason", ""))

    else:
        # CFO thinks about any other financial event
        decision = await _think(CFOAgent, business_id, event_type, payload)
        for action in decision.get("actions", []):
            await dispatch_action(business_id, action["workflow"],
                                  action.get("parameters", {}), action.get("reason", ""))


async def handle_ceo(business_id: str, event_type: str, payload: dict) -> None:
    from agents.executive.ceo.agent import CEOAgent
    from backend.events.bus import E

    if event_type == E.DAILY_STANDUP:
        # CEO morning standup — ask all depts, synthesize, decide actions
        agent = CEOAgent(business_id)
        resp = await agent.run(
            "Daily standup: check all departments, identify top issues and opportunities today, "
            "and decide which actions to take autonomously vs which need owner approval.",
            context={"event_type": "daily.standup", "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        )
        # CEO recommendations are already stored via create_recommendation tool
        return

    elif event_type == E.REVIEW_NEGATIVE:
        # CEO gets notified of negative reviews
        sb = get_supabase()
        sb.table("notifications_log").insert({
            "business_id": business_id,
            "channel": "internal",
            "message": f"ALERT: Negative review received. {payload.get('review_text', '')[:200]}",
            "status": "sent",
        }).execute()

    elif event_type in ("internal.ceo_alert", "internal.alert"):
        # A department escalated something to the CEO (e.g. CFO revenue drop, CTO critical failure)
        sb = get_supabase()
        from_dept = payload.get("_from", payload.get("from", "a department"))
        msg = payload.get("message", "")
        sb.table("notifications_log").insert({
            "business_id": business_id,
            "channel": "internal",
            "message": f"[{from_dept.upper()} -> CEO] {msg[:300]}",
            "status": "sent",
        }).execute()
        # High-urgency alerts become owner recommendations
        if payload.get("urgency") == "high":
            sb.table("recommendations").insert({
                "business_id": business_id,
                "generated_by": "ceo",
                "category": "escalation",
                "title": f"Escalation from {from_dept.upper()}",
                "description": msg[:500],
                "priority": "high",
                "status": "pending",
            }).execute()

    elif event_type == "opportunity.detected":
        # Opportunity engine surfaced a high-value opportunity
        sb = get_supabase()
        sb.table("notifications_log").insert({
            "business_id": business_id,
            "channel": "internal",
            "message": f"OPPORTUNITY: {payload.get('title', '')} (est. ${payload.get('potential_value', 0):.0f})",
            "status": "sent",
        }).execute()

