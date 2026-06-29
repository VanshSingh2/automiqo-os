"""
Free social media data extraction (best-effort).
Instagram: hidden web_profile_info endpoint (breaks every 2-4 weeks).
Facebook: oEmbed API + Scrapling fallback.
LinkedIn: Serper search for company URL only (don't scrape directly).
Success rate from VPS: 60-70% — add try/except everywhere.
"""
import re
import asyncio
import httpx
from typing import Optional

INSTAGRAM_APP_ID = "936619743392459"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
]
_ua_index = 0


def _next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


async def get_instagram_profile(username: str) -> dict:
    """
    Fetch public Instagram business profile via hidden web endpoint.
    No login required. Rate limit: ~200 req/hour/IP.
    NOTE: Breaks when Instagram updates API. Wrapped in try/except.
    """
    if not username:
        return {}
    username = username.lstrip("@").strip()
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    headers = {
        "User-Agent": _next_ua(),
        "x-ig-app-id": INSTAGRAM_APP_ID,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/{username}/",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            user = resp.json().get("data", {}).get("user", {})
            if not user:
                return {}
            return {
                "instagram_username": username,
                "instagram_followers": user.get("edge_followed_by", {}).get("count", 0),
                "instagram_posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                "instagram_bio": user.get("biography", ""),
                "instagram_verified": user.get("is_verified", False),
                "instagram_business": user.get("is_business_account", False),
                "instagram_category": user.get("category_name", ""),
                "instagram_email": user.get("business_email", ""),
                "instagram_phone": user.get("business_phone_number", ""),
                "instagram_external_url": user.get("external_url", ""),
                "instagram_scraped": True,
            }
        elif resp.status_code == 429:
            await asyncio.sleep(30)
            return {"instagram_scraped": False, "reason": "rate_limited"}
    except Exception:
        pass
    return {"instagram_scraped": False}



async def find_instagram_handle_from_serper(business_name: str, city: str) -> Optional[str]:
    """Find Instagram handle via Serper web search."""
    from backend.integrations.serper_client import search_web_for_directory
    try:
        results = await search_web_for_directory(f'"{business_name}" {city} site:instagram.com', num_results=3)
        for result in results:
            url = result.get("link", "")
            match = re.search(r"instagram\.com/([a-zA-Z0-9_.]+)/?", url)
            if match:
                handle = match.group(1)
                if handle.lower() not in ["p", "explore", "accounts", "stories", "reels", "tv"]:
                    return handle
    except Exception:
        pass
    return None


async def get_facebook_page_basic(facebook_url: str) -> dict:
    """Get basic Facebook page data via oEmbed API. No auth required."""
    if not facebook_url:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://graph.facebook.com/oembed_page",
                params={"url": facebook_url, "maxwidth": 500},
            )
        if resp.status_code == 200:
            data = resp.json()
            return {"facebook_page_name": data.get("title", ""), "facebook_scraped": True}
    except Exception:
        pass
    # Fallback: extract from meta tags via httpx
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": _next_ua()}) as client:
            resp = await client.get(facebook_url)
        html = resp.text
        result = {"facebook_scraped": True}
        og_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
        og_desc = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', html)
        if og_title:
            result["facebook_page_name"] = og_title.group(1)
        if og_desc:
            result["facebook_description"] = og_desc.group(1)[:300]
        phone_match = re.search(r"\+?1?\s*\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", html)
        if phone_match:
            result["facebook_phone"] = phone_match.group(0).strip()
        return result
    except Exception:
        pass
    return {"facebook_scraped": False}


async def find_facebook_url_from_serper(business_name: str, city: str) -> Optional[str]:
    """Find Facebook page URL via Serper web search."""
    from backend.integrations.serper_client import search_web_for_directory
    try:
        results = await search_web_for_directory(f'"{business_name}" {city} site:facebook.com', num_results=3)
        for result in results:
            url = result.get("link", "")
            if "facebook.com/" in url and "/posts/" not in url and "/photos/" not in url:
                return url
    except Exception:
        pass
    return None


async def find_linkedin_url(business_name: str, city: str) -> Optional[str]:
    """Find LinkedIn company URL via Serper — don't scrape LinkedIn directly."""
    from backend.integrations.serper_client import search_web_for_directory
    try:
        results = await search_web_for_directory(f'"{business_name}" "{city}" site:linkedin.com/company', num_results=3)
        for result in results:
            url = result.get("link", "")
            if "linkedin.com/company/" in url:
                return url
    except Exception:
        pass
    return None


async def _safe_instagram(name: str, city: str) -> dict:
    try:
        handle = await find_instagram_handle_from_serper(name, city)
        if handle:
            await asyncio.sleep(1)
            return await get_instagram_profile(handle)
    except Exception:
        pass
    return {}


async def _safe_facebook(name: str, city: str) -> dict:
    try:
        fb_url = await find_facebook_url_from_serper(name, city)
        if fb_url:
            return await get_facebook_page_basic(fb_url)
    except Exception:
        pass
    return {}


async def _safe_linkedin(name: str, city: str) -> dict:
    try:
        url = await find_linkedin_url(name, city)
        if url:
            return {"linkedin_company_url": url, "linkedin_scraped": True}
    except Exception:
        pass
    return {"linkedin_scraped": False}


async def enrich_social_batch(leads: list[dict], max_concurrent: int = 3, delay_between: float = 2.0) -> list[dict]:
    """Enrich a batch of leads with social media data (Instagram, Facebook, LinkedIn)."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def enrich_one_social(lead: dict) -> dict:
        async with semaphore:
            name = lead.get("company_name", "")
            city = lead.get("city", "New Jersey")
            results = await asyncio.gather(
                _safe_instagram(name, city),
                _safe_facebook(name, city),
                _safe_linkedin(name, city),
            )
            for result in results:
                if result:
                    lead.update(result)
            await asyncio.sleep(delay_between)
            return lead

    return list(await asyncio.gather(*[enrich_one_social(l) for l in leads]))
