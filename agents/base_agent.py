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
        # Coerce list content (e.g. Anthropic returns a list of content blocks) to string
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", "") or block.get("content", ""))
                else:
                    parts.append(str(block))
            content = "".join(parts)
        elif not isinstance(content, str):
            content = str(content)
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

    async def search_knowledge(self, query: str, category: str = None, limit: int = 5) -> list:
        """Search business knowledge base (FAQs, policies, SOPs) by semantic meaning."""
        try:
            from backend.memory.semantic import semantic_search
            return await semantic_search(self.business_id, query, category, limit)
        except Exception:
            return []

    async def remember(self, content: str, source: str = "agent_action") -> None:
        """Store a fact in reflections table for learning loop."""
        try:
            from backend.memory.supabase_client import get_supabase
            get_supabase().table("reflections").insert({
                "business_id": str(self.business_id),
                "what_happened": content,
                "lesson": "",
                "source": source,
                "mistake": False,
            }).execute()
        except Exception:
            pass

    async def recall_facts(self, query: str, limit: int = 5) -> list:
        """Recall relevant past reflections/facts (lightweight Graphiti substitute)."""
        try:
            from backend.memory.supabase_client import get_supabase
            result = get_supabase().table("reflections") \
                .select("what_happened,lesson,created_at") \
                .eq("business_id", str(self.business_id)) \
                .order("created_at", desc=True).limit(limit * 3).execute()
            rows = result.data or []
            query_lower = query.lower()
            scored = [(r, sum(1 for w in query_lower.split() if w in (r.get("what_happened") or "").lower())) for r in rows]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [r for r, _ in scored[:limit]]
        except Exception:
            return []

    def _inject_biz(self, prompt: str) -> str:
        """Replace template vars with this business's full profile from config."""
        from backend.memory.supabase_client import get_supabase
        try:
            result = get_supabase().table("businesses").select("name,industry,timezone,config") \
                .eq("id", str(self.business_id)).limit(1).execute()
            biz = result.data[0] if result.data else {}
        except Exception:
            biz = {}
        cfg = biz.get("config") or {}
        from datetime import datetime, timezone as tz

        # Build a compact business-context block agents can rely on
        services = cfg.get("services") or []
        svc_str = ", ".join(
            f"{s.get('name')}(${s.get('price','?')})" for s in services[:12]
        ) if services else "not specified"
        hours = cfg.get("business_hours") or {}
        hours_str = ", ".join(f"{k}:{v}" for k, v in hours.items()) if hours else "not specified"

        context_block = (
            f"Business: {biz.get('name','Your Business')} | Industry: {biz.get('industry','service')} | "
            f"Location: {cfg.get('city','')}, {cfg.get('state','')}\n"
            f"Brand voice: {cfg.get('brand_voice','friendly, professional')}\n"
            f"Services: {svc_str}\n"
            f"Hours: {hours_str}\n"
            f"Booking link: {cfg.get('booking_url','(none set)')}\n"
            f"Target customer: {cfg.get('target_customer','local customers')}\n"
            f"Monthly revenue goal: ${cfg.get('monthly_revenue_goal','not set')}\n"
            f"Avg ticket: ${cfg.get('avg_ticket_value','?')}\n"
            f"Policies: {'; '.join(cfg.get('policies', [])) or 'standard'}\n"
            f"USPs: {'; '.join(cfg.get('unique_selling_points', [])) or 'quality service'}"
        )

        return prompt \
            .replace("{business_name}", biz.get("name", "Your Business")) \
            .replace("{industry}", biz.get("industry", "service")) \
            .replace("{timezone}", biz.get("timezone", "America/New_York")) \
            .replace("{date}", datetime.now(tz.utc).strftime("%Y-%m-%d")) \
            .replace("{brand_voice}", cfg.get("brand_voice", "friendly, professional")) \
            .replace("{booking_url}", cfg.get("booking_url", "")) \
            .replace("{business_context}", context_block)
