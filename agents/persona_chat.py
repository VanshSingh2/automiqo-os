"""
PersonaChatAgent — the conversational voice of a single team member.

When the owner DMs a member from the Team page, this agent answers *in
character*. It blends the member's persona with the live business profile and
the member's recalled memory, so the Inventory Manager sounds different from
the Lead Manager — and both know about the actual business.

It is intentionally lightweight: a focused, in-character chat, not the heavy
data-gathering run() that the department heads use for autonomous decisions.
"""
from uuid import UUID
from langchain_core.messages import HumanMessage, SystemMessage
from agents.base_agent import BaseAgent
from shared.schemas import AgentResponse


_SYSTEM_TEMPLATE = """You are {member_name}, the {member_title} at {business_name}.

# Who you are
{persona}

# The business you work for
{business_context}

# What you remember that's relevant
{memory}

# How to reply
- The owner is messaging you 1:1. Reply in first person, in character, as {member_name}.
- Be concise and warm — a few sentences unless asked for more detail.
- Stay strictly within your area of responsibility ({member_title}).
- If something is outside your area, say briefly which teammate handles it (e.g. the COO, CMO, etc.).
- Be specific to THIS business; never invent data you don't have — if you're unsure, say what you'd check.
- Never mention being an AI, a model, or a prompt. You are a member of the team.
"""


class PersonaChatAgent(BaseAgent):
    def __init__(self, business_id: UUID, agent_key: str):
        super().__init__(business_id)
        self.agent_key = agent_key
        self.llm = self._build_dept_llm()

    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        from backend.engines.business_blueprint import persona_for, member_display, DEPARTMENTS

        member_name = member_display(self.agent_key)
        # Title: manager label, dept head label, or "CEO"
        if self.agent_key == "ceo":
            member_title = "CEO"
        elif "." in self.agent_key:
            dept, mgr = self.agent_key.split(".", 1)
            member_title = DEPARTMENTS.get(dept, {}).get("managers", {}).get(mgr, member_name)
        else:
            member_title = DEPARTMENTS.get(self.agent_key, {}).get("label", member_name)

        persona = persona_for(self.agent_key)

        # Recall anything this business remembers that's relevant to the question.
        try:
            memory = await self.memory_context(question)
        except Exception:
            memory = ""
        memory = memory or "(nothing specific yet)"

        system = _SYSTEM_TEMPLATE.format(
            member_name=member_name,
            member_title=member_title,
            persona=persona,
            business_name="{business_name}",      # filled by _inject_biz
            business_context="{business_context}",  # filled by _inject_biz
            memory=memory,
        )
        system = self._inject_biz(system)

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=question),
            ])
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    (b.get("text", "") if isinstance(b, dict) else str(b)) for b in content
                )
            reply = (content or "").strip() or "Sure — what would you like to know?"
        except Exception as e:
            reply = f"(I couldn't think that through just now: {e})"

        return AgentResponse(status="ok", summary=reply)
