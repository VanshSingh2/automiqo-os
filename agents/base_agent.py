from abc import ABC, abstractmethod
from uuid import UUID
from shared.schemas import AgentResponse


class BaseAgent(ABC):
    def __init__(self, business_id: UUID):
        self.business_id = business_id

    @abstractmethod
    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        ...

    def _load_prompt(self, name: str) -> str:
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "prompts", f"{name}.md")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _build_dept_llm():
        """Build LLM for dept/manager agents respecting DEPT_MODEL env var."""
        import os
        from langchain_openai import ChatOpenAI
        model_str = os.getenv("DEPT_MODEL", "openai/gpt-4o-mini")
        provider, _, model = model_str.partition("/")
        if provider == "nvidia":
            return ChatOpenAI(
                model=model or "meta/llama-3.1-8b-instruct",
                api_key=os.getenv("NVIDIA_API_KEY", ""),
                base_url="https://integrate.api.nvidia.com/v1",
            )
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model or "claude-haiku-4-5-20251001", api_key=os.getenv("ANTHROPIC_API_KEY", ""), max_tokens=2048)
        else:
            return ChatOpenAI(model=model or "gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY", ""))

    async def consult_specialist(self, specialist: str, task: str, extra_context: dict = {}) -> str:
        """Consult a specialist expert. Available to all agents."""
        from agents.shared.specialist_caller import SpecialistCaller
        return await SpecialistCaller().consult(
            specialist, task,
            {"business_id": str(self.business_id), "agent": self.__class__.__name__, **extra_context}
        )

    async def consult_specialists_parallel(self, consultations: list, extra_context: dict = {}) -> dict:
        """Consult multiple specialists simultaneously."""
        from agents.shared.specialist_caller import SpecialistCaller
        return await SpecialistCaller().consult_multiple(
            consultations,
            {"business_id": str(self.business_id), "agent": self.__class__.__name__, **extra_context}
        )

    @staticmethod
    def _parse_response(content: str) -> "AgentResponse":
        """Parse LLM response, stripping markdown code fences if present."""
        import re, json
        m = re.search(r"```[\w]*\s*([\s\S]*?)```", content)
        clean = m.group(1).strip() if m else content.strip()
        try:
            parsed = json.loads(clean)
            return AgentResponse(
                status=parsed.get("status", "ok"),
                summary=parsed.get("summary", clean),
                metrics=parsed.get("metrics", {}),
                recommendations=parsed.get("recommendations", []),
            )
        except Exception:
            return AgentResponse(status="ok", summary=content.strip())

    def _inject_biz(self, prompt: str) -> str:
        """Replace {business_name}, {industry}, {timezone} with real values from Supabase."""
        from backend.memory.supabase_client import get_supabase
        try:
            result = get_supabase().table("businesses").select("name,industry,timezone") \
                .eq("id", str(self.business_id)).limit(1).execute()
            biz = result.data[0] if result.data else {}
        except Exception:
            biz = {}
        from datetime import datetime, timezone as tz
        return prompt \
            .replace("{business_name}", biz.get("name", "Your Business")) \
            .replace("{industry}", biz.get("industry", "service")) \
            .replace("{timezone}", biz.get("timezone", "America/New_York")) \
            .replace("{date}", datetime.now(tz.utc).strftime("%Y-%m-%d"))
