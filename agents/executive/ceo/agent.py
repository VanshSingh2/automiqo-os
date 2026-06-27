import os
import json
from uuid import UUID
from datetime import datetime, timezone
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from typing import TypedDict, Annotated
import operator

from agents.base_agent import BaseAgent
from agents.executive.ceo.tools import make_ceo_tools
from shared.schemas import AgentResponse

# ── Model selection ──────────────────────────────────────────────
# Set CEO_MODEL in .env to switch:
#   openai/gpt-4.1          (default)
#   openai/gpt-4o
#   anthropic/claude-sonnet-4-6
#   anthropic/claude-opus-4-8
#   nvidia/nvidia/llama-3.1-nemotron-ultra-253b-v1
#   nvidia/<any-nvidia-nim-model>

def _build_llm(tools):
    provider, _, model = os.getenv("CEO_MODEL", "openai/gpt-4.1").partition("/")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=model or "claude-sonnet-4-6",
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            max_tokens=4096,
        )
    elif provider == "nvidia":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model or "nvidia/llama-3.1-nemotron-ultra-253b-v1",
            api_key=os.getenv("NVIDIA_API_KEY", ""),
            base_url="https://integrate.api.nvidia.com/v1",
        )
    else:  # openai (default)
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model or "gpt-4.1",
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )

    return llm.bind_tools(tools)


class CEOState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    business_id: str


class CEOAgent(BaseAgent):
    def __init__(self, business_id: UUID):
        super().__init__(business_id)
        self.tools = make_ceo_tools(business_id)
        self.llm_with_tools = _build_llm(self.tools)
        self._graph = self._build_graph()

    def _build_graph(self):
        tool_node = ToolNode(self.tools)

        def should_continue(state: CEOState):
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return END

        def call_model(state: CEOState):
            from backend.memory.supabase_client import get_supabase
            biz_result = get_supabase().table("businesses").select("name,industry,timezone") \
                .eq("id", state["business_id"]).limit(1).execute()
            biz = biz_result.data[0] if biz_result.data else {}
            prompt = self._load_prompt("ceo")
            system = prompt.replace("{business_name}", biz.get("name", "Your Business")) \
                           .replace("{industry}", biz.get("industry", "service")) \
                           .replace("{timezone}", biz.get("timezone", "America/New_York")) \
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

        # Strip markdown code fences the LLM sometimes wraps around JSON
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```", 2)[-1] if stripped.count("```") >= 2 else stripped
            stripped = stripped.lstrip("json").strip().rstrip("`").strip()
        else:
            stripped = content

        try:
            parsed = json.loads(stripped)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", content),
                metrics=parsed.get("metrics", {}),
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=str(content))
