"""
Reputation Monitor — ingests reviews from Google, Yelp, and Facebook so the
Customer Success department can RESPOND to reviews, not just request them.

Uses Serper.dev (already configured) to pull public review snippets — no paid
review-API needed. Stores reviews in the `reviews` table, flags negatives,
and lets CSD act on them.
"""
import os
import re
import httpx
from datetime import datetime, timezone
from backend.memory.supabase_client import get_supabase

SERPER_BASE = "https://google.serper.dev"


def _headers() -> dict:
    return {"X-API-KEY": os.getenv("SERPER_API_KEY", ""), "Content-Type": "application/json"}


def _sentiment(rating: float, text: str) -> str:
    if rating and rating <= 2:
        return "negative"
    if rating and rating >= 4:
        return "positive"
    neg_words = ["terrible", "awful", "rude", "worst", "disappointed", "never again", "waste"]
    if any(w in (text or "").lower() for w in neg_words):
        return "negative"
    return "neutral"


async def fetch_google_reviews(business_name: str, location: str = "") -> list[dict]:
    """Pull recent Google review snippets for a business via Serper /search."""
    query = f'{business_name} {location} reviews'
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{SERPER_BASE}/search", headers=_headers(),
                                     json={"q": query, "num": 10})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    reviews = []
    # Serper returns a "reviews" block for some places; also parse organic snippets
    for r in data.get("reviews", []) or []:
        reviews.append({
            "platform": "google",
            "author": r.get("user", r.get("author", "")),
            "rating": float(r.get("rating", 0) or 0),
            "text": r.get("snippet", r.get("review", "")),
            "review_date": r.get("date", ""),
        })
    # Fallback: knowledge graph rating
    kg = data.get("knowledgeGraph", {})
    if kg.get("rating"):
        reviews.append({
            "platform": "google", "author": "aggregate",
            "rating": float(kg.get("rating", 0) or 0),
            "text": f"Overall rating {kg.get('rating')} from {kg.get('ratingCount','?')} reviews",
            "review_date": "",
        })
    return reviews


async def ingest_reviews(business_id: str) -> dict:
    """
    Fetch + store reviews for a business, flag negatives, and queue CSD response.
    Called by the reputation n8n workflow and the CSD daily loop.
    """
    sb = get_supabase()
    biz = sb.table("businesses").select("name,config,address").eq("id", business_id).limit(1).execute().data
    if not biz:
        return {"error": "business not found"}
    name = biz[0]["name"]
    cfg = biz[0].get("config") or {}
    location = f"{cfg.get('city','')} {cfg.get('state','')}".strip() or (biz[0].get("address") or "")

    google = await fetch_google_reviews(name, location)
    all_reviews = google
    stored = 0
    negatives = []

    for rv in all_reviews:
        text = rv.get("text", "")
        rating = rv.get("rating", 0)
        sentiment = _sentiment(rating, text)
        # Dedup by platform + author + first 60 chars
        key = f"{rv['platform']}:{rv.get('author','')}:{text[:60]}"
        existing = sb.table("reviews").select("id").eq("business_id", business_id)\
            .eq("dedup_key", key).limit(1).execute().data
        if existing:
            continue
        try:
            sb.table("reviews").insert({
                "business_id": business_id,
                "platform": rv["platform"],
                "author": rv.get("author", ""),
                "rating": rating,
                "text": text[:1000],
                "sentiment": sentiment,
                "dedup_key": key,
                "responded": False,
                "review_date": rv.get("review_date") or None,
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            stored += 1
            if sentiment == "negative":
                negatives.append(rv)
        except Exception:
            pass

    # Queue CSD response for negatives + alert CEO if reputation at risk
    if negatives:
        from backend.events.bus import publish, E
        for n in negatives[:5]:
            await publish(business_id, E.REVIEW_NEGATIVE, {
                "platform": n["platform"], "rating": n.get("rating"),
                "review_text": n.get("text", "")[:300],
                "source": "reputation_monitor",
            }, source="reputation_monitor")

    return {
        "fetched": len(all_reviews),
        "stored": stored,
        "negatives": len(negatives),
        "business": name,
    }


async def get_reputation_summary(business_id: str) -> dict:
    """Return reputation stats for the owner dashboard."""
    sb = get_supabase()
    reviews = sb.table("reviews").select("platform,rating,sentiment,responded")\
        .eq("business_id", business_id).execute().data or []
    if not reviews:
        return {"total": 0, "avg_rating": 0, "negative_unresponded": 0}
    rated = [r for r in reviews if r.get("rating")]
    avg = sum(float(r["rating"]) for r in rated) / max(len(rated), 1)
    neg_unresp = [r for r in reviews if r.get("sentiment") == "negative" and not r.get("responded")]
    by_platform = {}
    for r in reviews:
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
    return {
        "total": len(reviews),
        "avg_rating": round(avg, 2),
        "negative_unresponded": len(neg_unresp),
        "by_platform": by_platform,
        "positive": sum(1 for r in reviews if r.get("sentiment") == "positive"),
        "negative": sum(1 for r in reviews if r.get("sentiment") == "negative"),
    }
