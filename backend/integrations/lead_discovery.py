"""
Lead Discovery — find businesses via Serper.dev Google Maps + organic search.
Layer 1 of the lead pipeline.
"""
import os
import httpx
import asyncio
from typing import Optional


SERPER_KEY = lambda: os.getenv("SERPER_API_KEY", "")
HEADERS = {"X-API-KEY": "", "Content-Type": "application/json"}


async def search_google_maps(query: str, location: str, count: int = 20) -> list[dict]:
    """Search Google Maps via Serper.dev. Returns raw business listings."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://google.serper.dev/maps",
            headers={"X-API-KEY": SERPER_KEY(), "Content-Type": "application/json"},
            json={"q": f"{query} {location}", "num": min(count, 20)},
        )
        r.raise_for_status()
        places = r.json().get("places", [])

    leads = []
    for p in places:
        leads.append({
            "company_name": p.get("title", ""),
            "address": p.get("address", ""),
            "phone": p.get("phoneNumber", ""),
            "website": p.get("website", ""),
            "google_rating": p.get("rating"),
            "review_count": p.get("reviews") or p.get("reviewCount", 0),
            "google_maps_url": p.get("website", ""),
            "category": p.get("category", ""),
            "source": "google_maps",
            "has_website": bool(p.get("website")),
        })
    return leads


async def search_google_organic(query: str, location: str, count: int = 10) -> list[dict]:
    """Organic Google search for leads not on Maps. Supplements Maps results."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY(), "Content-Type": "application/json"},
            json={"q": f"{query} {location}", "num": count},
        )
        r.raise_for_status()
        results = r.json().get("organic", [])

    leads = []
    for res in results:
        url = res.get("link", "")
        # Skip directories and aggregators
        skip = ["yelp.com", "yellowpages", "tripadvisor", "facebook.com", "instagram.com", "linkedin.com"]
        if any(s in url for s in skip):
            continue
        leads.append({
            "company_name": res.get("title", "").split(" - ")[0].split(" | ")[0],
            "website": url,
            "address": res.get("snippet", "")[:100],
            "source": "google_organic",
            "has_website": True,
        })
    return leads


async def discover_leads(
    query: str,
    location: str,
    count: int = 50,
    include_organic: bool = True,
) -> list[dict]:
    """
    Full discovery: Google Maps + optional organic search.
    Deduplicates by website domain.
    """
    tasks = [search_google_maps(query, location, min(count, 20))]
    if include_organic and count > 20:
        tasks.append(search_google_organic(query, location, 10))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_leads = []
    seen_domains = set()

    for batch in results:
        if isinstance(batch, Exception):
            continue
        for lead in batch:
            website = lead.get("website", "")
            domain = website.split("/")[2] if "//" in website else website.split("/")[0]
            domain = domain.replace("www.", "")
            if domain and domain in seen_domains:
                continue
            if domain:
                seen_domains.add(domain)
            all_leads.append(lead)

    return all_leads[:count]
