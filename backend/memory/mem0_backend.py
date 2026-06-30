"""
Mem0 backend for the Unified Memory Service.

Mem0 (https://github.com/mem0ai/mem0) is the semantic memory engine. It rides on
the SAME Postgres/pgvector you already run on Supabase — no new service, ~150MB.

AUTO-DETECTING: if `mem0ai` isn't installed or no DB URL is configured, every
function here returns a "not available" signal and MemoryService falls back to
the existing Supabase/pgvector logic. So the app never breaks.

One-time VPS setup (see docs/memory.md):
    pip install mem0ai
    export MEM0_DB_URL="postgresql://postgres:<pwd>@<host>:5432/postgres"
    # (your Supabase project's direct Postgres connection string)

Scoping (multi-tenant + multi-agent):
    user_id  = business_id   -> tenant isolation (a business's whole memory)
    agent_id = agent name    -> which bot wrote it (CEO, CTO, manager, worker)
A business's agents can all read each other's memory by searching with
user_id alone; filter by agent_id to narrow to one bot.
"""
import os
import functools

_MEM0 = None
_CHECKED = False


def _db_url() -> str:
    return os.getenv("MEM0_DB_URL") or os.getenv("SUPABASE_DB_URL") or ""


def is_available() -> bool:
    """True only if mem0ai is importable AND a Postgres URL is configured."""
    if not _db_url():
        return False
    try:
        import mem0  # noqa: F401
        return True
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _get_client():
    """Build the Mem0 client once, backed by pgvector on Supabase Postgres."""
    try:
        from mem0 import Memory
        config = {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "connection_string": _db_url(),
                    "collection_name": "mem0_memories",
                },
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": os.getenv("DEPT_MODEL", "gpt-4o-mini").split("/")[-1],
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-small",
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                },
            },
        }
        return Memory.from_config(config)
    except Exception as e:
        print(f"[mem0] init failed, falling back to pgvector: {e}")
        return None


def add(business_id: str, text: str, agent: str = "shared", metadata: dict = None) -> bool:
    """Store a memory. Returns True if Mem0 handled it, False to trigger fallback."""
    if not is_available():
        return False
    client = _get_client()
    if client is None:
        return False
    try:
        client.add(
            text,
            user_id=str(business_id),
            agent_id=agent,
            metadata=metadata or {},
        )
        return True
    except Exception as e:
        print(f"[mem0] add failed: {e}")
        return False


def search(business_id: str, query: str, agent: str = None, limit: int = 5) -> list | None:
    """
    Semantic search. Returns a list of {memory, score, ...} dicts, or None to
    signal the caller to use the pgvector fallback.
    """
    if not is_available():
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        kwargs = {"user_id": str(business_id), "limit": limit}
        if agent:
            kwargs["agent_id"] = agent
        result = client.search(query, **kwargs)
        # Mem0 returns {"results": [...]} or a list depending on version
        if isinstance(result, dict):
            return result.get("results", [])
        return result or []
    except Exception as e:
        print(f"[mem0] search failed: {e}")
        return None


def get_all(business_id: str, agent: str = None, limit: int = 50) -> list | None:
    """Return all memories for a business (optionally one agent)."""
    if not is_available():
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        kwargs = {"user_id": str(business_id), "limit": limit}
        if agent:
            kwargs["agent_id"] = agent
        result = client.get_all(**kwargs)
        if isinstance(result, dict):
            return result.get("results", [])
        return result or []
    except Exception:
        return None
