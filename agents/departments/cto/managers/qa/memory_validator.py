"""Memory Validator — checks customer memory, business memory, long-term recall, contradictions."""
import json
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class MemoryValidator(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ctx = context or {}
        try:
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            # Check knowledge base
            knowledge = sb.table("knowledge").select("id,category,title").eq("business_id", str(self.business_id)).execute().data or []
            # Check reflections for duplicates
            reflections = sb.table("reflections").select("what_happened").eq("business_id", str(self.business_id)).limit(200).execute().data or []
            seen = set()
            duplicates = 0
            for r in reflections:
                txt = (r.get("what_happened") or "")[:80]
                if txt in seen:
                    duplicates += 1
                seen.add(txt)
            # Check customers with memory
            customers = sb.table("customers").select("id,name,tags").eq("business_id", str(self.business_id)).limit(10).execute().data or []
            state = {
                "knowledge_items": len(knowledge),
                "knowledge_categories": list({k.get("category") for k in knowledge}),
                "reflections_total": len(reflections),
                "duplicate_reflections": duplicates,
                "customers_with_tags": sum(1 for c in customers if c.get("tags")),
                "memory_health": "ok" if duplicates < 10 else "degraded",
            }
        except Exception as e:
            state = {"error": str(e)}
        state.update(ctx)
        messages = [
            SystemMessage(content=(
                "You are the Memory Validator for an AI business OS. "
                "Validate memory consistency: check for duplicates, contradictions, missing customer memory, stale data. "
                "Respond with JSON: {status, summary, metrics, recommendations}."
            )),
            HumanMessage(content=f"Data: {json.dumps(state, default=str)}\n\nTask: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)
