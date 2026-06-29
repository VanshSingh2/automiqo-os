"""
Compliance Manager — validates privacy, consent, regulations, recording policies, data retention.
TCPA: no SMS before 8am or after 9pm (local time).
HIPAA: no PHI in AI responses for medical businesses.
GDPR: honor opt-outs, right to deletion.
Recording: warn if call recording may be active.
"""
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


class ComplianceResult:
    def __init__(self, compliant: bool, violations: list[str], warnings: list[str], action_required: str = ""):
        self.compliant = compliant
        self.violations = violations
        self.warnings = warnings
        self.action_required = action_required


class ComplianceManager:
    def check_sms(self, phone: str, business_id: str, customer_opt_out: bool = False) -> ComplianceResult:
        """Check TCPA compliance before sending any SMS."""
        violations, warnings = [], []

        if customer_opt_out:
            violations.append(f"TCPA: Customer {phone} has opted out of SMS.")
            return ComplianceResult(False, violations, warnings, "do_not_send")

        # TCPA quiet hours: 8am-9pm recipient local time (simplified: use EST)
        now_utc = datetime.now(timezone.utc)
        est_hour = (now_utc.hour - 5) % 24
        if not (8 <= est_hour <= 21):
            violations.append(f"TCPA: Cannot send SMS at {est_hour}:00 EST (quiet hours 8am-9pm).")
            return ComplianceResult(False, violations, warnings, "schedule_for_business_hours")

        # Check for valid US phone format
        cleaned = phone.replace("+1", "").replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
        if len(cleaned) != 10:
            warnings.append(f"Phone number may not be valid US number: {phone}")

        return ComplianceResult(len(violations) == 0, violations, warnings)

    def check_data_retention(self, table: str, record_age_days: int) -> ComplianceResult:
        """Check if a record has exceeded its retention policy."""
        retention_policies = {
            "calls": 365,           # 1 year
            "messages": 365,
            "reflections": 730,     # 2 years
            "recommendations": 365,
            "reports": 730,
            "ai_costs": 90,         # 90 days
            "kpi_events": 90,
        }
        max_days = retention_policies.get(table, 365)
        violations, warnings = [], []

        if record_age_days > max_days:
            violations.append(f"Data retention: {table} records older than {max_days} days should be deleted.")
            return ComplianceResult(False, violations, warnings, "delete_record")
        elif record_age_days > max_days * 0.8:
            warnings.append(f"Data retention: {table} record approaching {max_days}-day limit.")

        return ComplianceResult(True, violations, warnings)

    async def check_customer_consent(self, business_id: str, customer_id: str, channel: str) -> ComplianceResult:
        """Verify customer consent for a specific outreach channel."""
        try:
            sb = get_supabase()
            customer = sb.table("customers").select("opt_out_sms,opt_out_email,phone,email")\
                .eq("business_id", business_id).eq("id", customer_id).limit(1).execute().data
            if not customer:
                return ComplianceResult(False, [f"Customer {customer_id} not found."], [], "cannot_contact")
            c = customer[0]
            violations, warnings = [], []

            if channel == "sms" and c.get("opt_out_sms"):
                violations.append("Customer has opted out of SMS.")
            if channel == "email" and c.get("opt_out_email"):
                violations.append("Customer has opted out of email.")
            if channel == "sms" and not c.get("phone"):
                violations.append("Customer has no phone number on file.")
            if channel == "email" and not c.get("email"):
                violations.append("Customer has no email on file.")

            return ComplianceResult(len(violations) == 0, violations, warnings)
        except Exception as e:
            return ComplianceResult(False, [str(e)], [], "error")

    def check_hipaa(self, message: str, industry: str) -> ComplianceResult:
        """Basic HIPAA check — flag potential PHI in messages for medical businesses."""
        if industry not in ("medspa", "dental", "healthcare", "medical"):
            return ComplianceResult(True, [], [])

        phi_patterns = [
            "social security", "ssn", "date of birth", "dob", "diagnosis",
            "prescription", "insurance id", "medical record",
        ]
        warnings = []
        message_lower = message.lower()
        for pattern in phi_patterns:
            if pattern in message_lower:
                warnings.append(f"Possible PHI in message: '{pattern}'. Review before sending.")

        return ComplianceResult(True, [], warnings)


# Singleton
compliance_manager = ComplianceManager()
