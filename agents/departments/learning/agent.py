import os
import json
import asyncio
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse
from agents.departments.learning.managers.reflection_manager import ReflectionManager
from agents.departments.learning.managers.knowledge_manager import KnowledgeManager
from agents.departments.learning.managers.prompt_improvement_manager import PromptImprovementManager
from agents.departments.learning.managers.innovation_manager import InnovationManager
from backend.memory.supabase_client import get_supabase
from datetime import datetime, timezone, timedelta


class LearningDirectorAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def _query_managers(self, question: str, state: dict) -> dict:
        managers = [ReflectionManager, KnowledgeManager, PromptImprovementManager, InnovationManager]
        tasks = [m(self.business_id).run(question, state) for m in managers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        merged = {}
        summaries = []
        for r in results:
            if isinstance(r, AgentResponse):
                summaries.append(r.summary)
                merged.update(r.metrics or {})
        merged["manager_insights"] = " | ".join(s for s in summaries if s)
        return merged

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        sb = get_supabase()
        bid = str(self.business_id)
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        reflections = sb.table("reflections").select("what_happened,lesson,mistake").eq("business_id", bid).gte("created_at", week_ago).execute().data or []
        failed_tasks = sb.table("tasks").select("workflow,error").eq("business_id", bid).eq("status", "failed").gte("created_at", week_ago).execute().data or []
        state = {
            "reflections_7d": len(reflections),
            "mistakes_7d": len([r for r in reflections if r.get("mistake")]),
            "failed_workflows_7d": len(failed_tasks),
        }
        manager_data = await self._query_managers(question, state)
        state.update(manager_data)
        try:
            prompt = self._load_prompt("learning_director")
        except Exception:
            prompt = "You are the Learning Director. Respond with JSON: {status, summary, metrics, recommendations}."
        # Consult specialists before LLM call
        _q = question.lower()
        _consultations = []
        if any(w in _q for w in ["prompt", "improve", "optimize", "hallucination", "ai response"]):
            _consultations.append({"specialist": "prompt_engineer", "task": question})
        if any(w in _q for w in ["agent", "multi-agent", "pipeline", "orchestration", "delegation"]):
            _consultations.append({"specialist": "multi_agent_systems_architect", "task": question})
        if any(w in _q for w in ["workflow", "n8n", "automation", "process", "failure"]):
            _consultations.append({"specialist": "workflow_optimizer", "task": question})
        if _consultations:
            _insights = await self.consult_specialists_parallel(_consultations)
            _specialist_block = "\n\n## Specialist Insights\n" + "\n".join(
                f"### {k.replace('_', ' ').title()}\n{v}" for k, v in _insights.items()
            )
        else:
            _specialist_block = ""
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}{_specialist_block}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        result = self._parse_response(response.content)
        result.metrics = {**state, **result.metrics}
        return result
