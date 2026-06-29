"""
Knowledge Gap Detector — identifies whether failures are caused by
missing knowledge, broken prompts, missing workflows, or policy gaps.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from backend.memory.supabase_client import get_supabase


GAP_TYPES = {
    "missing_knowledge": "Agent doesn't know a fact it should know",
    "broken_prompt":     "Agent prompt gives wrong instructions or misses a scenario",
    "missing_workflow":  "n8n workflow doesn't exist or has no logic",
    "policy_gap":        "Policy table doesn't cover this action type",
    "data_gap":          "Required data not in Supabase (missing column/table)",
    "integration_gap":   "External API not configured or returning errors",
    "logic_error":       "Agent reasoned correctly but workflow logic is wrong",
}


class KnowledgeGapDetector:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if not self._llm:
            self._llm = ChatOpenAI(
                model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def detect_from_failures(self, business_id: str, since_hours: int = 24) -> list[dict]:
        """Scan recent task failures and classify the root cause of each."""
        sb = get_supabase()
        since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
        failed = sb.table("tasks").select("id,workflow,error,parameters,created_by")\
            .eq("business_id", business_id).eq("status", "failed")\
            .gte("created_at", since).execute().data or []

        if not failed:
            return []

        gaps = []
        # Group by workflow to avoid duplicate analysis
        by_workflow: dict[str, list] = {}
        for t in failed:
            wf = t.get("workflow", "unknown")
            by_workflow.setdefault(wf, []).append(t)

        for workflow, tasks in by_workflow.items():
            sample_error = tasks[0].get("error", "unknown error")
            gap_type = self._classify_gap(workflow, sample_error)
            recommendation = self._get_recommendation(gap_type, workflow, sample_error)

            gaps.append({
                "workflow": workflow,
                "failure_count": len(tasks),
                "sample_error": sample_error[:300],
                "gap_type": gap_type,
                "gap_description": GAP_TYPES.get(gap_type, "Unknown gap type"),
                "recommendation": recommendation,
                "priority": "high" if len(tasks) >= 3 else "normal",
            })

        gaps.sort(key=lambda x: x["failure_count"], reverse=True)
        return gaps

    def _classify_gap(self, workflow: str, error: str) -> str:
        """Rule-based gap classification."""
        error_lower = (error or "").lower()
        if any(x in error_lower for x in ["not found", "404", "no such file", "missing workflow"]):
            return "missing_workflow"
        if any(x in error_lower for x in ["column", "table", "relation", "does not exist"]):
            return "data_gap"
        if any(x in error_lower for x in ["401", "403", "authentication", "api key", "unauthorized"]):
            return "integration_gap"
        if any(x in error_lower for x in ["json", "parse", "schema", "validation"]):
            return "logic_error"
        if any(x in error_lower for x in ["timeout", "connection", "network", "503"]):
            return "integration_gap"
        return "logic_error"

    def _get_recommendation(self, gap_type: str, workflow: str, error: str) -> str:
        recs = {
            "missing_workflow":  f"Create n8n workflow '{workflow}' with real logic (not a stub).",
            "broken_prompt":     f"Review agent prompt for workflow '{workflow}'. Add missing scenario.",
            "data_gap":          f"Run SQL migration to add required column/table for '{workflow}'.",
            "policy_gap":        f"Add '{workflow}' to policy_engine.py POLICIES table.",
            "integration_gap":   f"Check API key and connectivity for '{workflow}'. Verify .env vars.",
            "logic_error":       f"Debug workflow logic in n8n for '{workflow}'. Error: {error[:100]}",
            "missing_knowledge": f"Add knowledge base entry for '{workflow}' scenario.",
        }
        return recs.get(gap_type, f"Investigate '{workflow}' failure manually.")

    async def auto_store_gaps(self, business_id: str) -> int:
        """Detect gaps and store them as reflections for Learning Director."""
        gaps = await self.detect_from_failures(business_id)
        if not gaps:
            return 0
        sb = get_supabase()
        stored = 0
        for gap in gaps:
            try:
                sb.table("reflections").insert({
                    "business_id": business_id,
                    "what_happened": f"Knowledge gap detected: {gap['gap_type']} in '{gap['workflow']}' ({gap['failure_count']} failures)",
                    "lesson": gap["recommendation"],
                    "source": "knowledge_gap_detector",
                    "mistake": True,
                }).execute()
                stored += 1
            except Exception:
                pass
        return stored


# Singleton
knowledge_gap_detector = KnowledgeGapDetector()
