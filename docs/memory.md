# Memory Architecture — Automiqo OS

## TL;DR recommendation

**Mem0 is the chosen memory engine** — backed by the Supabase/pgvector you already
run. It gives every bot (CEO, CTO, managers, workers) fast shared memory with
~150MB RAM and zero new service. Graphiti+Neo4j (~1.5GB) was rejected as too heavy.

It's wired behind `MemoryService` with **automatic fallback**: if `mem0ai` isn't
installed or `MEM0_DB_URL` isn't set, it transparently uses pgvector — the app
never breaks.

### One-time VPS setup
```bash
pip install mem0ai
# Supabase -> Settings -> Database -> Connection string (direct):
export MEM0_DB_URL="postgresql://postgres:<password>@db.<project>.supabase.co:5432/postgres"
```
That's it. On next start, all bots use Mem0 automatically.

### How any agent uses it (zero boilerplate)
```python
await self.remember("Customer Jane prefers morning appointments")   # any agent
facts = await self.recall("Jane appointment preferences")
block = await self.memory_context("botox pricing", customer_id=cid)  # prompt-ready
```
`self.remember` / `self.recall` / `self.memory_context` are on BaseAgent, so every
department head, manager, and worker shares the same fast memory, scoped by
business_id (tenant) + agent name.

## The 4 memory layers (all free, already running)

| Layer | Store | Used for |
|---|---|---|
| **Semantic** | `knowledge` table + pgvector | Facts, policies, FAQs, services — similarity recall |
| **Episodic** | `reflections` table | What happened + lessons learned (temporal via `created_at`) |
| **Entity / graph** | `knowledge_graph` engine over Supabase | Customer → appointments → staff → services relations |
| **Key-value** | `agent_memory` table | Durable per-agent state (confidence, last-run, prefs) |

### One interface
```python
from backend.memory.memory_service import memory_for
mem = memory_for(business_id)

await mem.remember_fact("We close at 6pm on Saturdays", category="policy")
await mem.remember_event("Lead asked about botox pricing", lesson="Add botox to FAQ", agent="cmo")
await mem.remember_kv("last_campaign", "spring_promo", agent="cmo")

facts   = await mem.recall_facts("opening hours")
lessons = await mem.recall_events("pricing", mistakes_only=False)
context = await mem.build_context("botox pricing", customer_id=cid)  # one block for a prompt
```

`build_context()` returns a compact memory block you can drop straight into any
agent prompt (relevant facts + recent lessons + customer relationship).

## Cost / RAM comparison

| Option | Extra RAM | Extra cost | New service to host | Verdict |
|---|---|---|---|---|
| **Unified Memory Service (this)** | ~0 | $0 | none (reuses Supabase/pgvector) | ✅ Use this |
| Mem0 (self-host, pgvector backend) | ~150MB | $0 | 1 small service | Optional upgrade |
| Graphiti + **FalkorDB** (Redis module) | ~50MB | $0 | uses your existing Redis | If you truly need a temporal graph |
| Graphiti + Neo4j | ~1.5GB+ | $0 (self-host) but heavy | Neo4j | ❌ Too heavy for your VPS |

## If you later want a real temporal knowledge graph

The lightest path is **Graphiti with the FalkorDB driver**, NOT Neo4j:
- FalkorDB is a Redis module (graph queries on top of Redis). You already run Redis,
  so it adds ~50MB instead of Neo4j's 1.5GB+.
- Graphiti supports a FalkorDB driver, so you keep Graphiti's temporal
  bi-temporal knowledge-graph features at a fraction of the RAM.

Migration sketch (only if/when needed):
1. Run FalkorDB as a Redis module alongside your existing Redis.
2. `pip install graphiti-core` and configure the FalkorDB driver.
3. Wrap it behind the SAME `MemoryService` interface (`remember_*`/`recall_*`) so no
   agent code changes — just the backing store swaps.

Until you have a concrete need (e.g. "what did this customer say about X across
6 months of conversations, ranked by recency and relationship"), the Unified
Memory Service is the right, free, low-RAM choice.
