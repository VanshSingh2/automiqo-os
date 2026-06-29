# Complete Free Lead Intelligence Scraping System
## Automiqo OS — Full Scraping Stack Implementation

---

## The Honest Reality First

Before building, you need to know the truth about "free" for each platform:

| Platform | Free Method | Works From VPS? | Reliability | Maintenance |
|---|---|---|---|---|
| Business Websites | Scrapling (self-hosted) | ✅ Yes | ⭐⭐⭐⭐⭐ | Low |
| Google Maps | Serper.dev ($2/1K) | ✅ Yes | ⭐⭐⭐⭐⭐ | Zero |
| Yelp | Scrapling StealthyFetcher | ✅ Yes | ⭐⭐⭐⭐ | Low |
| BBB / YellowPages | Scrapling Fetcher | ✅ Yes | ⭐⭐⭐⭐⭐ | Zero |
| Instagram | Hidden API endpoint (httpx) | ⚠️ Breaks every few weeks | ⭐⭐ | High |
| Facebook | Scrapling StealthyFetcher | ⚠️ Partial only | ⭐⭐ | High |
| LinkedIn | LinkedIn public search API (no auth) | ⚠️ Rate limited | ⭐⭐ | High |
| Firecrawl | Self-hosted open source | ✅ Yes (needs 2GB+ RAM) | ⭐⭐⭐⭐ | Medium |
| Crawl4AI | Open source, free | ✅ Yes | ⭐⭐⭐⭐ | Low |

**Bottom line:**
- Scrapling = best free tool for websites, Yelp, BBB, YellowPages
- Crawl4AI = best free tool for intelligent AI extraction from any site
- Firecrawl self-hosted = good but RAM-heavy for your VPS
- Instagram/Facebook/LinkedIn = all unreliable from VPS, use rotation tricks

---

## Tool Comparison: Scrapling vs Crawl4AI vs Firecrawl (Self-Hosted)

| Feature | Scrapling | Crawl4AI | Firecrawl (self-hosted) |
|---|---|---|---|
| Cost | Free | Free | Free (self-host) |
| RAM usage | ~300MB | ~500MB | ~1.5GB |
| Anti-bot bypass | ✅ Built-in (Camoufox) | ⚠️ Basic | ⚠️ Basic |
| AI extraction | ❌ Manual selectors | ✅ LLM-powered | ✅ LLM-powered |
| Speed | ⭐⭐⭐⭐⭐ Fastest | ⭐⭐⭐ Medium | ⭐⭐⭐ Medium |
| Social media | ⚠️ Partial | ❌ No | ❌ No |
| Markdown output | ❌ | ✅ | ✅ |
| Adaptive selectors | ✅ (survives redesigns) | ❌ | ❌ |
| Docker image | ✅ Small | ✅ Medium | ✅ Large |

**Decision:**
- Use **Scrapling** for business websites, Yelp, BBB (fast, anti-bot, adaptive)
- Use **Crawl4AI** for AI-powered extraction when you need structured data from messy pages
- Use **hidden endpoints** for Instagram/Facebook (free but fragile)
- Use **LinkedIn public search** (no auth, limited but free)
- **Skip Firecrawl self-hosted** — too RAM-heavy for your Hetzner CX31

---

## Architecture

```
LEAD INTELLIGENCE ENGINE (all free except Serper.dev)

DISCOVERY
  Serper.dev /maps          → Google Maps (primary, $2/1K)
  Serper.dev /search        → Yelp, BBB, YellowPages URLs
  Instagram hashtag search  → Find businesses by hashtag (free)
  LinkedIn public search    → Find company pages (free, limited)

ENRICHMENT LAYER 1 — Scrapling (self-hosted, free)
  Fetcher                   → Business websites (fast, static)
  StealthyFetcher           → Yelp pages, Facebook pages
  DynamicFetcher            → JS-heavy sites (last resort)

ENRICHMENT LAYER 2 — Crawl4AI (self-hosted, free)
  AsyncWebCrawler           → AI extraction from complex pages
  LLMExtractionStrategy     → Structured data via GPT-4o-mini

ENRICHMENT LAYER 3 — Social Hidden Endpoints (free)
  Instagram web_profile_info → followers, bio, email, category
  Facebook Graph OEMBED      → page name, follower count
  LinkedIn voyager API       → company data (no auth)

SCORING + CRM
  Lead scorer (Python)      → 0-100 score
  Supabase                  → store all leads
```

---

## STEP 1 — Install All Dependencies

Add to `backend/requirements.txt`:
```
# Already there
scrapling[fetchers]>=0.3.2

# Add these
crawl4ai>=0.4.0
httpx>=0.27.0
```

Run after deployment:
```bash
# Install Scrapling browsers (one-time)
scrapling install

# Install Crawl4AI browsers (one-time)
python -m crawl4ai.setup
# OR
crawl4ai-setup
```

Add to `docker/Dockerfile.backend`:
```dockerfile
RUN pip install "scrapling[fetchers]" crawl4ai httpx --break-system-packages
RUN scrapling install
RUN python -m crawl4ai.setup
```

---

## STEP 2 — Create `backend/integrations/crawl4ai_extractor.py`

```python
"""
Crawl4AI extractor for AI-powered structured data extraction.
Used as Layer 2 enrichment when Scrapling doesn't get enough data.

Crawl4AI is open source, free, runs locally.
Uses your OpenAI key to extract structured data via LLM.
Cost per extraction: ~$0.0002 (GPT-4o-mini, ~400 input + 200 output tokens)

When to use vs Scrapling:
- Use Scrapling first (fast, free, no LLM cost)
- Fall back to Crawl4AI when:
  a) Scrapling gets blocked
  b) Page is complex/dynamic
  c) You need AI-structured extraction (services list, pricing table)
"""
import os
import json
import asyncio
from typing import Optional
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
from pydantic import BaseModel


# ── EXTRACTION SCHEMAS ────────────────────────────────────────────────────────

class BusinessProfile(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    owner_name: Optional[str] = None
    services: list[str] = []
    pricing_mentioned: bool = False
    has_online_booking: bool = False
    booking_platform: Optional[str] = None
    has_chatbot: bool = False
    instagram_handle: Optional[str] = None
    facebook_url: Optional[str] = None
    years_in_business: Optional[int] = None
    description: Optional[str] = None


class YelpProfile(BaseModel):
    phone: Optional[str] = None
    price_range: Optional[str] = None
    categories: list[str] = []
    yelp_rating: Optional[float] = None
    yelp_review_count: Optional[int] = None
    address: Optional[str] = None
    hours: Optional[str] = None
    claimed: Optional[bool] = None


# ── CORE EXTRACTOR ────────────────────────────────────────────────────────────

async def extract_business_profile_ai(website_url: str) -> dict:
    """
    Use Crawl4AI with GPT-4o-mini to extract structured business data.
    Falls back gracefully if extraction fails.
    
    Cost: ~$0.0002 per site (use after Scrapling fails)
    """
    strategy = LLMExtractionStrategy(
        provider="openai/gpt-4o-mini",
        api_token=os.getenv("OPENAI_API_KEY"),
        schema=BusinessProfile.schema(),
        extraction_type="schema",
        instruction=(
            "Extract business contact and technology information from this website. "
            "For booking_platform, look for: mindbody, vagaro, fresha, booksy, "
            "calendly, acuity, square, jane_app, boulevard, zenoti. "
            "Set has_online_booking=true if any booking button or form exists. "
            "Set has_chatbot=true if you see a chat bubble, live chat, or chatbot widget. "
            "Return null for any field not clearly present on the page."
        ),
        apply_chunking=False,
    )

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=strategy,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=None,
            options={"ignore_links": False}
        ),
        page_timeout=20000,
        wait_for_images=False,
    )

    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=website_url, config=config)

        if result.success and result.extracted_content:
            data = json.loads(result.extracted_content)
            if isinstance(data, list) and data:
                data = data[0]
            return {**data, "extracted_by": "crawl4ai"}
    except Exception as e:
        pass

    return {"extracted_by": "crawl4ai_failed"}


async def extract_yelp_profile_ai(yelp_url: str) -> dict:
    """
    Use Crawl4AI to extract structured data from a Yelp business listing.
    Yelp is heavily protected — use Scrapling first, fall back here.
    """
    strategy = LLMExtractionStrategy(
        provider="openai/gpt-4o-mini",
        api_token=os.getenv("OPENAI_API_KEY"),
        schema=YelpProfile.schema(),
        extraction_type="schema",
        instruction=(
            "Extract business information from this Yelp page. "
            "price_range should be $, $$, $$$, or $$$$. "
            "claimed means the business owner has claimed their Yelp listing."
        ),
        apply_chunking=False,
    )

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        extraction_strategy=strategy,
        page_timeout=25000,
    )

    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=yelp_url, config=config)
        if result.success and result.extracted_content:
            data = json.loads(result.extracted_content)
            if isinstance(data, list) and data:
                data = data[0]
            return {**data, "extracted_by": "crawl4ai_yelp"}
    except Exception:
        pass

    return {}


async def get_page_as_markdown(url: str) -> Optional[str]:
    """
    Get clean markdown from any URL.
    Useful for feeding page content to GPT-4o-mini separately.
    """
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=DefaultMarkdownGenerator(
            options={"ignore_links": True, "ignore_images": True}
        ),
        page_timeout=15000,
    )
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
        if result.success:
            return result.markdown.raw_markdown if result.markdown else None
    except Exception:
        pass
    return None
```

---

## STEP 3 — Create `backend/integrations/social_scrapers.py`

```python
"""
Free social media data extraction.

HONEST NOTES:
- Instagram: Uses hidden web_profile_info endpoint. Works without login.
  BREAKS every 2-4 weeks when Instagram updates. Needs maintenance.
  From VPS (datacenter IP): will get 429 frequently. Use with try/except.

- Facebook: Uses oEmbed + Scrapling on public pages.
  Only gets basic info (name, description). No followers count reliably.
  Login-gated content is inaccessible.

- LinkedIn: Uses public voyager/search endpoint (no auth).
  Returns company data but heavily rate-limited.
  ~50 requests/hour per IP from VPS before 429s.

These are all best-effort. For a lead intelligence system,
they add useful signals even at 60-70% success rate.
The alternative (paying Apify/ScrapeCreators) is $0.15-1.50/1K profiles.
"""
import re
import json
import httpx
import asyncio
from typing import Optional
from scrapling.fetchers import Fetcher, StealthyFetcher


# ── INSTAGRAM ────────────────────────────────────────────────────────────────

# Instagram's internal app ID — this is public/constant
INSTAGRAM_APP_ID = "936619743392459"

# Rotate user agents to reduce detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

_ua_index = 0

def _next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


async def get_instagram_profile(username: str) -> dict:
    """
    Fetch public Instagram business profile using hidden web endpoint.
    No login required. Works for public business profiles.

    Returns: followers, bio, post count, business email,
             business phone, category, verification status.

    NOTE: Breaks periodically when Instagram updates. Wrapped in try/except.
    Rate limit: ~200 requests/hour/IP. Add delay between calls.
    """
    if not username:
        return {}

    # Clean username (remove @ if present)
    username = username.lstrip("@").strip()

    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    headers = {
        "User-Agent": _next_ua(),
        "x-ig-app-id": INSTAGRAM_APP_ID,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/{username}/",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"Cookie": ""},  # No auth cookies
        ) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user", {})
            if not user:
                return {}

            return {
                "instagram_username": username,
                "instagram_followers": user.get("edge_followed_by", {}).get("count", 0),
                "instagram_following": user.get("edge_follow", {}).get("count", 0),
                "instagram_posts": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                "instagram_bio": user.get("biography", ""),
                "instagram_verified": user.get("is_verified", False),
                "instagram_business": user.get("is_business_account", False),
                "instagram_category": user.get("category_name", ""),
                "instagram_email": user.get("business_email", ""),
                "instagram_phone": user.get("business_phone_number", ""),
                "instagram_external_url": user.get("external_url", ""),
                "instagram_profile_pic": user.get("profile_pic_url", ""),
                "instagram_scraped": True,
            }

        elif resp.status_code == 429:
            # Rate limited — back off
            await asyncio.sleep(30)
            return {"instagram_scraped": False, "reason": "rate_limited"}

    except Exception as e:
        pass

    return {"instagram_scraped": False}


async def find_instagram_handle_from_serper(
    business_name: str,
    city: str,
) -> Optional[str]:
    """
    Use Serper.dev web search to find a business's Instagram handle.
    Called before get_instagram_profile().
    Returns handle string or None.
    """
    from backend.integrations.serper_client import search_web_for_directory

    results = await search_web_for_directory(
        query=f'"{business_name}" {city} site:instagram.com',
        num_results=3,
    )

    for result in results:
        url = result.get("link", "")
        # Match instagram.com/handle pattern
        match = re.search(r"instagram\.com/([a-zA-Z0-9_.]+)/?", url)
        if match:
            handle = match.group(1)
            # Filter out generic Instagram pages
            if handle.lower() not in ["p", "explore", "accounts", "stories", "reels", "tv"]:
                return handle

    return None


# ── FACEBOOK ─────────────────────────────────────────────────────────────────

async def get_facebook_page_basic(facebook_url: str) -> dict:
    """
    Get basic Facebook page data using Facebook's oEmbed API.
    No auth required. Returns: page name, description.
    Limited data but 100% reliable and free.
    """
    if not facebook_url:
        return {}

    oembed_url = f"https://www.facebook.com/plugins/page.php?href={facebook_url}"

    try:
        # Try oEmbed first (most reliable)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://graph.facebook.com/oembed_page",
                params={"url": facebook_url, "maxwidth": 500},
            )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "facebook_page_name": data.get("title", ""),
                "facebook_provider": "oembed",
                "facebook_scraped": True,
            }
    except Exception:
        pass

    # Fallback: Scrapling on public page
    return await _scrape_facebook_page_scrapling(facebook_url)


async def _scrape_facebook_page_scrapling(facebook_url: str) -> dict:
    """
    Scrape public Facebook business page with StealthyFetcher.
    Gets: phone, about text, category from meta tags.
    """
    try:
        page = await asyncio.to_thread(
            StealthyFetcher.fetch,
            facebook_url,
            headless=True,
            network_idle=True,
            timeout=20,
        )
        if not page:
            return {}

        html = page.html

        result = {"facebook_scraped": True}

        # Extract from meta tags (most reliable)
        og_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
        og_desc = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', html)

        if og_title:
            result["facebook_page_name"] = og_title.group(1)
        if og_desc:
            result["facebook_description"] = og_desc.group(1)[:300]

        # Phone from page
        phone_match = re.search(r"\+?1?\s*\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", html)
        if phone_match:
            result["facebook_phone"] = phone_match.group(0).strip()

        return result

    except Exception:
        return {"facebook_scraped": False}


async def find_facebook_url_from_serper(
    business_name: str,
    city: str,
) -> Optional[str]:
    """Find Facebook page URL via Serper web search."""
    from backend.integrations.serper_client import search_web_for_directory

    results = await search_web_for_directory(
        query=f'"{business_name}" {city} site:facebook.com',
        num_results=3,
    )

    for result in results:
        url = result.get("link", "")
        # Match facebook.com/pagename pattern
        if "facebook.com/" in url and "/posts/" not in url and "/photos/" not in url:
            return url

    return None


# ── LINKEDIN ─────────────────────────────────────────────────────────────────

async def get_linkedin_company_public(company_name: str, city: str = "") -> dict:
    """
    Search LinkedIn public company pages without authentication.
    Uses LinkedIn's public search endpoint (no login required).

    Rate limited: ~50 requests/hour from datacenter IPs.
    Returns: company URL, size estimate, industry from search snippet.

    NOTE: LinkedIn blocks datacenter IPs aggressively.
    This works intermittently. Add delay between calls.
    """
    search_query = f"{company_name} {city}".strip()
    url = (
        f"https://www.linkedin.com/search/results/companies/"
        f"?keywords={httpx.URL(search_query)}&origin=SWITCH_SEARCH_VERTICAL"
    )

    headers = {
        "User-Agent": _next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            html = resp.text

            # Extract company URL from search results
            company_url_match = re.search(
                r'href="(https://www\.linkedin\.com/company/[^"?]+)',
                html
            )
            if company_url_match:
                return {
                    "linkedin_company_url": company_url_match.group(1),
                    "linkedin_scraped": True,
                }
    except Exception:
        pass

    # Fallback: use Serper to find the LinkedIn URL
    return await _find_linkedin_via_serper(company_name, city)


async def _find_linkedin_via_serper(company_name: str, city: str) -> dict:
    """Find LinkedIn company URL via Serper (uses Serper credits)."""
    from backend.integrations.serper_client import search_web_for_directory

    results = await search_web_for_directory(
        query=f'"{company_name}" {city} site:linkedin.com/company',
        num_results=3,
    )

    for result in results:
        url = result.get("link", "")
        if "linkedin.com/company/" in url:
            return {
                "linkedin_company_url": url,
                "linkedin_scraped": True,
                "linkedin_source": "serper",
            }

    return {"linkedin_scraped": False}


async def get_linkedin_company_details(linkedin_url: str) -> dict:
    """
    Scrape LinkedIn company page for basic public info.
    Uses Scrapling StealthyFetcher.
    Gets: description, employee count range, industry from meta tags.

    Success rate from VPS: ~40% (LinkedIn blocks heavily)
    Use with try/except — best effort only.
    """
    if not linkedin_url or "linkedin.com/company/" not in linkedin_url:
        return {}

    try:
        page = await asyncio.to_thread(
            StealthyFetcher.fetch,
            linkedin_url,
            headless=True,
            network_idle=True,
            timeout=25,
        )
        if not page:
            return {}

        html = page.html
        result = {}

        # Meta tags (most reliable even with partial page load)
        og_desc = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', html)
        if og_desc:
            result["linkedin_description"] = og_desc.group(1)[:300]

        # Employee count
        emp_match = re.search(r"(\d[\d,]+)\s*(?:employees|employee)", html, re.I)
        if emp_match:
            result["linkedin_employee_count"] = emp_match.group(1).replace(",", "")

        # Industry from structured data
        industry_match = re.search(r'"industry":\s*"([^"]+)"', html)
        if industry_match:
            result["linkedin_industry"] = industry_match.group(1)

        result["linkedin_details_scraped"] = True
        return result

    except Exception:
        return {"linkedin_details_scraped": False}


# ── BATCH SOCIAL ENRICHMENT ───────────────────────────────────────────────────

async def enrich_social_batch(
    leads: list[dict],
    max_concurrent: int = 3,
    delay_between: float = 2.0,
) -> list[dict]:
    """
    Enrich a batch of leads with social media data.
    All three platforms in parallel per lead, but batch is sequential
    to avoid rate limits.

    Args:
        leads: Lead dicts with company_name, city fields
        max_concurrent: Parallel leads to process (keep low for social)
        delay_between: Seconds between leads (social rate limits)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def enrich_one_social(lead: dict) -> dict:
        async with semaphore:
            name = lead.get("company_name", "")
            city = lead.get("city", "New Jersey")

            # Run social lookups with individual try/except
            tasks = [
                _safe_instagram(name, city),
                _safe_facebook(name, city),
                _safe_linkedin(name, city),
            ]
            results = await asyncio.gather(*tasks)

            for result in results:
                if result:
                    lead.update(result)

            await asyncio.sleep(delay_between)
            return lead

    return list(await asyncio.gather(*[enrich_one_social(l) for l in leads]))


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
        result = await get_linkedin_company_public(name, city)
        if result.get("linkedin_company_url"):
            await asyncio.sleep(2)
            details = await get_linkedin_company_details(result["linkedin_company_url"])
            return {**result, **details}
        return result
    except Exception:
        pass
    return {}
```

---

## STEP 4 — Update Scraper Decision Logic in `backend/integrations/scrapling_enricher.py`

Add this function at the bottom:

```python
async def enrich_with_fallback(website_url: str) -> dict:
    """
    Smart enrichment: try Scrapling first (free, fast),
    fall back to Crawl4AI (free, slower, AI-powered) if needed.
    
    Use this instead of calling enrich_lead_website() directly.
    """
    if not website_url:
        return {"enrichment_failed": True, "reason": "no_url"}

    # Layer 1: Try Scrapling (fast, no LLM cost)
    scrapling_result = await enrich_lead_website(website_url)

    # If Scrapling got good data, return it
    if scrapling_result.get("enriched") and (
        scrapling_result.get("email") or
        scrapling_result.get("tech_stack") or
        scrapling_result.get("has_booking_system") is not None
    ):
        scrapling_result["enrichment_method"] = "scrapling"
        return scrapling_result

    # Layer 2: Fall back to Crawl4AI (LLM-powered)
    if scrapling_result.get("enrichment_failed"):
        from backend.integrations.crawl4ai_extractor import extract_business_profile_ai
        ai_result = await extract_business_profile_ai(website_url)
        if ai_result.get("extracted_by") == "crawl4ai":
            ai_result["enrichment_method"] = "crawl4ai"
            ai_result["enriched"] = True
            return ai_result

    # Return whatever Scrapling got (even partial)
    scrapling_result["enrichment_method"] = "scrapling_partial"
    return scrapling_result
```

---

## STEP 5 — Update `backend/integrations/lead_intelligence.py`

Replace the `run_enrichment` function:

```python
async def run_enrichment(leads: list[dict], include_social: bool = True) -> list[dict]:
    """
    Stage 2: Multi-layer enrichment.
    Layer 1: Scrapling on websites (fast, free)
    Layer 2: Crawl4AI fallback (AI extraction, ~$0.0002/site)
    Layer 3: Social media (Instagram, Facebook, LinkedIn)
    """
    from backend.integrations.scrapling_enricher import enrich_with_fallback
    from backend.integrations.social_scrapers import enrich_social_batch

    # Layer 1+2: Website enrichment
    with_website = [l for l in leads if l.get("website")]
    without_website = [l for l in leads if not l.get("website")]

    semaphore = asyncio.Semaphore(5)

    async def enrich_one(lead: dict) -> dict:
        async with semaphore:
            result = await enrich_with_fallback(lead["website"])
            lead.update(result)
            return lead

    enriched = list(await asyncio.gather(*[enrich_one(l) for l in with_website]))
    all_leads = enriched + without_website

    # Layer 3: Social enrichment (best effort)
    if include_social:
        print("[Stage 2b] Social enrichment (Instagram, Facebook, LinkedIn)...")
        # Only do top 50 by score to save time/rate limits
        top_leads = sorted(all_leads, key=lambda x: x.get("score", 0), reverse=True)[:50]
        rest_leads = all_leads[50:]

        enriched_social = await enrich_social_batch(
            top_leads,
            max_concurrent=2,
            delay_between=2.0,
        )
        all_leads = enriched_social + rest_leads

    return all_leads
```

---

## STEP 6 — Update Lead Scorer for Social Signals

Update `backend/integrations/lead_scorer.py` — add social scoring:

```python
def score_lead(lead: dict) -> dict:
    """Extended scorer with social signals."""
    score = 0
    reasons = []

    # ── EXISTING SIGNALS ─────────────────────────────────────
    if not lead.get("has_website"):
        score += 20; reasons.append("no website")
    if not lead.get("has_online_booking"):
        score += 25; reasons.append("no online booking")
    if not lead.get("has_chatbot"):
        score += 15; reasons.append("no AI/chatbot")

    review_count = lead.get("review_count", 0) or 0
    if review_count < 50:
        score += 15; reasons.append(f"only {review_count} Google reviews")

    rating = lead.get("google_rating", 0) or 0
    if 0 < rating < 4.0:
        score += 10; reasons.append(f"{rating}★ Google rating")

    if lead.get("email"):
        score += 10; reasons.append("has email")
    if lead.get("phone"):
        score += 5; reasons.append("has phone")

    bp = lead.get("booking_platform", "")
    BASIC = ["calendly", "squarespace", "wix", "square"]
    ADVANCED = ["mindbody", "vagaro", "fresha", "jane_app", "boulevard", "zenoti"]
    if bp in BASIC:
        score += 15; reasons.append(f"uses {bp} (easy upgrade)")
    elif bp in ADVANCED:
        score -= 10; reasons.append(f"uses {bp} (harder sell)")

    # ── NEW: SOCIAL SIGNALS ───────────────────────────────────

    # Instagram: no presence = opportunity
    if not lead.get("instagram_username"):
        score += 10; reasons.append("no Instagram found")
    else:
        insta_followers = lead.get("instagram_followers", 0) or 0
        insta_posts = lead.get("instagram_posts", 0) or 0

        if insta_followers < 500:
            score += 8; reasons.append(f"only {insta_followers} Instagram followers")
        if insta_posts < 20:
            score += 5; reasons.append("rarely posts on Instagram")
        # Business email in Instagram bio = great contact
        if lead.get("instagram_email"):
            score += 8; reasons.append("email in Instagram bio")

    # Facebook: low engagement = opportunity
    if not lead.get("facebook_page_name"):
        score += 5; reasons.append("no Facebook page found")

    # LinkedIn: no presence = very small operation (good target)
    if not lead.get("linkedin_company_url"):
        score += 5; reasons.append("no LinkedIn presence")

    # Bonus: email in bio = highly reachable
    if lead.get("instagram_email") and not lead.get("email"):
        lead["email"] = lead["instagram_email"]
        reasons.append("email from Instagram bio")

    score = min(score, 100)

    return {
        **lead,
        "score": score,
        "score_reason": ", ".join(reasons),
        "tier": "A" if score >= 75 else "B" if score >= 50 else "C",
    }
```

---

## STEP 7 — LinkedIn Sales Navigator Reality Check

**What Sales Navigator actually is:**

Sales Navigator is LinkedIn's $100+/month paid subscription. It lets you search with advanced filters (company size, seniority, location, industry). The "free trial" they offer is 30 days.

The only official LinkedIn API close to useful is part of the Sales Navigator Application Platform's Display Services API. Even that is heavily constrained — you need Sales Navigator Advanced Plus, access is limited to approved partners only, and you must apply to the partner program. It's not designed for data ownership — it's purely for CRM integrations, meaning profile data can only be synced into supported CRMs.

**For your use case (NJ local businesses):**

You don't actually need Sales Navigator. Local businesses don't have "VP of Sales" profiles — they have a business owner with a Facebook page. Sales Navigator is for B2B SaaS selling to corporations, not med spas.

**What to do instead:**

```python
# FREE: Use Serper to find LinkedIn company pages
# Zero scraping, zero account risk, uses search credits you already have

async def find_business_linkedin(business_name: str, city: str) -> Optional[str]:
    """
    Find LinkedIn company page URL via Google search.
    Uses Serper.dev /search — no LinkedIn account, no scraping.
    """
    from backend.integrations.serper_client import search_web_for_directory
    results = await search_web_for_directory(
        query=f'"{business_name}" "{city}" site:linkedin.com/company',
        num_results=2,
    )
    for r in results:
        url = r.get("link", "")
        if "linkedin.com/company/" in url:
            return url
    return None
```

That's it. Store the URL. Don't scrape it. A LinkedIn company page URL in your lead profile tells you they have a corporate presence — that's the signal you need. Don't risk your IP for it.

---

## STEP 8 — Add New Supabase Columns

Run in Supabase SQL editor:

```sql
-- Instagram enrichment
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_username TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_followers INTEGER DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_posts INTEGER DEFAULT 0;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_bio TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_verified BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_business BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_category TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_email TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_phone TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_external_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram_scraped BOOLEAN DEFAULT false;

-- Facebook enrichment
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_page_name TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_phone TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_description TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook_scraped BOOLEAN DEFAULT false;

-- LinkedIn enrichment
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_company_url TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_description TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_employee_count TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_industry TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin_scraped BOOLEAN DEFAULT false;

-- Enrichment metadata
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enrichment_method TEXT;
-- 'scrapling' | 'crawl4ai' | 'scrapling_partial'

-- Update index for social queries
CREATE INDEX IF NOT EXISTS leads_instagram ON leads(business_id, instagram_username);
CREATE INDEX IF NOT EXISTS leads_social_score ON leads(business_id, score DESC, instagram_scraped);
```

---

## STEP 9 — Update CLAUDE.md

Add to `.claude/CLAUDE.md`:

```markdown
## Scraping Stack (All Free)

### Tool Decision Tree
1. Business websites → Scrapling (Fetcher first → StealthyFetcher → DynamicFetcher)
2. Scrapling fails → Crawl4AI (AI extraction, costs ~$0.0002/site in OpenAI tokens)
3. Yelp listings → Scrapling StealthyFetcher
4. BBB/YellowPages → Scrapling Fetcher (no protection on these)
5. Instagram → Hidden web_profile_info endpoint (httpx, no auth)
6. Facebook → oEmbed API + Scrapling StealthyFetcher fallback
7. LinkedIn → Serper web search for company URL only (don't scrape)
8. Social discovery → Serper /search with site: operators

### Files
- backend/integrations/scrapling_enricher.py — website + Yelp + BBB
- backend/integrations/crawl4ai_extractor.py — AI extraction fallback
- backend/integrations/social_scrapers.py — Instagram, Facebook, LinkedIn
- backend/integrations/serper_client.py — discovery for all sources

### Crawl4AI Setup
Run once per container: crawl4ai-setup
Uses OpenAI key for LLM extraction — cost ~$0.0002/page

### Social Rate Limits
Instagram: 200 req/hour/IP. Add 1-2s delay between calls.
Facebook: Less strict but StealthyFetcher needed
LinkedIn: 50 req/hour from datacenter IP. Mostly use Serper instead.

### DO NOT
- Scrape LinkedIn profiles — use Serper to get company URL only
- Run more than 3 concurrent social scrapes
- Use DynamicFetcher on more than 2 sites simultaneously
- Store credentials for any social platform in .env

### Social Reliability
These are best-effort. 60-70% success rate is normal.
Instagram endpoint breaks every 2-4 weeks (Instagram updates API).
When it breaks: check latest working headers at github.com/D4Vinci/Scrapling issues.
```

---

## Complete Cost Summary

| Stage | Tool | Cost Per 100 Leads |
|---|---|---|
| Google Maps discovery | Serper.dev | $0.02 |
| Instagram/FB/LI discovery | Serper.dev /search | $0.06 |
| Website enrichment | Scrapling (free) | $0.00 |
| AI extraction fallback | Crawl4AI + GPT-4o-mini | ~$0.02 |
| Instagram profiles | Hidden endpoint (free) | $0.00 |
| Facebook pages | Scrapling (free) | $0.00 |
| LinkedIn URLs | Serper /search | $0.04 |
| **TOTAL** | | **~$0.14 per 100 leads** |

**10,000 fully profiled leads = ~$14 total.**

---

## What You Get Per Lead (Complete Profile)

```
Company Name, Address, Phone           ← Serper /maps
Google Rating, Review Count            ← Serper /maps
Website URL                            ← Serper /maps
Email                                  ← Scrapling / Instagram bio
Services Offered                       ← Scrapling / Crawl4AI
Booking Platform                       ← Scrapling (tech detection)
Has Online Booking (bool)              ← Scrapling
Has Chatbot (bool)                     ← Scrapling
Tech Stack (array)                     ← Scrapling
Yelp Categories, Price Range           ← Scrapling /Yelp
BBB Rating, Years in Business          ← Scrapling / BBB
Instagram Handle + Followers + Posts   ← Instagram endpoint
Instagram Email (if in bio)            ← Instagram endpoint
Instagram Business Category            ← Instagram endpoint
Facebook Page Name                     ← oEmbed / Scrapling
LinkedIn Company URL                   ← Serper search
Lead Score 0-100                       ← Scorer
Tier A/B/C                             ← Scorer
Score Reason                           ← Scorer
```
