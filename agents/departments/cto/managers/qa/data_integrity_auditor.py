"""Data Integrity Auditor — validates CRM consistency, orphan records, duplicate appointments, audit trail."""
import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class DataIntegrityAuditor(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            bid = str(self.business_id)
            # Check for appointments without customers
            appts = sb.table("appointments").select("id,customer_id,status").eq("business_id", bid).limit(100).execute().data or []
            orphan_appts = [a for a in appts if not a.get("customer_id")]
            # Check for duplicate leads
            leads = sb.table("leads").select("phone,email,website").eq("business_id", bid).limit(500).execute().data or []
            phones = [l["phone"] for l in leads if l.get("phone")]
            dup_phones = len(phones) - len(set(phones))
            emails_list = [l["email"] for l in leads if l.get("email")]
            dup_emails = len(emails_list) - len(set(emails_list))
            # Audit log check
            try:
                audit = sb.table("audit_log").select("id").eq("business_id", bid).limit(1).execute().data or []
                audit_enabled = len(audit) > 0
            except Exception:
                audit_enabled = False
            state = {
                "appointments_total": len(appts),
                "orphan_appointments": len(orphan_appts),
                "leads_total": len(leads),
                "duplicate_lead_phones": dup_phones,
                "duplicate_lead_emails": dup_emails,
                "audit_log_active": audit_enabled,
                "integrity_score": max(0, 100 - len(orphan_appts) * 5 - dup_phones * 2 - dup_emails * 2),
            }
        except Exception as e:
            state = {"error": str(e)}
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Data Integrity Auditor for an AI business OS. "
                "Check for orphan records, duplicates, CRM consistency, and audit trail gaps. "
                "Report integrity score and specific issues found. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
