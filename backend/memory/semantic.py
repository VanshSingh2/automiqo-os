"""
pgvector semantic search over Supabase knowledge table.
Use for: FAQs, policies, SOPs, pricing, service descriptions.
Different from Graphiti (relationships) — this is document/knowledge search.
"""
import os
from uuid import UUID
from openai import AsyncOpenAI
from backend.memory.supabase_client import get_supabase

_openai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


async def get_embedding(text: str) -> list:
    response = await _openai.embeddings.create(
        model="text-embedding-3-small",
        input=text.replace("\n", " ")
    )
    return response.data[0].embedding


async def embed_and_store(business_id: UUID, category: str, title: str, content: str, source: str = "manual") -> str:
    """Embed text and store in knowledge table."""
    embedding = await get_embedding(f"{title}\n{content}")
    sb = get_supabase()
    result = sb.table("knowledge").insert({
        "business_id": str(business_id),
        "category": category,
        "title": title,
        "content": content,
        "embedding": embedding,
        "source": source,
        "approved": True,
    }).execute()
    return result.data[0]["id"] if result.data else ""


async def semantic_search(business_id: UUID, query: str, category: str = None, limit: int = 5) -> list:
    """Search knowledge base by semantic meaning using pgvector cosine similarity."""
    query_embedding = await get_embedding(query)
    sb = get_supabase()

    rpc_params = {
        "query_embedding": query_embedding,
        "business_id_filter": str(business_id),
        "similarity_threshold": 0.7,
        "match_count": limit,
    }
    if category:
        rpc_params["category_filter"] = category

    try:
        result = sb.rpc("match_knowledge", rpc_params).execute()
        return result.data or []
    except Exception:
        # Fallback: regular text search
        q = sb.table("knowledge").select("title,content,category").eq("business_id", str(business_id)).eq("approved", True).limit(limit)
        if category:
            q = q.eq("category", category)
        return q.execute().data or []


async def load_business_knowledge(business_id: UUID, knowledge_items: list) -> dict:
    """Bulk load knowledge items for onboarding."""
    loaded = errors = 0
    for item in knowledge_items:
        try:
            await embed_and_store(business_id, item["category"], item["title"], item["content"], item.get("source", "onboarding"))
            loaded += 1
        except Exception:
            errors += 1
    return {"loaded": loaded, "errors": errors}
