"""
AI Mentor — coaches internal AI departments by explaining mistakes and recommending improvements.
Reviews each dept's recent decisions, identifies patterns of error, and generates targeted coaching.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from backend.memory.supabase_client import get_supabase


DEPT_WEAKNESSES = {
    "coo": ["over-scheduling staff", "missing no-show patterns", "inventory blind spots"],
    "cmo": ["low-quality lead scoring", "campaign timing", "message personalization"],
    "cro": ["wrong dormancy thresholds", "upsell timing", "churn prediction accuracy"],
    "cfo": ["cost attribution", "revenue forecasting", "AI spend monitoring"],
    "cto": ["false positive failures", "regression detection", "deployment risk assessment"],
    "csd": ["complaint categorization", "loyalty timing", "survey response rates"],
    "learning": ["experiment design", "pattern generalization", "confidence calibration"],
}


class AIMentor:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def coach_department(self, business_id: str, dept: str) -> dict:
        """Generate coaching feedback for a specific department."""
        sb = get_supabase()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        # Get dept's recent mistakes
        mistakes = sb.table("reflections").select("what_happened,lesson,confidence")\
            .eq("business_id", business_id).eq("mistake", True)\
            .gte("created_at", week_ago).execute().data or []

        # Get audit trail for this dept
        audit = sb.table("audit_log").select("action,reasoning,confidence,outcome")\
            .eq("business_id", business_id).eq("agent_name", dept)\
            .gte("created_at", week_ago).limit(20).execute().data or []

        # Known weaknesses for this dept
        weaknesses = DEPT_WEAKNESSES.get(dept, [])

        messages = [
            SystemMessage(content=(
                f"You are the AI Mentor for the {dept.upper()} department of an AI business OS. "
                "Review their recent performance and provide specific, actionable coaching. "
                "Focus on patterns of mistakes, not isolated errors. "
                "Respond with JSON: {coaching_summary, specific_mistakes: [{mistake, root_cause, correction}], "
                "prompt_improvements: [{area, current_behavior, suggested_behavior}], "
                "confidence_score: 0-100, next_week_focus: str}"
            )),
            HumanMessage(content=(
                f"Department: {dept.upper()}\n"
                f"Known weak areas: {weaknesses}\n"
                f"Recent mistakes ({len(mistakes)}): {json.dumps([m.get('what_happened','')[:100] for m in mistakes[:5]], default=str)}\n"
                f"Recent decisions ({len(audit)}): {json.dumps([a.get('action','') for a in audit[:5]], default=str)}"
            )),
        ]

        try:
            resp = await self._get_llm().ainvoke(messages)
            import re
            raw = resp.content.strip()
            m = re.search(r"```[\w]*\s*([\s\S]*?)```", raw)
            coaching = json.loads(m.group(1).strip() if m else raw)
        except Exception as e:
            coaching = {"coaching_summary": f"Mentor analysis error: {e}", "specific_mistakes": [], "prompt_improvements": []}

        coaching["department"] = dept
        coaching["generated_at"] = datetime.now(timezone.utc).isoformat()

        # Save coaching as recommendation
        try:
            sb.table("recommendations").insert({
                "business_id": business_id,
                "generated_by": "ai_mentor",
                "category": "ai_coaching",
                "title": f"{dept.upper()} weekly coaching report",
                "description": coaching.get("coaching_summary", ""),
                "priority": "normal",
                "status": "pending",
            }).execute()
        except Exception:
            pass

        return coaching

    async def coach_all_departments(self, business_id: str) -> dict:
        """Coach all departments. Called by Learning Director weekly."""
        import asyncio
        depts = ["coo", "cmo", "cro", "cfo", "csd"]
        results = await asyncio.gather(*[self.coach_department(business_id, d) for d in depts], return_exceptions=True)
        return {dept: r for dept, r in zip(depts, results) if not isinstance(r, Exception)}


# Singleton
ai_mentor = AIMentor()
