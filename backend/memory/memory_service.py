"""
Unified Memory Service — a single clean remember()/recall() interface over the
FOUR memory stores the OS already has, using ONLY Supabase + pgvector.

This is the free, ~zero-extra-RAM alternative to Graphiti (which needs Neo4j,
~1.5GB+ RAM). It gives agents Mem0-style layered memory without new infra:

  1. SEMANTIC   -> knowledge table (pgvector)        : facts, policies, FAQs
  2. EPISODIC   -> reflections table                 : what happened + lessons
  3. ENTITY     -> knowledge_graph engine (Supabase) : customer/service relations
  4. KEY-VALUE  -> agent_memory table                : durable per-agent state

Why this over Graphiti+Neo4j:
  - 0 extra RAM (reuses pgvector you already run on Supabase)
  - 0 extra cost / 0 new service to host or maintain
  - temporal recall via created_at ordering + semantic similarity
If you later want a true temporal knowledge graph, the lightest path is
Graphiti with the FalkorDB driver (a Redis module — you already run Redis —
~50MB) instead of Neo4j. See docs/memory.md.
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase


class MemoryService:
    def __init__(self, business_id: str):
        self.business_id = str(business_id)

    # ── REMEMBER ──────────────────────────────────────────────────────────────
    async def remember_fact(self, content: str, title: str = "", category: str = "general", agent: str = "shared") -> None:
        """Store a durable fact. Mem0 first (if available), else pgvector/knowledge."""
        # 1) Mem0 semantic layer (rides on pgvector, dedupes + summarizes)
        try:
            from backend.memory import mem0_backend
            if mem0_backend.add(self.business_id, content, agent=agent,
                                metadata={"title": title, "category": category}):
                return
        except Exception:
            pass
        # 2) Fallback: embed into knowledge table directly
        try:
            from backend.memory.semantic import embed_and_store
            await embed_and_store(self.business_id, category, title or content[:60], content, source="agent")
        except Exception:
            try:
                get_supabase().table("knowledge").insert({
                    "business_id": self.business_id, "category": category,
                    "title": title or content[:60], "content": content,
                    "source": "agent", "approved": True,
                }).execute()
            except Exception:
                pass

    async def remember_event(self, what_happened: str, lesson: str = "",
                            agent: str = "", mistake: bool = False) -> None:
        """Store an episodic memory (something that happened + what was learned)."""
        try:
            get_supabase().table("reflections").insert({
                "business_id": self.business_id, "what_happened": what_happened,
                "lesson": lesson, "agent_name": agent, "mistake": mistake,
                "source": "memory_service",
            }).execute()
        except Exception:
            pass

    async def remember_kv(self, key: str, value: str, agent: str = "shared") -> None:
        """Store/overwrite a durable key-value memory for an agent."""
        try:
            sb = get_supabase()
            sb.table("agent_memory").upsert({
                "business_id": self.business_id, "agent_name": agent,
                "memory_type": "kv", "key": key, "value": value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

    # ── RECALL ────────────────────────────────────────────────────────────────
    async def recall_facts(self, query: str, limit: int = 5, category: str = None, agent: str = None) -> list[dict]:
        """Semantic recall. Mem0 first (fast, ranked), else pgvector, else keyword."""
        # 1) Mem0 semantic search
        try:
            from backend.memory import mem0_backend
            hits = mem0_backend.search(self.business_id, query, agent=agent, limit=limit)
            if hits is not None:
                return [
                    {"content": h.get("memory", h.get("text", "")),
                     "title": (h.get("metadata") or {}).get("title", ""),
                     "category": (h.get("metadata") or {}).get("category", ""),
                     "score": h.get("score")}
                    for h in hits
                ]
        except Exception:
            pass
        # 2) pgvector semantic search
        try:
            from backend.memory.semantic import semantic_search
            results = await semantic_search(self.business_id, query, category, limit)
            if results:
                return results
        except Exception:
            pass
        # 3) Keyword fallback over knowledge table
        sb = get_supabase()
        q = sb.table("knowledge").select("title,content,category").eq("business_id", self.business_id)
        if category:
            q = q.eq("category", category)
        rows = q.limit(limit * 4).execute().data or []
        ql = query.lower().split()
        scored = sorted(rows, key=lambda r: sum(w in (r.get("content") or "").lower() for w in ql), reverse=True)
        return scored[:limit]

    async def recall_events(self, query: str = "", limit: int = 5, mistakes_only: bool = False) -> list[dict]:
        """Recall recent episodic memories, optionally filtered to mistakes."""
        sb = get_supabase()
        q = sb.table("reflections").select("what_happened,lesson,mistake,created_at")\
            .eq("business_id", self.business_id)
        if mistakes_only:
            q = q.eq("mistake", True)
        rows = q.order("created_at", desc=True).limit(limit * 3).execute().data or []
        if not query:
            return rows[:limit]
        ql = query.lower().split()
        scored = sorted(rows, key=lambda r: sum(w in (r.get("what_happened") or "").lower() for w in ql), reverse=True)
        return scored[:limit]

    async def recall_kv(self, key: str, agent: str = "shared") -> str | None:
        """Recall a key-value memory."""
        try:
            sb = get_supabase()
            r = sb.table("agent_memory").select("value").eq("business_id", self.business_id)\
                .eq("agent_name", agent).eq("key", key).limit(1).execute().data
            return r[0]["value"] if r else None
        except Exception:
            return None

    async def recall_entity(self, customer_id: str) -> dict:
        """Recall everything connected to a customer (entity/graph memory)."""
        try:
            from backend.engines.knowledge_graph import knowledge_graph
            return await knowledge_graph.get_customer_graph(self.business_id, customer_id)
        except Exception:
            return {}

    # ── UNIFIED CONTEXT ───────────────────────────────────────────────────────
    async def build_context(self, query: str, customer_id: str = None, limit: int = 4) -> str:
        """
        One call that assembles a compact memory block for an agent prompt:
        relevant facts + recent lessons + (optional) customer relationship.
        """
        import asyncio
        facts, events = await asyncio.gather(
            self.recall_facts(query, limit),
            self.recall_events(query, limit),
        )
        parts = []
        if facts:
            parts.append("Known facts:\n" + "\n".join(
                f"- {f.get('title','')}: {(f.get('content') or '')[:140]}" for f in facts))
        if events:
            parts.append("Past lessons:\n" + "\n".join(
                f"- {(e.get('what_happened') or '')[:100]} => {(e.get('lesson') or '')[:80]}" for e in events))
        if customer_id:
            ent = await self.recall_entity(customer_id)
            if ent.get("customer"):
                c = ent["customer"]
                parts.append(
                    f"Customer: {c.get('name','?')} | visits: {ent.get('total_visits',0)} | "
                    f"LTV: ${ent.get('total_revenue',0):.0f} | relationship: {ent.get('relationship_strength','new')}")
        return "\n\n".join(parts) if parts else "No relevant memory yet."


def memory_for(business_id: str) -> MemoryService:
    return MemoryService(business_id)
