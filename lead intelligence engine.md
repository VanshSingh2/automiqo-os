# Lead Intelligence Engine — Claude Code Implementation
## Serper.dev (Discovery) + Scrapling (Enrichment) + Full Business Profiling

---

## Architecture Overview

```
Owner: "Find 100 med spas in New Jersey to target"
    ↓
CEO → CMO → Lead Intelligence Manager
    ↓
STAGE 1: DISCOVERY (Serper.dev)
  Google Maps API → 100 businesses
  (name, phone, address, rating, website)
    ↓
STAGE 2: ENRICHMENT (Scrapling)
  Visit each website → extract:
  email, services, pricing, booking platform,
  technology stack, has_chatbot, has_online_booking,
  social media handles, owner name
    ↓
STAGE 3: SCORING
  Score 0-100 based on fit criteria
  High score = needs Automiqo most
    ↓
STAGE 4: SEGMENTATION
  Segment by score, industry, location, tech stack
    ↓
STAGE 5: CRM
  Store in Supabase leads table
  Ready for AI SDR outreach
```

---

## When to Use Each Tool

| Tool | Use When | Cost | Speed |
|---|---|---|---|
| **Serper.dev /maps** | Discovering businesses by location + keyword | $2/1000 queries | Fast (API) |
| **Serper.dev /search** | Finding directories, Yelp listings, BBB pages | $2/1000 queries | Fast (API) |
| **Scrapling Fetcher** | Simple business website, static HTML | Free (self-hosted) | Very fast |
| **Scrapling StealthyFetcher** | Cloudflare-protected sites, modern JS sites | Free (self-hosted) | Medium |
| **Scrapling DynamicFetcher** | React/Vue sites that require JS to render | Free (self-hosted) | Slow (browser) |

**Decision tree in code:**
```
Try Fetcher (fast, free) →
  If empty/blocked → Try StealthyFetcher →
    If still blocked → Try DynamicFetcher →
      If all fail → Mark as "scrape_failed", skip
```

---

## STEP 1 — Install Dependencies

Add to `backend/requirements.txt`:
```
scrapling[fetchers]>=0.3.2
```

Add to `.env` and `.env.example`:
```bash
# Serper.dev
SERPER_API_KEY=your_serper_key_here
# Get at serper.dev — $2/1000 queries, 2500 free queries on signup

# Scrapling (no API key — self-hosted, runs in your backend container)
# Just install the package and run: scrapling install
```

After deploying, run inside the backend container:
```bash
scrapling install
# This installs browser dependencies (Playwright + Camoufox)
# Only needed once per VPS
```

Add to `docker/Dockerfile.backend` (after pip install):
```dockerfile
RUN scrapling install
```

---

## STEP 2 — Create `backend/integrations/serper_client.py`

```python
"""
Serper.dev API client for business discovery.
Used in Stage 1 of the Lead Intelligence Engine.

Serper.dev endpoints we use:
- POST /maps → Google Maps search (primary lead source)
- POST /search → Google web search (directories, Yelp, BBB)
- POST /places → Google Places details

Cost: $2 per 1,000 queries (2,500 free on signup)
Each /maps call returns up to 20 results.
50 businesses = ~3 API calls = $0.006
"""
import os
import httpx
import asyncio
from typing import Optional


SERPER_BASE = "https://google.serper.dev"


async def search_google_maps(
    query: str,
    location: str = "New Jersey, USA",
    num_results: int = 20,
) -> list[dict]:
    """
    Search Google Maps for local businesses.
    Primary discovery source — returns name, phone, address,
    rating, review count, website URL.

    Args:
        query: "med spa" | "gym" | "dental office" | "hair salon"
        location: City/state string
        num_results: Max results (20 per page, paginate for more)

    Returns:
        List of raw business dicts from Serper
    """
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY", ""),
        "Content-Type": "application/json",
    }
    payload = {
        "q": f"{query} {location}",
        "num": num_results,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SERPER_BASE}/maps",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return data.get("places", [])


async def search_google_maps_paginated(
    query: str,
    location: str,
    total_results: int = 100,
) -> list[dict]:
    """
    Get more than 20 results by paginating.
    Serper supports 'page' parameter for pagination.

    Args:
        total_results: How many total businesses to fetch (max ~200 per query)
    """
    all_results = []
    page = 1
    per_page = 20

    while len(all_results) < total_results:
        headers = {
            "X-API-KEY": os.getenv("SERPER_API_KEY", ""),
            "Content-Type": "application/json",
        }
        payload = {
            "q": f"{query} {location}",
            "num": per_page,
            "page": page,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{SERPER_BASE}/maps", headers=headers, json=payload)
            if resp.status_code != 200:
                break
            results = resp.json().get("places", [])

        if not results:
            break

        all_results.extend(results)
        page += 1

        # Rate limit: 1 request/second
        if len(all_results) < total_results:
            await asyncio.sleep(1)

    return all_results[:total_results]


async def search_web_for_directory(
    query: str,
    num_results: int = 10,
) -> list[dict]:
    """
    Search Google web for business directory pages.
    Used to find Yelp listings, BBB pages, Chamber of Commerce directories.

    Example queries:
    - "med spas New Jersey site:yelp.com"
    - "gyms Bergen County NJ site:yellowpages.com"
    - "dental offices NJ site:bbb.org"
    """
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY", ""),
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{SERPER_BASE}/search", headers=headers, json=payload)
        resp.raise_for_status()

    return resp.json().get("organic", [])


def normalize_serper_result(raw: dict, industry: str, location: str) -> dict:
    """
    Convert raw Serper /maps result to our lead schema.
    Only sets fields we can get from Google Maps — rest filled by enrichment.
    """
    return {
        # From Serper
        "company_name": raw.get("title", ""),
        "phone": raw.get("phoneNumber", ""),
        "address": raw.get("address", ""),
        "website": raw.get("website", ""),
        "google_rating": raw.get("rating", 0),
        "review_count": raw.get("ratingCount", 0),
        "google_place_id": raw.get("placeId", ""),
        "google_maps_url": raw.get("cid", ""),
        "category": raw.get("category", ""),
        "business_hours": raw.get("openingHours", []),
        # Metadata
        "industry": industry,
        "city": location.split(",")[0].strip() if "," in location else location,
        "state": "NJ",
        "source": "google_maps_serper",
        "has_website": bool(raw.get("website")),
        # Enrichment fields (filled later by Scrapling)
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
        "last_social_post": None,
        "enriched": False,
        "enrichment_failed": False,
        # Scoring (filled by scorer)
        "score": 0,
        "score_reason": "",
        "status": "new",
    }
```

---

## STEP 3 — Create `backend/integrations/scrapling_enricher.py`

```python
"""
Scrapling-based website enrichment for lead intelligence.
Used in Stage 2 of the Lead Intelligence Engine.

Scrapling has 3 fetcher modes:
1. Fetcher — fast HTTP, for simple static sites
2. StealthyFetcher — stealth Firefox, bypasses Cloudflare
3. DynamicFetcher — full Playwright browser, for JS-heavy sites

We try them in order, escalating only when needed.
This keeps costs (RAM/time) low for the majority of sites.
"""
import re
import asyncio
import os
from typing import Optional
from urllib.parse import urljoin, urlparse

from scrapling.fetchers import Fetcher, StealthyFetcher, DynamicFetcher


# ── TECHNOLOGY DETECTION PATTERNS ────────────────────────────────────────────
# Detect what booking/payment/CRM software the business uses
TECH_PATTERNS = {
    # Booking platforms
    "mindbody": ["mindbody", "mindbodyonline.com", "clients.mindbodyonline"],
    "fresha": ["fresha.com", "fresha", "shedul.com"],
    "vagaro": ["vagaro.com", "vagaro"],
    "booksy": ["booksy.com", "booksy"],
    "calendly": ["calendly.com", "calendly"],
    "acuity": ["acuityscheduling.com", "acuity"],
    "square": ["squareup.com", "square.site", "square appointments"],
    "squarespace": ["squarespace.com", "static.squarespace"],
    "wix": ["wix.com", "wixsite"],
    "jane_app": ["jane.app", "janeapp"],
    "boulevard": ["joinblvd.com", "boulevard"],
    "zenoti": ["zenoti.com"],
    # Payment
    "stripe": ["js.stripe.com", "stripe.com"],
    # CRM/Marketing
    "hubspot": ["hubspot.com", "hs-scripts"],
    "mailchimp": ["mailchimp.com", "chimpstatic"],
    "klaviyo": ["klaviyo.com"],
    # Chat/support
    "intercom": ["intercom.io", "intercomcdn"],
    "drift": ["drift.com", "js.driftt"],
    "tidio": ["tidio.com"],
    "zendesk": ["zendesk.com", "zopim"],
    "tawk": ["tawk.to"],
    "crisp": ["crisp.chat"],
    # Analytics
    "google_analytics": ["google-analytics.com", "gtag/js", "UA-", "G-"],
    "facebook_pixel": ["fbq(", "connect.facebook.net"],
}

# Keywords that indicate online booking capability
BOOKING_KEYWORDS = [
    "book now", "book online", "book appointment", "schedule appointment",
    "schedule now", "request appointment", "online booking", "book a visit",
    "reserve", "schedule online",
]

# Keywords indicating a chatbot/chat widget
CHAT_KEYWORDS = [
    "chat with us", "live chat", "chat now", "start chat",
    "message us", "chat support",
]

# Email regex
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Social media URL patterns
SOCIAL_PATTERNS = {
    "instagram": re.compile(r"instagram\.com/([a-zA-Z0-9_.]+)", re.I),
    "facebook": re.compile(r"facebook\.com/([a-zA-Z0-9_.]+)", re.I),
    "linkedin": re.compile(r"linkedin\.com/(?:company|in)/([a-zA-Z0-9_\-]+)", re.I),
    "tiktok": re.compile(r"tiktok\.com/@([a-zA-Z0-9_.]+)", re.I),
    "youtube": re.compile(r"youtube\.com/(?:channel|@|user)/([a-zA-Z0-9_\-]+)", re.I),
}


def _extract_from_html(url: str, html: str, page_obj=None) -> dict:
    """
    Extract all enrichment data from raw HTML string.
    Works whether page_obj is available or not.
    """
    html_lower = html.lower()
    result = {}

    # 1. Email extraction
    emails = EMAIL_RE.findall(html)
    filtered = [
        e for e in emails
        if not any(x in e.lower() for x in [
            "noreply", "no-reply", "example", "test@", "admin@",
            ".png", ".jpg", ".gif", "sentry", "wixpress"
        ])
    ]
    result["email"] = filtered[0] if filtered else None

    # 2. Social media
    for platform, pattern in SOCIAL_PATTERNS.items():
        match = pattern.search(html)
        if match:
            handle = match.group(1).rstrip("/")
            if handle.lower() not in ["sharer", "share", "pages", "login", "home"]:
                result[platform] = handle

    # 3. Technology detection
    detected_tech = []
    for tech, patterns in TECH_PATTERNS.items():
        if any(p.lower() in html_lower for p in patterns):
            detected_tech.append(tech)
    result["tech_stack"] = detected_tech

    # 4. Booking platform detection
    booking_platforms = ["mindbody", "fresha", "vagaro", "booksy", "calendly",
                        "acuity", "square", "jane_app", "boulevard", "zenoti"]
    for bp in booking_platforms:
        if bp in detected_tech:
            result["booking_platform"] = bp
            result["has_online_booking"] = True
            break
    else:
        # Check for generic booking keywords
        result["has_online_booking"] = any(kw in html_lower for kw in BOOKING_KEYWORDS)
        result["booking_platform"] = None

    # 5. Chat widget detection
    result["has_chatbot"] = any(
        any(p in html_lower for p in TECH_PATTERNS.get(ct, []))
        for ct in ["intercom", "drift", "tidio", "zendesk", "tawk", "crisp"]
    ) or any(kw in html_lower for kw in CHAT_KEYWORDS)

    # 6. Pricing detection
    price_patterns = [r"\$\d+", r"pricing", r"price list", r"our rates", r"per unit", r"per session"]
    result["pricing_mentioned"] = any(re.search(p, html_lower) for p in price_patterns)

    # 7. Services extraction (from page object if available)
    services = []
    if page_obj:
        # Look for service-like headings and list items
        try:
            headings = page_obj.css("h2, h3, h4, .service-title, .service-name")
            for h in headings[:20]:
                text = h.text if hasattr(h, 'text') else str(h)
                text = text.strip()
                if text and 5 < len(text) < 60:
                    services.append(text)
        except Exception:
            pass
    result["services"] = services[:15]

    # 8. Phone from page (backup)
    phone_re = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
    phones = phone_re.findall(html)
    result["phone_from_site"] = phones[0] if phones else None

    return result


async def _fetch_with_fallback(url: str, timeout: int = 15) -> tuple[Optional[str], Optional[object]]:
    """
    Try fetchers in order: Fetcher → StealthyFetcher → DynamicFetcher.
    Returns (html_string, page_object) or (None, None) if all fail.
    """
    # Stage 1: Fast HTTP fetcher (no browser, instant)
    try:
        page = await asyncio.to_thread(
            Fetcher.fetch, url,
            timeout=timeout,
            stealthy_headers=True,
        )
        if page and len(page.html) > 500:
            return page.html, page
    except Exception:
        pass

    # Stage 2: Stealth Firefox (bypasses Cloudflare)
    try:
        page = await asyncio.to_thread(
            StealthyFetcher.fetch, url,
            headless=True,
            network_idle=True,
            timeout=timeout * 2,
        )
        if page and len(page.html) > 500:
            return page.html, page
    except Exception:
        pass

    # Stage 3: Full Playwright browser (JS-heavy sites)
    try:
        page = await asyncio.to_thread(
            DynamicFetcher.fetch, url,
            headless=True,
            network_idle=True,
            timeout=timeout * 3,
        )
        if page and len(page.html) > 500:
            return page.html, page
    except Exception:
        pass

    return None, None


async def enrich_lead_website(website_url: str) -> dict:
    """
    Full website enrichment using Scrapling.
    Visits homepage, then /contact and /about if email not found.

    Returns enrichment dict with all detected fields.
    """
    if not website_url or not website_url.startswith("http"):
        return {"enrichment_failed": True, "reason": "no_website"}

    enrichment = {"enriched": True}

    # Visit homepage
    html, page = await _fetch_with_fallback(website_url)
    if not html:
        return {"enrichment_failed": True, "reason": "fetch_failed"}

    data = _extract_from_html(website_url, html, page)
    enrichment.update(data)

    # If no email found, try /contact and /about pages
    if not enrichment.get("email"):
        base = f"{urlparse(website_url).scheme}://{urlparse(website_url).netloc}"
        for path in ["/contact", "/contact-us", "/about", "/about-us"]:
            contact_url = base + path
            try:
                c_html, c_page = await _fetch_with_fallback(contact_url, timeout=10)
                if c_html:
                    c_data = _extract_from_html(contact_url, c_html, c_page)
                    if c_data.get("email"):
                        enrichment["email"] = c_data["email"]
                        enrichment["email_source"] = path
                        break
            except Exception:
                continue

    return enrichment


async def enrich_leads_batch(
    leads: list[dict],
    max_concurrent: int = 5,
    delay_between: float = 0.5,
) -> list[dict]:
    """
    Enrich multiple leads in parallel with rate limiting.

    Args:
        leads: List of lead dicts with 'website' field
        max_concurrent: Max parallel Scrapling instances
                        Keep at 5 for Hetzner CX31 (8GB RAM)
                        Increase to 10 on larger VPS
        delay_between: Seconds between each batch (be polite)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def enrich_one(lead: dict) -> dict:
        if not lead.get("website"):
            lead["enrichment_failed"] = True
            lead["reason"] = "no_website"
            return lead

        async with semaphore:
            await asyncio.sleep(delay_between)
            enrichment = await enrich_lead_website(lead["website"])
            lead.update(enrichment)
            return lead

    return list(await asyncio.gather(*[enrich_one(l) for l in leads]))
```

---

## STEP 4 — Create `backend/integrations/lead_scorer.py`

```python
"""
Lead Intelligence Scorer.
Scores each lead 0-100 based on fit for Automiqo OS.
Higher score = business needs AI automation most.
"""


SCORING_RULES = [
    # Opportunity signals (they need us)
    {"field": "has_website", "value": False, "points": 20, "reason": "no website"},
    {"field": "has_online_booking", "value": False, "points": 25, "reason": "no online booking"},
    {"field": "has_chatbot", "value": False, "points": 15, "reason": "no chatbot/AI"},
    {"field": "review_count_lt_50", "points": 15, "reason": "low review count"},
    {"field": "rating_lt_4", "points": 10, "reason": "below 4-star rating"},
    # Reachability signals
    {"field": "email", "value": True, "points": 10, "reason": "has email"},
    {"field": "phone", "value": True, "points": 5, "reason": "has phone"},
    # Tech signals (using competitor platforms we can replace or complement)
    {"field": "booking_platform_basic", "points": 15, "reason": "uses basic booking platform"},
]

BASIC_BOOKING_PLATFORMS = ["calendly", "squarespace", "wix", "square"]
ADVANCED_BOOKING_PLATFORMS = ["mindbody", "vagaro", "fresha", "jane_app", "boulevard", "zenoti"]


def score_lead(lead: dict) -> dict:
    """
    Score a lead and return updated lead dict with score and score_reason.

    Scoring logic:
    - No website: +20 (biggest opportunity, they're invisible online)
    - No online booking: +25 (core Automiqo value prop)
    - No chatbot: +15 (Automiqo replaces this)
    - Low reviews (<50): +15 (reputation problem we can fix)
    - Rating <4.0: +10 (customer experience problem)
    - Has email: +10 (we can reach them)
    - Has phone: +5 (we can call them)
    - Basic booking platform: +15 (easy to upgrade to Automiqo)
    - Advanced platform: -10 (harder sell, already invested)
    """
    score = 0
    reasons = []

    if not lead.get("has_website"):
        score += 20
        reasons.append("no website")

    if not lead.get("has_online_booking"):
        score += 25
        reasons.append("no online booking")

    if not lead.get("has_chatbot"):
        score += 15
        reasons.append("no AI/chatbot")

    review_count = lead.get("review_count", 0) or 0
    if review_count < 50:
        score += 15
        reasons.append(f"only {review_count} reviews")

    rating = lead.get("google_rating", 0) or 0
    if 0 < rating < 4.0:
        score += 10
        reasons.append(f"{rating}★ rating")

    if lead.get("email"):
        score += 10
        reasons.append("has email")

    if lead.get("phone"):
        score += 5
        reasons.append("has phone")

    bp = lead.get("booking_platform", "")
    if bp in BASIC_BOOKING_PLATFORMS:
        score += 15
        reasons.append(f"uses {bp} (easy upgrade)")
    elif bp in ADVANCED_BOOKING_PLATFORMS:
        score -= 10
        reasons.append(f"uses {bp} (harder sell)")

    # Bonus: no social media presence
    if not lead.get("instagram") and not lead.get("facebook"):
        score += 5
        reasons.append("no social presence")

    # Cap at 100
    score = min(score, 100)

    return {
        **lead,
        "score": score,
        "score_reason": ", ".join(reasons),
        "tier": "A" if score >= 75 else "B" if score >= 50 else "C",
    }


def segment_leads(leads: list[dict]) -> dict:
    """
    Segment leads into tiers and groups for targeted outreach.
    """
    tier_a = [l for l in leads if l.get("tier") == "A"]  # Score 75+
    tier_b = [l for l in leads if l.get("tier") == "B"]  # Score 50-74
    tier_c = [l for l in leads if l.get("tier") == "C"]  # Score <50

    # Group by key attribute
    no_booking = [l for l in leads if not l.get("has_online_booking")]
    no_website = [l for l in leads if not l.get("has_website")]
    has_calendly = [l for l in leads if l.get("booking_platform") == "calendly"]
    has_mindbody = [l for l in leads if l.get("booking_platform") == "mindbody"]

    return {
        "total": len(leads),
        "tier_a": {"count": len(tier_a), "leads": tier_a},
        "tier_b": {"count": len(tier_b), "leads": tier_b},
        "tier_c": {"count": len(tier_c), "leads": tier_c},
        "segments": {
            "no_booking_system": {"count": len(no_booking), "leads": no_booking},
            "no_website": {"count": len(no_website), "leads": no_website},
            "using_calendly": {"count": len(has_calendly), "leads": has_calendly},
            "using_mindbody": {"count": len(has_mindbody), "leads": has_mindbody},
        },
        "outreach_priority": sorted(
            tier_a, key=lambda x: x.get("score", 0), reverse=True
        )[:20],
    }
```

---

## STEP 5 — Create `backend/integrations/lead_intelligence.py`

```python
"""
Lead Intelligence Engine — orchestrates all stages.
This is what the Lead Manager agent calls.
"""
import asyncio
from uuid import UUID
from backend.integrations.serper_client import (
    search_google_maps_paginated,
    normalize_serper_result,
)
from backend.integrations.scrapling_enricher import enrich_leads_batch
from backend.integrations.lead_scorer import score_lead, segment_leads
from backend.memory.supabase_client import get_supabase
from backend.memory.leads import upsert_lead


# Industry search queries
INDUSTRY_QUERIES = {
    "medspa": [
        "med spa", "medical spa", "aesthetics clinic",
        "botox clinic", "laser aesthetics", "cosmetic clinic",
    ],
    "gym": [
        "gym", "fitness center", "personal training studio",
        "crossfit", "boutique fitness", "yoga studio",
    ],
    "salon": [
        "hair salon", "beauty salon", "nail salon",
        "barber shop", "blowout bar",
    ],
    "dental": [
        "dental office", "dentist", "dental clinic",
        "family dentistry", "cosmetic dentist",
    ],
    "wellness": [
        "wellness center", "chiropractic", "massage therapy",
        "physical therapy", "acupuncture",
    ],
}

# NJ cities to target
NJ_CITIES = [
    "Newark NJ", "Jersey City NJ", "Paterson NJ", "Elizabeth NJ",
    "Edison NJ", "Woodbridge NJ", "Lakewood NJ", "Toms River NJ",
    "Hamilton NJ", "Trenton NJ", "Clifton NJ", "Camden NJ",
    "Brick NJ", "Cherry Hill NJ", "Passaic NJ",
    "Bergen County NJ", "Essex County NJ", "Hudson County NJ",
    "Middlesex County NJ", "Union County NJ", "Monmouth County NJ",
]


async def run_discovery(
    business_id: UUID,
    industry: str,
    locations: list[str],
    limit_per_location: int = 20,
) -> list[dict]:
    """
    Stage 1: Discover businesses via Serper.dev Google Maps.
    Returns raw normalized leads (not yet enriched).
    """
    queries = INDUSTRY_QUERIES.get(industry, [industry])
    all_leads = []
    seen_names = set()

    for location in locations:
        for query in queries[:2]:  # Top 2 queries per location
            results = await search_google_maps_paginated(
                query=query,
                location=location,
                total_results=limit_per_location,
            )
            for raw in results:
                name = raw.get("title", "").lower().strip()
                if name and name not in seen_names:
                    seen_names.add(name)
                    lead = normalize_serper_result(raw, industry, location)
                    all_leads.append(lead)

            await asyncio.sleep(0.5)  # Rate limit between queries

    return all_leads


async def run_enrichment(leads: list[dict]) -> list[dict]:
    """
    Stage 2: Enrich leads with website data using Scrapling.
    Visits each website and extracts email, tech, booking platform, etc.
    """
    # Only enrich leads with websites
    with_website = [l for l in leads if l.get("website")]
    without_website = [l for l in leads if not l.get("website")]

    enriched = await enrich_leads_batch(
        with_website,
        max_concurrent=5,
        delay_between=0.3,
    )

    return enriched + without_website


async def run_scoring(leads: list[dict]) -> list[dict]:
    """Stage 3 + 4: Score and segment all leads."""
    return [score_lead(lead) for lead in leads]


async def save_leads_to_crm(business_id: UUID, leads: list[dict]) -> dict:
    """Stage 5: Save all leads to Supabase leads table with dedup."""
    saved = 0
    skipped = 0
    for lead in leads:
        try:
            await upsert_lead(business_id, lead)
            saved += 1
        except Exception:
            skipped += 1
    return {"saved": saved, "skipped": skipped}


async def run_full_pipeline(
    business_id: UUID,
    industry: str,
    locations: list[str] = None,
    limit_per_location: int = 20,
    skip_enrichment: bool = False,
) -> dict:
    """
    Run the complete Lead Intelligence Pipeline.
    Called by Lead Manager agent when owner asks for leads.

    Args:
        business_id: The Automiqo client's business ID
        industry: "medspa" | "gym" | "salon" | "dental" | "wellness"
        locations: List of location strings (defaults to NJ cities)
        limit_per_location: Max leads per location (20 = ~3 API calls)
        skip_enrichment: Set True for fast discovery-only run

    Returns:
        Summary dict with counts and top leads
    """
    if locations is None:
        locations = NJ_CITIES[:5]  # Default: top 5 NJ cities

    print(f"[Lead Intelligence] Starting pipeline for {industry} in {locations}")

    # Stage 1: Discovery
    print("[Stage 1] Discovering via Serper.dev...")
    raw_leads = await run_discovery(business_id, industry, locations, limit_per_location)
    print(f"[Stage 1] Found {len(raw_leads)} unique businesses")

    # Stage 2: Enrichment (optional)
    if not skip_enrichment:
        print("[Stage 2] Enriching with Scrapling...")
        leads = await run_enrichment(raw_leads)
        print(f"[Stage 2] Enriched {sum(1 for l in leads if l.get('enriched'))} leads")
    else:
        leads = raw_leads

    # Stage 3+4: Score and segment
    print("[Stage 3] Scoring leads...")
    scored_leads = await run_scoring(leads)
    segments = segment_leads(scored_leads)

    # Stage 5: Save to CRM
    print("[Stage 5] Saving to Supabase...")
    save_result = await save_leads_to_crm(business_id, scored_leads)

    return {
        "pipeline_complete": True,
        "industry": industry,
        "locations": locations,
        "total_discovered": len(raw_leads),
        "total_enriched": sum(1 for l in scored_leads if l.get("enriched")),
        "total_saved": save_result["saved"],
        "segments": {
            "tier_a_count": segments["tier_a"]["count"],
            "tier_b_count": segments["tier_b"]["count"],
            "tier_c_count": segments["tier_c"]["count"],
            "no_booking_system": segments["segments"]["no_booking_system"]["count"],
            "no_website": segments["segments"]["no_website"]["count"],
        },
        "top_20_leads": [
            {
                "name": l["company_name"],
                "score": l["score"],
                "tier": l["tier"],
                "phone": l["phone"],
                "email": l.get("email"),
                "booking_platform": l.get("booking_platform"),
                "score_reason": l["score_reason"],
            }
            for l in segments["outreach_priority"]
        ],
    }
```

---

## STEP 6 — Update Lead Manager Agent

Open `agents/departments/cmo/managers/lead_manager.py`

Add this method to the `LeadManager` class:

```python
    async def run_lead_pipeline(
        self,
        industry: str,
        locations: list[str] = None,
        limit_per_location: int = 20,
    ) -> dict:
        """
        Kick off the full Lead Intelligence Pipeline.
        Called when owner says 'Find me leads' or CEO delegates lead gen task.
        """
        from backend.integrations.lead_intelligence import run_full_pipeline
        return await run_full_pipeline(
            business_id=self.business_id,
            industry=industry,
            locations=locations,
            limit_per_location=limit_per_location,
        )
```

Update the `run()` method to detect lead generation intent:

```python
    async def run(self, question: str, context: dict | None = None) -> AgentResponse:
        question_lower = question.lower()

        # Detect lead generation intent
        is_lead_gen = any(w in question_lower for w in [
            "find leads", "find businesses", "scrape leads", "get leads",
            "find prospects", "lead generation", "find med spas",
            "find gyms", "find salons", "find dentists"
        ])

        if is_lead_gen:
            # Extract industry from question
            industry = "medspa"
            for ind in ["gym", "salon", "dental", "wellness", "medspa", "med spa"]:
                if ind.replace(" ", "") in question_lower.replace(" ", ""):
                    industry = ind.replace(" ", "")
                    break

            result = await self.run_lead_pipeline(
                industry=industry,
                locations=None,  # Default NJ cities
                limit_per_location=20,
            )
            return AgentResponse(
                status="ok",
                summary=(
                    f"Lead Intelligence Pipeline complete for {industry}. "
                    f"Found {result['total_discovered']} businesses, "
                    f"enriched {result['total_enriched']}, "
                    f"saved {result['total_saved']} to CRM. "
                    f"Tier A (highest fit): {result['segments']['tier_a_count']} leads. "
                    f"No booking system: {result['segments']['no_booking_system']} leads."
                ),
                metrics=result["segments"],
                recommendations=[
                    f"Start outreach with {result['segments']['tier_a_count']} Tier A leads",
                    f"{result['segments']['no_booking_system']} businesses have NO online booking — highest conversion probability",
                ]
            )

        # Otherwise run normal lead manager logic
        # ... (your existing code here)
```

---

## STEP 7 — Add n8n Workflow: `n8n/marketing/run_lead_pipeline.json`

Create this workflow as the primary trigger for lead intelligence:

```json
{
  "name": "Run Lead Intelligence Pipeline",
  "active": true,
  "nodes": [
    {
      "id": "wh-001",
      "name": "Webhook Trigger",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "parameters": {
        "httpMethod": "POST",
        "path": "run_lead_pipeline",
        "responseMode": "responseNode"
      }
    },
    {
      "id": "ex-001",
      "name": "Extract Params",
      "type": "n8n-nodes-base.set",
      "typeVersion": 3,
      "position": [460, 300],
      "parameters": {
        "mode": "manual",
        "assignments": {
          "assignments": [
            {"id": "a1", "name": "business_id", "value": "={{ $json.business_id }}", "type": "string"},
            {"id": "a2", "name": "task_id", "value": "={{ $json.task_id }}", "type": "string"},
            {"id": "a3", "name": "industry", "value": "={{ $json.parameters.industry || 'medspa' }}", "type": "string"},
            {"id": "a4", "name": "locations", "value": "={{ $json.parameters.locations || [] }}", "type": "array"},
            {"id": "a5", "name": "limit", "value": "={{ $json.parameters.limit_per_location || 20 }}", "type": "number"}
          ]
        }
      }
    },
    {
      "id": "pipeline-001",
      "name": "Run Lead Pipeline",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [680, 300],
      "parameters": {
        "method": "POST",
        "url": "={{ $env.BACKEND_URL }}/leads/pipeline/run",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "business_id", "value": "={{ $('Extract Params').item.json.business_id }}"},
            {"name": "industry", "value": "={{ $('Extract Params').item.json.industry }}"},
            {"name": "locations", "value": "={{ $('Extract Params').item.json.locations }}"},
            {"name": "limit_per_location", "value": "={{ $('Extract Params').item.json.limit }}"}
          ]
        }
      }
    },
    {
      "id": "wr-001",
      "name": "Write Result to Tasks",
      "type": "n8n-nodes-base.supabase",
      "typeVersion": 1,
      "position": [900, 300],
      "credentials": {"supabaseApi": {"id": "supabase_main", "name": "Supabase_Main"}},
      "parameters": {
        "operation": "update",
        "tableId": "tasks",
        "filterType": "manual",
        "filters": {
          "conditions": [
            {"keyName": "id", "keyValue": "={{ $('Extract Params').item.json.task_id }}", "condition": "eq"},
            {"keyName": "business_id", "keyValue": "={{ $('Extract Params').item.json.business_id }}", "condition": "eq"}
          ]
        },
        "dataToSend": "defineBelow",
        "fieldsUi": {
          "fieldValues": [
            {"fieldId": "status", "fieldValue": "completed"},
            {"fieldId": "result", "fieldValue": "={{ JSON.stringify($('Run Lead Pipeline').item.json) }}"},
            {"fieldId": "completed_at", "fieldValue": "={{ new Date().toISOString() }}"}
          ]
        }
      }
    },
    {
      "id": "rs-001",
      "name": "Respond Success",
      "type": "n8n-nodes-base.respondToWebhook",
      "typeVersion": 1,
      "position": [1120, 300],
      "parameters": {
        "respondWith": "json",
        "responseBody": "={{ JSON.stringify($('Run Lead Pipeline').item.json) }}",
        "options": {"responseCode": 200}
      }
    }
  ],
  "connections": {
    "Webhook Trigger": {"main": [[{"node": "Extract Params", "type": "main", "index": 0}]]},
    "Extract Params": {"main": [[{"node": "Run Lead Pipeline", "type": "main", "index": 0}]]},
    "Run Lead Pipeline": {"main": [[{"node": "Write Result to Tasks", "type": "main", "index": 0}]]},
    "Write Result to Tasks": {"main": [[{"node": "Respond Success", "type": "main", "index": 0}]]}
  },
  "tags": ["marketing", "leads", "company-os"]
}
```

---

## STEP 8 — Add Backend API Endpoints

Add to `backend/api/leads.py`:

```python
from backend.integrations.lead_intelligence import run_full_pipeline
from pydantic import BaseModel

class PipelineRequest(BaseModel):
    business_id: str
    industry: str = "medspa"
    locations: list[str] = []
    limit_per_location: int = 20
    skip_enrichment: bool = False


@router.post("/leads/pipeline/run")
async def run_pipeline(req: PipelineRequest):
    """
    Run the full Lead Intelligence Pipeline.
    Kicked off by n8n workflow or directly by Lead Manager agent.
    Long-running — consider running as background task for large batches.
    """
    from fastapi import BackgroundTasks
    result = await run_full_pipeline(
        business_id=UUID(req.business_id),
        industry=req.industry,
        locations=req.locations if req.locations else None,
        limit_per_location=req.limit_per_location,
        skip_enrichment=req.skip_enrichment,
    )
    return result


@router.post("/leads/pipeline/discover-only")
async def discover_only(req: PipelineRequest):
    """
    Discovery only — no enrichment. Fast, cheap.
    Use when you want a quick count before committing to full run.
    """
    req.skip_enrichment = True
    return await run_pipeline(req)


@router.get("/leads/{business_id}/intelligence-summary")
async def intelligence_summary(business_id: UUID):
    """
    Get summary of all leads with scoring breakdown.
    Shows how many are in each tier and segment.
    """
    from backend.memory.leads import get_lead_stats, get_leads
    stats = await get_lead_stats(business_id)
    top_leads = await get_leads(business_id, status="new", limit=5, min_score=70)
    return {
        "pipeline_stats": stats,
        "top_5_leads": top_leads,
    }
```

---

## STEP 9 — Update Supabase Schema

Add these columns to the `leads` table (if not already present):

```sql
-- Technology and enrichment columns
ALTER TABLE leads ADD COLUMN IF NOT EXISTS tech_stack TEXT[] DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS booking_platform TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS has_chatbot BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS pricing_mentioned BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS instagram TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS facebook TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS linkedin TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS tiktok TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS owner_name TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS services_found TEXT[] DEFAULT '{}';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS tier TEXT DEFAULT 'C';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS category TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS business_hours JSONB DEFAULT '[]';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS google_place_id TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enriched BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enrichment_failed BOOLEAN DEFAULT false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_source TEXT;

-- Index for tier-based queries
CREATE INDEX IF NOT EXISTS leads_tier_score ON leads(business_id, tier, score DESC);
CREATE INDEX IF NOT EXISTS leads_booking_platform ON leads(business_id, booking_platform);
```

---

## STEP 10 — Update CLAUDE.md

Add to `.claude/CLAUDE.md`:

```markdown
## Lead Intelligence Engine

### Architecture
3-stage pipeline: Serper.dev (Discovery) → Scrapling (Enrichment) → Scorer

### Files
- backend/integrations/serper_client.py — Google Maps API calls
- backend/integrations/scrapling_enricher.py — Website data extraction
- backend/integrations/lead_scorer.py — 0-100 scoring + segmentation
- backend/integrations/lead_intelligence.py — Orchestrates all stages
- n8n/marketing/run_lead_pipeline.json — n8n trigger workflow
- backend/api/leads.py — POST /leads/pipeline/run endpoint

### When to use Serper.dev
- Finding businesses by keyword + location (Google Maps)
- Searching directories (Yelp, BBB, YellowPages via web search)
- Fast, cheap: $2/1000 queries

### When to use Scrapling
- Visiting business websites to extract email, tech stack, services
- Three fetcher modes (escalate as needed):
  1. Fetcher — fast, for static sites (90% of local biz sites)
  2. StealthyFetcher — bypasses Cloudflare (some med spas use it)
  3. DynamicFetcher — full browser, for React/JS-heavy sites (slow, use sparingly)
- Install: pip install 'scrapling[fetchers]' && scrapling install

### Scoring Logic
- No online booking: +25 (core Automiqo value prop)
- No website: +20
- No chatbot: +15
- <50 reviews: +15
- Has email: +10
- Has phone: +5
- Using Calendly/Wix: +15 (easy upgrade target)
- Using Mindbody/Vagaro: -10 (harder sell)

### Industry Queries
See INDUSTRY_QUERIES dict in lead_intelligence.py
Default NJ locations: See NJ_CITIES list

### DO NOT
- Run DynamicFetcher on more than 3 concurrent sites (too much RAM)
- Skip the fallback chain — always try Fetcher first
- Store raw HTML in Supabase — only store extracted fields
```

---

## Testing Commands

```bash
# Test Serper discovery
python3 -c "
import asyncio
from backend.integrations.serper_client import search_google_maps
results = asyncio.run(search_google_maps('med spa', 'Newark NJ', 5))
print(f'Found {len(results)} results')
for r in results:
    print(f'  - {r.get(\"title\")} | {r.get(\"phoneNumber\")} | {r.get(\"website\",\"no website\")}')
"

# Test Scrapling enrichment on one URL
python3 -c "
import asyncio
from backend.integrations.scrapling_enricher import enrich_lead_website
result = asyncio.run(enrich_lead_website('https://example-medspa.com'))
print(result)
"

# Test full pipeline (discovery only, fast)
curl -X POST http://localhost:8000/leads/pipeline/discover-only \
  -H 'Content-Type: application/json' \
  -d '{
    \"business_id\": \"00000000-0000-0000-0000-000000000001\",
    \"industry\": \"medspa\",
    \"locations\": [\"Newark NJ\"],
    \"limit_per_location\": 5
  }'

# Test full pipeline with enrichment
curl -X POST http://localhost:8000/leads/pipeline/run \
  -H 'Content-Type: application/json' \
  -d '{
    \"business_id\": \"00000000-0000-0000-0000-000000000001\",
    \"industry\": \"medspa\",
    \"locations\": [\"Newark NJ\", \"Jersey City NJ\"],
    \"limit_per_location\": 10
  }'
```

---

## Cost Estimate

| Stage | Tool | Cost Per 100 Leads |
|---|---|---|
| Discovery | Serper.dev | ~$0.02 (10 API calls) |
| Enrichment | Scrapling | $0 (self-hosted) |
| Scoring | Python | $0 |
| **Total** | | **~$0.02 per 100 leads** |

For 10,000 leads: ~$2 in Serper costs. Everything else is free.
