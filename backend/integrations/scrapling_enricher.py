"""
Scrapling-based website enrichment for lead intelligence.
Replaces lead_enricher.py for the new pipeline.
Three-tier fallback: Fetcher -> StealthyFetcher -> DynamicFetcher.
"""
import re
import asyncio
from typing import Optional
from urllib.parse import urlparse

TECH_PATTERNS = {
    "mindbody": ["mindbody", "mindbodyonline.com"],
    "fresha": ["fresha.com", "fresha", "shedul.com"],
    "vagaro": ["vagaro.com", "vagaro"],
    "booksy": ["booksy.com", "booksy"],
    "calendly": ["calendly.com", "calendly"],
    "acuity": ["acuityscheduling.com", "acuity"],
    "square": ["squareup.com", "square.site"],
    "squarespace": ["squarespace.com", "static.squarespace"],
    "wix": ["wix.com", "wixsite"],
    "jane_app": ["jane.app", "janeapp"],
    "boulevard": ["joinblvd.com", "boulevard"],
    "zenoti": ["zenoti.com"],
    "stripe": ["js.stripe.com"],
    "hubspot": ["hubspot.com", "hs-scripts"],
    "mailchimp": ["mailchimp.com", "chimpstatic"],
    "klaviyo": ["klaviyo.com"],
    "intercom": ["intercom.io", "intercomcdn"],
    "drift": ["drift.com", "driftt"],
    "tidio": ["tidio.com"],
    "zendesk": ["zendesk.com", "zopim"],
    "tawk": ["tawk.to"],
    "crisp": ["crisp.chat"],
    "google_analytics": ["google-analytics.com", "gtag/js", "G-"],
    "facebook_pixel": ["fbq(", "connect.facebook.net"],
}

BOOKING_KEYWORDS = ["book now", "book online", "book appointment", "schedule appointment",
                    "schedule now", "request appointment", "online booking", "book a visit"]
CHAT_KEYWORDS = ["chat with us", "live chat", "chat now", "start chat", "message us"]
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE)
SOCIAL_PATTERNS = {
    "instagram": re.compile(r"instagram\.com/([a-zA-Z0-9_.]+)", re.I),
    "facebook": re.compile(r"facebook\.com/([a-zA-Z0-9_.]+)", re.I),
    "linkedin": re.compile(r"linkedin\.com/(?:company|in)/([a-zA-Z0-9_\-]+)", re.I),
    "tiktok": re.compile(r"tiktok\.com/@([a-zA-Z0-9_.]+)", re.I),
}



def _extract_from_html(url: str, html: str, page_obj=None) -> dict:
    """Extract all enrichment data from raw HTML."""
    html_lower = html.lower()
    result = {}
    # 1. Email
    emails = EMAIL_RE.findall(html)
    filtered = [e for e in emails if not any(x in e.lower() for x in
        ["noreply", "no-reply", "example", "test@", "admin@", ".png", ".jpg", "sentry", "wixpress"])]
    result["email"] = filtered[0] if filtered else None
    # 2. Social media
    for platform, pattern in SOCIAL_PATTERNS.items():
        match = pattern.search(html)
        if match:
            handle = match.group(1).rstrip("/")
            if handle.lower() not in ["sharer", "share", "pages", "login", "home"]:
                result[platform] = handle
    # 3. Tech detection
    detected_tech = [tech for tech, patterns in TECH_PATTERNS.items()
                     if any(p.lower() in html_lower for p in patterns)]
    result["tech_stack"] = detected_tech
    # 4. Booking platform
    booking_platforms = ["mindbody","fresha","vagaro","booksy","calendly","acuity","square","jane_app","boulevard","zenoti"]
    for bp in booking_platforms:
        if bp in detected_tech:
            result["booking_platform"] = bp
            result["has_online_booking"] = True
            break
    else:
        result["has_online_booking"] = any(kw in html_lower for kw in BOOKING_KEYWORDS)
        result["booking_platform"] = None
    # 5. Chatbot
    result["has_chatbot"] = any(
        any(p in html_lower for p in TECH_PATTERNS.get(ct, []))
        for ct in ["intercom", "drift", "tidio", "zendesk", "tawk", "crisp"]
    ) or any(kw in html_lower for kw in CHAT_KEYWORDS)
    # 6. Pricing
    result["pricing_mentioned"] = any(re.search(p, html_lower) for p in
        [r"\$\d+", r"pricing", r"price list", r"our rates", r"per session"])
    # 7. Services from headings
    services = []
    if page_obj:
        try:
            headings = page_obj.css("h2, h3, h4")
            for h in headings[:20]:
                text = getattr(h, "text", str(h)).strip()
                if text and 5 < len(text) < 60:
                    services.append(text)
        except Exception:
            pass
    result["services"] = services[:15]
    # 8. Phone backup
    phone_re = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
    phones = phone_re.findall(html)
    result["phone_from_site"] = phones[0] if phones else None
    return result



async def _fetch_with_fallback(url: str, timeout: int = 15) -> tuple[Optional[str], Optional[object]]:
    """Try Fetcher -> StealthyFetcher -> DynamicFetcher in order."""
    try:
        from scrapling.fetchers import Fetcher
        page = await asyncio.to_thread(Fetcher.fetch, url, timeout=timeout, stealthy_headers=True)
        if page and len(page.html) > 500:
            return page.html, page
    except Exception:
        pass
    try:
        from scrapling.fetchers import StealthyFetcher
        page = await asyncio.to_thread(StealthyFetcher.fetch, url, headless=True, network_idle=True, timeout=timeout*2)
        if page and len(page.html) > 500:
            return page.html, page
    except Exception:
        pass
    try:
        from scrapling.fetchers import DynamicFetcher
        page = await asyncio.to_thread(DynamicFetcher.fetch, url, headless=True, network_idle=True, timeout=timeout*3)
        if page and len(page.html) > 500:
            return page.html, page
    except Exception:
        pass
    # Final fallback: plain httpx
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(url)
            if len(resp.text) > 200:
                return resp.text, None
    except Exception:
        pass
    return None, None


async def enrich_lead_website(website_url: str) -> dict:
    """Full website enrichment: homepage + /contact fallback."""
    if not website_url or not website_url.startswith("http"):
        return {"enrichment_failed": True, "reason": "no_website"}
    enrichment = {"enriched": True}
    html, page = await _fetch_with_fallback(website_url)
    if not html:
        return {"enrichment_failed": True, "reason": "fetch_failed"}
    data = _extract_from_html(website_url, html, page)
    enrichment.update(data)
    if not enrichment.get("email"):
        base = f"{urlparse(website_url).scheme}://{urlparse(website_url).netloc}"
        for path in ["/contact", "/contact-us", "/about", "/about-us"]:
            try:
                c_html, c_page = await _fetch_with_fallback(base + path, timeout=10)
                if c_html:
                    c_data = _extract_from_html(base + path, c_html, c_page)
                    if c_data.get("email"):
                        enrichment["email"] = c_data["email"]
                        enrichment["email_source"] = path
                        break
            except Exception:
                continue
    return enrichment


async def enrich_with_fallback(website_url: str) -> dict:
    """
    Smart enrichment: Scrapling first, Crawl4AI if Scrapling fails.
    Use this as the single entry point for website enrichment.
    """
    if not website_url:
        return {"enrichment_failed": True, "reason": "no_url"}
    result = await enrich_lead_website(website_url)
    if result.get("enriched") and (result.get("email") or result.get("tech_stack") or result.get("has_online_booking") is not None):
        result["enrichment_method"] = "scrapling"
        return result
    if result.get("enrichment_failed"):
        from backend.integrations.crawl4ai_extractor import extract_business_profile_ai
        ai_result = await extract_business_profile_ai(website_url)
        if ai_result.get("extracted_by") == "crawl4ai":
            ai_result["enrichment_method"] = "crawl4ai"
            ai_result["enriched"] = True
            return ai_result
    result["enrichment_method"] = "scrapling_partial"
    return result
