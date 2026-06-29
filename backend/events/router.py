"""
Event Router — maps event types to which dept agents care and should react.
Multiple depts can listen to the same event (fan-out).
"""
from backend.events.bus import E

# event_type → list of dept keys that handle it
EVENT_SUBSCRIPTIONS: dict[str, list[str]] = {
    # Lead events → CMO owns lead gen
    E.LEAD_DISCOVERED:      ["cmo"],
    E.LEAD_REPLIED:         ["cmo"],
    E.LEAD_BOOKED:          ["cmo", "coo"],

    # Appointment events → multiple depts care
    E.APPT_BOOKED:          ["coo", "cro"],        # COO schedules reminder, CRO notes upsell opp
    E.APPT_CANCELLED:       ["coo", "cro"],        # COO fills waitlist, CRO recovers
    E.APPT_COMPLETED:       ["csd", "cro", "cfo"], # CSD gets review, CRO upsells, CFO logs revenue
    E.APPT_NO_SHOW:         ["cro", "coo"],        # CRO reactivates, COO logs pattern
    E.APPT_REMINDER_DUE:    ["coo"],               # COO sends reminder

    # Customer events
    E.CUSTOMER_DORMANT:     ["cro", "cmo"],        # CRO reactivates, CMO campaigns
    E.CUSTOMER_CHURN_RISK:  ["csd", "cro"],        # CSD reaches out, CRO offers deal
    E.CUSTOMER_VIP:         ["csd", "cro"],        # CSD rewards, CRO upgrades

    # Communication events
    E.SMS_RECEIVED:         ["coo"],               # COO routes to right dept or replies
    E.CALL_MISSED:          ["cro"],               # CRO recovers missed call
    E.CALL_COMPLETED:       ["csd", "learning"],   # CSD scores, Learning captures insights
    E.REVIEW_RECEIVED:      ["csd"],               # CSD monitors
    E.REVIEW_NEGATIVE:      ["csd", "ceo"],        # CSD responds, CEO alerted

    # Revenue events
    E.PAYMENT_FAILED:       ["cro", "cfo"],        # CRO recovers, CFO notes
    E.MEMBERSHIP_EXPIRING:  ["cro", "csd"],        # CRO renews, CSD retention
    E.UPSELL_OPPORTUNITY:   ["cro"],               # CRO acts

    # Platform events
    E.WORKFLOW_FAILED:      ["cto"],               # CTO investigates
    E.WORKFLOW_COMPLETED:   ["learning"],          # Learning captures outcomes

    # Scheduled intelligence
    E.DAILY_STANDUP:        ["ceo"],               # CEO orchestrates all depts
    E.HOURLY_HEARTBEAT:     ["coo", "cro"],        # Check for due reminders, dormant customers
}


def get_handlers(event_type: str) -> list[str]:
    """Return list of dept keys that should handle this event."""
    return EVENT_SUBSCRIPTIONS.get(event_type, [])


# Auto-fire whitelist: these actions fire without owner approval
AUTO_FIRE_ACTIONS = {
    "send_reminder_24h",
    "send_reminder_2h",
    "recover_missed_call",
    "log_no_show",
    "request_google_review",
    "score_conversation",
    "generate_reflection",
    "update_customer",
    "tag_customer",
}

# Always require approval
APPROVAL_REQUIRED_ACTIONS = {
    "reactivate_dormant_member",
    "send_sms_campaign",
    "send_email_campaign",
    "send_cold_outreach",
    "send_upsell_offer",
    "send_payment_link",
    "book_appointment",
}


def requires_approval(workflow_name: str) -> bool:
    if workflow_name in AUTO_FIRE_ACTIONS:
        return False
    if workflow_name in APPROVAL_REQUIRED_ACTIONS:
        return True
    return True  # default: require approval for unknown workflows
