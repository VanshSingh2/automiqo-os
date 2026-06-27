import os
import json
from uuid import UUID
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


class BusinessPlanner(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        state = context or {}
        try:
            prompt = self._load_prompt("managers/cfo/business_planner")
        except Exception:
            prompt = "You are the Business Planner. Respond with JSON: {status, summary, metrics, recommendations}."
        messages = [
            SystemMessage(content=self._inject_biz(prompt)),
            HumanMessage(content=f"Data: {json.dumps(state)}\n\nQuestion: {question}"),
        ]
        response = await self.llm.ainvoke(messages)
        try:
            parsed = json.loads(response.content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", response.content),
                metrics={**state, **parsed.get("metrics", {})},
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=response.content, metrics=state)
