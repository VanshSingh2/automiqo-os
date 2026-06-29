"""
Audit Manager — logs reasoning, tools used, memory accessed, confidence, and final decisions.
Every significant agent action is auditable — WHO decided WHAT with WHAT confidence and WHY.
"""
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase


class AuditManager:
    async def log_action(
        self,
        business_id: str,
        agent: str,
        action: str,
        workflow: str,
        parameters: dict,
        reasoning: str,
        confidence: float,
        approved_by: str = "autonomous",
        risk_level: str = "low",
        outcome: str = "",
    ) -> str:
        """Log any agent action with full audit trail. Returns audit_id."""
        try:
            sb = get_supabase()
            result = sb.table("audit_log").insert({
                "business_id": business_id,
                "agent_name": agent,
                "action": action,
                "workflow": workflow,
                "parameters": parameters,
                "reasoning": reasoning[:1000],
                "confidence": confidence,
                "approved_by": approved_by,
                "risk_level": risk_level,
                "outcome": outcome,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return result.data[0]["id"] if result.data else ""
        except Exception:
            return ""

    async def log_decision(self, business_id: str, dept: str, decision_result) -> None:
        """Log a DecisionResult from the decision engine."""
        if not decision_result.chosen_option:
            return
        await self.log_action(
            business_id=business_id,
            agent=dept,
            action=decision_result.chosen_option.action,
            workflow=decision_result.chosen_option.workflow,
            parameters=decision_result.chosen_option.parameters,
            reasoning=decision_result.reasoning,
            confidence=decision_result.confidence,
            approved_by="autonomous" if not decision_result.requires_approval else "pending_approval",
            risk_level=decision_result.risk_level,
        )

    async def log_inter_dept(
        self, business_id: str, from_dept: str, to_dept: str, message: str, urgency: str
    ) -> None:
        """Log agent-to-agent communication."""
        try:
            sb = get_supabase()
            sb.table("audit_log").insert({
                "business_id": business_id,
                "agent_name": from_dept,
                "action": f"alert_{to_dept}",
                "workflow": "inter_dept_communication",
                "parameters": {"to": to_dept, "message": message[:500], "urgency": urgency},
                "reasoning": f"{from_dept} alerted {to_dept}",
                "confidence": 1.0,
                "approved_by": "autonomous",
                "risk_level": "low",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

    async def get_audit_trail(self, business_id: str, agent: str = None, limit: int = 50) -> list[dict]:
        """Get recent audit log entries."""
        try:
            sb = get_supabase()
            q = sb.table("audit_log").select("*").eq("business_id", business_id)\
                .order("created_at", desc=True).limit(limit)
            if agent:
                q = q.eq("agent_name", agent)
            return q.execute().data or []
        except Exception:
            return []


# Singleton
audit = AuditManager()
