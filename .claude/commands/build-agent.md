Build a new LangGraph agent for this project.

Agent name: $ARGUMENTS

Requirements:
1. Create /agents/departments/{name}/agent.py
2. Create /prompts/{name}.md
3. Agent inherits from BaseAgent (agents/base_agent.py)
4. Uses gpt-4o-mini (unless name is 'ceo' — use claude-sonnet-4-6)
5. Accepts: (business_id: UUID, question: str) → AgentResponse
6. Reads from Supabase via backend/memory/ modules only
7. Never calls external APIs directly — dispatch TaskRequest
8. Load prompt: self._load_prompt("{name}")

Output format (AgentResponse from shared/schemas.py):
{status, metrics, recommendations, tasks_to_dispatch, summary}
