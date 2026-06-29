"""
Decision Engine — structured decision flow for all agent decisions.

Flow: Understand → Generate options → Evaluate → Risk analysis → Choose → Confidence → Execute

Every significant agent decision goes through this instead of raw LLM calls.
This makes decisions explainable, auditable, and consistent.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


@dataclass
class DecisionOption:
    action: str
    workflow: str
    parameters: dict
    expected_outcome: str
    risk_level: str
    confidence: float
    reasoning: str


@dataclass
class DecisionResult:
    situation: str
    options_considered: list[DecisionOption]
    chosen_option: Optional[DecisionOption]
    confidence: float          # 0-1
    reasoning: str
    requires_approval: bool
    risk_level: str
    decided_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fallback: str = ""


DECISION_SYSTEM_PROMPT = """You are the Decision Engine for an AI business operating system.
Your job: analyze a situation and return a structured decision with options.

You must respond with valid JSON matching this schema exactly:
{
  "situation_summary": "brief 1-sentence summary",
  "options": [
    {
      "action": "human description",
      "workflow": "n8n_workflow_name",
      "parameters": {},
      "expected_outcome": "what happens if we do this",
      "risk_level": "low|medium|high|critical",
      "confidence": 0.0-1.0,
      "reasoning": "why this option"
    }
  ],
  "recommended_option_index": 0,
  "overall_confidence": 0.0-1.0,
  "overall_reasoning": "why this is the best choice",
  "requires_approval": false
}

Rules:
- Always provide 2-3 options including a "do nothing" option
- Risk level must match the action's potential impact
- Confidence < 0.6 means escalate to CEO or owner
- requires_approval=true for any action affecting > 1 customer or > $50
"""


class DecisionEngine:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                api_key=os.getenv("OPENAI_API_KEY", ""),
            )
        return self._llm

    async def decide(
        self,
        business_id: str,
        dept: str,
        situation: str,
        context: dict = None,
        available_actions: list[str] = None,
    ) -> DecisionResult:
        """
        Main decision method. Given a situation, generate and evaluate options,
        return the best choice with full reasoning.

        Args:
            business_id:       Business context
            dept:              Which dept is making the decision (coo, cro, etc.)
            situation:         What happened / what needs a decision
            context:           Additional data (metrics, customer info, etc.)
            available_actions: Restrict to specific workflows (optional)
        """
        from backend.engines.policy_engine import policy
        from backend.engines.risk_manager import risk_manager

        ctx_str = json.dumps(context or {}, default=str)
        actions_hint = f"Available workflows: {', '.join(available_actions)}" if available_actions else ""

        messages = [
            SystemMessage(content=DECISION_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Department: {dept.upper()}\n"
                f"Business ID: {business_id[:8]}...\n"
                f"Situation: {situation}\n"
                f"Context: {ctx_str[:1000]}\n"
                f"{actions_hint}"
            )),
        ]

        try:
            resp = await self._get_llm().ainvoke(messages)
            raw = resp.content.strip()
            # Strip markdown code fences
            import re
            m = re.search(r"```[\w]*\s*([\s\S]*?)```", raw)
            data = json.loads(m.group(1).strip() if m else raw)
        except Exception as e:
            return DecisionResult(
                situation=situation, options_considered=[], chosen_option=None,
                confidence=0.0, reasoning=f"Decision engine error: {e}",
                requires_approval=True, risk_level="medium", fallback="escalate_to_ceo",
            )

        # Build option objects
        options = []
        for opt in data.get("options", []):
            pol = policy.check(opt.get("workflow", ""), {}, business_id)
            risk = await risk_manager.assess(business_id, opt.get("workflow", ""), opt.get("parameters", {}))
            options.append(DecisionOption(
                action=opt.get("action", ""),
                workflow=opt.get("workflow", ""),
                parameters=opt.get("parameters", {}),
                expected_outcome=opt.get("expected_outcome", ""),
                risk_level=risk.risk_level,
                confidence=float(opt.get("confidence", 0.5)),
                reasoning=opt.get("reasoning", ""),
            ))

        chosen_idx = data.get("recommended_option_index", 0)
        chosen = options[chosen_idx] if options and chosen_idx < len(options) else None
        overall_confidence = float(data.get("overall_confidence", 0.5))
        requires_approval = data.get("requires_approval", False) or overall_confidence < 0.6

        # Policy override — if chosen action requires approval, enforce it
        if chosen:
            pol = policy.check(chosen.workflow, chosen.parameters, business_id)
            if pol.requires_approval:
                requires_approval = True

        return DecisionResult(
            situation=situation,
            options_considered=options,
            chosen_option=chosen,
            confidence=overall_confidence,
            reasoning=data.get("overall_reasoning", ""),
            requires_approval=requires_approval,
            risk_level=chosen.risk_level if chosen else "medium",
        )

    async def decide_and_act(
        self,
        business_id: str,
        dept: str,
        situation: str,
        context: dict = None,
    ) -> dict:
        """
        Decide AND execute the chosen action if confidence >= 0.7 and not blocked.
        Otherwise queue for approval.
        """
        from backend.engines.audit_manager import audit
        from backend.events.handlers import dispatch_action

        result = await self.decide(business_id, dept, situation, context)

        await audit.log_decision(business_id, dept, result)

        if not result.chosen_option:
            return {"acted": False, "reason": "no_option_chosen", "result": result}

        if result.requires_approval or result.confidence < 0.7:
            # Queue as recommendation for owner
            from backend.memory.supabase_client import get_supabase
            sb = get_supabase()
            sb.table("recommendations").insert({
                "business_id": business_id,
                "generated_by": dept,
                "category": "autonomous_decision",
                "title": f"{dept.upper()} decision: {result.chosen_option.action[:80]}",
                "description": f"Situation: {result.situation}\nReasoning: {result.reasoning}\nConfidence: {result.confidence:.0%}",
                "priority": "high" if result.risk_level in ("high", "critical") else "normal",
                "status": "pending",
            }).execute()
            return {"acted": False, "queued_for_approval": True, "result": result}

        # Execute
        await dispatch_action(
            business_id,
            result.chosen_option.workflow,
            result.chosen_option.parameters,
            f"{dept} autonomous decision: {result.reasoning[:200]}",
        )
        return {"acted": True, "workflow": result.chosen_option.workflow, "result": result}


# Singleton
decision_engine = DecisionEngine()
