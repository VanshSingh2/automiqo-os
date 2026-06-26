import os
import json
from uuid import UUID
from datetime import datetime, timezone
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from typing import TypedDict, Annotated
import operator

from agents.base_agent import BaseAgent
from agents.executive.ceo.tools import make_ceo_tools
from shared.schemas import AgentResponse


class CEOState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    business_id: str


class CEOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            max_tokens=4096,
        )
        self.tools = make_ceo_tools(business_id)
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        self._graph = self._build_graph()

    def _build_graph(self):
        tool_node = ToolNode(self.tools)

        def should_continue(state: CEOState):
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return END

        def call_model(state: CEOState):
            prompt = self._load_prompt("ceo")
            system = prompt.replace("{business_name}", "Your Business") \
                           .replace("{industry}", "service") \
                           .replace("{timezone}", "America/New_York") \
                           .replace("{date}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            messages = [SystemMessage(content=system)] + state["messages"]
            response = self.llm_with_tools.invoke(messages)
            return {"messages": [response]}

        builder = StateGraph(CEOState)
        builder.add_node("agent", call_model)
        builder.add_node("tools", tool_node)
        builder.set_entry_point("agent")
        builder.add_conditional_edges("agent", should_continue)
        builder.add_edge("tools", "agent")
        return builder.compile()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        state = {
            "messages": [HumanMessage(content=question)],
            "business_id": str(self.business_id),
        }
        result = await self._graph.ainvoke(state)
        last_msg = result["messages"][-1]
        content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        if isinstance(content, list):
            content = " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)

        try:
            parsed = json.loads(content)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", content),
                metrics=parsed.get("metrics", {}),
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=str(content))
