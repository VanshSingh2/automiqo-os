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
