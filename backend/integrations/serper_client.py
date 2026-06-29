"""
Serper.dev API client for business discovery.
Stage 1 of the Lead Intelligence Engine.
Cost: $2/1000 queries. 2500 free on signup.
"""
import os
import httpx
import asyncio

SERPER_BASE = "https://google.serper.dev"


def _headers() -> dict:
    return {"X-API-KEY": os.getenv("SERPER_API_KEY", ""), "Content-Type": "application/json"}


async def search_google_maps(query: str, location: str = "New Jersey, USA", num_results: int = 20) -> list[dict]:
    """Search Google Maps via Serper.dev. Returns raw business listings."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SERPER_BASE}/maps",
            headers=_headers(),
            json={"q": f"{query} {location}", "num": num_results},
        )
        resp.raise_for_status()
    return resp.json().get("places", [])


async def search_google_maps_paginated(query: str, location: str, total_results: int = 100) -> list[dict]:
    """Paginate Serper /maps to get more than 20 results."""
    all_results = []
    page = 1
    per_page = 20
    while len(all_results) < total_results:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{SERPER_BASE}/maps",
                headers=_headers(),
                json={"q": f"{query} {location}", "num": per_page, "page": page},
            )
            if resp.status_code != 200:
                break
            results = resp.json().get("places", [])
        if not results:
            break
        all_results.extend(results)
        page += 1
        if len(all_results) < total_results:
            await asyncio.sleep(1)
    return all_results[:total_results]


async def search_web_for_directory(query: str, num_results: int = 10) -> list[dict]:
    """Search Google web for directories (Yelp, BBB, YellowPages) or social URLs."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SERPER_BASE}/search",
            headers=_headers(),
            json={"q": query, "num": num_results},
        )
        resp.raise_for_status()
    return resp.json().get("organic", [])



def normalize_serper_result(raw: dict, industry: str, location: str) -> dict:
    """Convert raw Serper /maps result to our lead schema."""
    return {
        "company_name": raw.get("title", ""),
        "phone": raw.get("phoneNumber", ""),
        "address": raw.get("address", ""),
        "website": raw.get("website", ""),
        "google_rating": raw.get("rating", 0),
        "review_count": raw.get("ratingCount") or raw.get("reviews") or 0,
        "google_place_id": raw.get("placeId", ""),
        "category": raw.get("category", ""),
        "business_hours": raw.get("openingHours", []),
        "industry": industry,
        "city": location.split(",")[0].strip() if "," in location else location,
        "state": "NJ",
        "source": "google_maps_serper",
        "has_website": bool(raw.get("website")),
        "email": None,
        "owner_name": None,
        "services": [],
        "pricing_mentioned": False,
        "has_online_booking": False,
        "has_chatbot": False,
        "booking_platform": None,
        "tech_stack": [],
        "instagram": None,
        "facebook": None,
        "linkedin": None,
        "enriched": False,
        "enrichment_failed": False,
        "score": 0,
        "score_reason": "",
        "tier": "C",
        "status": "new",
    }
