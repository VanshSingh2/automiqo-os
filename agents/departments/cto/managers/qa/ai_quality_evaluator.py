"""AI Quality Evaluator — scores accuracy, hallucinations, tone, empathy, goal completion."""
import json
from uuid import UUID
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class AIQualityEvaluator(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            # Sample recent reflections for quality signals
            reflections = sb.table("reflections").select("what_happened,lesson,mistake").eq("business_id", str(self.business_id)).gte("created_at", since).limit(50).execute().data or []
            recommendations = sb.table("recommendations").select("action,status").eq("business_id", str(self.business_id)).gte("created_at", since).limit(30).execute().data or []
            mistakes = [r for r in reflections if r.get("mistake")]
            approved = [r for r in recommendations if r.get("status") == "approved"]
            rejected = [r for r in recommendations if r.get("status") == "rejected"]
            state = {
                "reflections_7d": len(reflections),
                "mistakes_7d": len(mistakes),
                "mistake_rate": round(len(mistakes) / max(len(reflections), 1) * 100, 1),
                "recommendations_7d": len(recommendations),
                "approval_rate": round(len(approved) / max(len(recommendations), 1) * 100, 1),
                "rejection_rate": round(len(rejected) / max(len(recommendations), 1) * 100, 1),
                "quality_dimensions": ["accuracy", "hallucinations", "tone", "empathy", "conciseness", "policy_compliance", "tool_selection", "goal_completion"],
            }
        except Exception as e:
            state = {"error": str(e)}
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the AI Quality Evaluator for an AI business OS. "
                "Score AI response quality: accuracy, hallucinations, tone, empathy, conciseness, policy compliance. "
                "High mistake rate or low approval rate signals quality degradation. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
