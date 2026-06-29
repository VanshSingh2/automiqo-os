"""
Capability Registry — explicit permissions for every agent.
Defines exactly what each agent CAN and CANNOT do.
Prevents agents from acting outside their scope.
"""
from backend.engines.policy_engine import POLICIES


# What each department can trigger
DEPT_CAPABILITIES: dict[str, dict] = {
    "ceo": {
        "can_trigger": list(POLICIES.keys()),  # CEO can trigger anything (still needs policy check)
        "can_alert": ["coo","cro","cmo","cfo","cto","csd","learning"],
        "can_approve": True,
        "max_financial_exposure": None,  # No limit for CEO
        "description": "Full access. Orchestrates all departments.",
    },
    "coo": {
        "can_trigger": [
            "send_reminder_24h","send_reminder_2h","log_no_show","assign_staff",
            "book_appointment","cancel_appointment","reschedule_appointment",
            "fill_waitlist_slot","check_availability","send_shift_swap_request",
            "check_inventory","send_inventory_reorder_alert","log_equipment_maintenance",
            "track_vendor","track_room_resource","update_calendar","generate_daily_report",
        ],
        "can_alert": ["cmo","cro","csd","ceo"],
        "can_approve": False,
        "max_financial_exposure": 0,
        "description": "Operations: appointments, staff, inventory. No financial actions.",
    },
    "cro": {
        "can_trigger": [
            "recover_missed_call","reactivate_dormant_member","send_upsell_offer",
            "send_payment_link","send_renewal_reminder","recover_failed_payment",
            "send_rebooking_reminder","win_back_sequence","make_outbound_call",
            "track_referral","generate_revenue_report",
        ],
        "can_alert": ["cmo","csd","cfo","ceo"],
        "can_approve": False,
        "max_financial_exposure": 100,
        "description": "Revenue recovery and growth. Limited financial exposure.",
    },
    "cmo": {
        "can_trigger": [
            "run_lead_pipeline","score_lead","enrich_lead_profile","scrape_google_maps_leads",
            "scrape_website_email","send_cold_outreach","send_sms_campaign","send_email_campaign",
            "send_whatsapp_campaign","schedule_social_post","simulate_campaign","send_referral_link",
            "nurture_cold_lead","nurture_warm_lead","nurture_post_visit",
        ],
        "can_alert": ["cro","csd","ceo"],
        "can_approve": False,
        "max_financial_exposure": 0,
        "description": "Marketing: leads, campaigns, content. Cannot spend money.",
    },
    "cfo": {
        "can_trigger": [
            "generate_invoice","create_purchase_order","process_deposit_refund",
            "generate_revenue_report","generate_campaign_report","generate_weekly_summary",
            "track_ai_costs","generate_cost_report",
        ],
        "can_alert": ["cro","cmo","ceo"],
        "can_approve": False,
        "max_financial_exposure": 500,
        "description": "Finance: reporting, invoicing, cost tracking.",
    },
    "cto": {
        "can_trigger": [
            "run_daily_backup","monitor_vps_health","run_regression_tests","run_qa_pipeline",
            "execute_deployment","rollback_to_version","rollback_workflow_version",
            "rotate_api_key_reminder","check_tenant_isolation","compress_agent_prompt",
            "track_ai_costs","monitor_api_health","monitor_failed_workflows",
        ],
        "can_alert": ["ceo"],
        "can_approve": False,
        "max_financial_exposure": 0,
        "description": "Platform: deployments, backups, monitoring, QA.",
    },
    "csd": {
        "can_trigger": [
            "send_satisfaction_survey","request_google_review","handle_complaint",
            "send_loyalty_reward","send_rebooking_reminder","tag_customer","update_customer",
        ],
        "can_alert": ["cro","ceo"],
        "can_approve": False,
        "max_financial_exposure": 50,
        "description": "Customer success: reviews, complaints, loyalty.",
    },
    "learning": {
        "can_trigger": [
            "generate_reflection","store_failure_pattern","store_success_script",
            "analyze_call_transcript","update_agent_confidence","score_conversation",
            "run_ab_experiment","declare_experiment_winner","detect_knowledge_gap",
            "create_recommendation",
        ],
        "can_alert": ["coo","cro","cmo","cfo","cto","csd"],
        "can_approve": False,
        "max_financial_exposure": 0,
        "description": "Learning: reflections, patterns, experiments, improvements.",
    },
}


class CapabilityRegistry:
    def can_trigger(self, dept: str, workflow: str) -> bool:
        """Check if a department is allowed to trigger a workflow."""
        cap = DEPT_CAPABILITIES.get(dept, {})
        allowed = cap.get("can_trigger", [])
        return workflow in allowed or dept == "ceo"

    def can_alert(self, from_dept: str, to_dept: str) -> bool:
        """Check if from_dept is allowed to send alerts to to_dept."""
        cap = DEPT_CAPABILITIES.get(from_dept, {})
        return to_dept in cap.get("can_alert", [])

    def get_dept_capabilities(self, dept: str) -> dict:
        """Return full capability set for a department."""
        return DEPT_CAPABILITIES.get(dept, {})

    def get_all(self) -> dict:
        """Return full registry — used by CEO and audit."""
        return DEPT_CAPABILITIES

    def validate(self, dept: str, workflow: str, financial_amount: float = 0) -> tuple[bool, str]:
        """Full validation: capability check + financial exposure check."""
        if not self.can_trigger(dept, workflow):
            return False, f"{dept.upper()} is not authorized to trigger '{workflow}'"
        cap = DEPT_CAPABILITIES.get(dept, {})
        max_exposure = cap.get("max_financial_exposure")
        if max_exposure is not None and financial_amount > max_exposure:
            return False, f"{dept.upper()} cannot authorize ${financial_amount:.0f} (max: ${max_exposure})"
        return True, "authorized"


# Singleton
capability_registry = CapabilityRegistry()
