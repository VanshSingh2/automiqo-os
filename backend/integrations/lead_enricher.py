"""
Lead Enricher — extract email, phone, services, booking system from websites using Scrapling.
Layer 2 of the lead pipeline.
"""
import re
import asyncio
from typing import Optional


# Known booking platforms — if found in page source, lead has a booking system
BOOKING_PLATFORMS = [
    ("mindbody", "Mindbody"), ("vagaro", "Vagaro"), ("fresha", "Fresha"),
    ("booksy", "Booksy"), ("acuityscheduling", "Acuity"), ("calendly", "Calendly"),
    ("cal.com", "Cal.com"), ("square", "Square Appointments"), ("zenoti", "Zenoti"),
    ("boulevard", "Boulevard"), ("booker", "Booker"), ("glofox", "Glofox"),
    ("schedulicity", "Schedulicity"), ("timely", "Timely"), ("setmore", "Setmore"),
    ("simplybook", "SimplyBook"), ("bookingpress", "BookingPress"),
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?1?\s?[\.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})")
INSTAGRAM_RE = re.compile(r"instagram\.com/([a-zA-Z0-9._]+)")
SOCIAL_RE = {
    "facebook": re.compile(r"facebook\.com/([a-zA-Z0-9.]+)"),
    "tiktok": re.compile(r"tiktok\.com/@([a-zA-Z0-9._]+)"),
}


def _detect_booking(html: str) -> tuple[bool, Optional[str]]:
    html_lower = html.lower()
    for keyword, platform_name in BOOKING_PLATFORMS:
        if keyword in html_lower:
            return True, platform_name
    return False, None


def _extract_emails(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    # Filter out common false positives
    skip = ["example.com", "yourdomain", "email@", "info@example", "test@", "noreply@", "sentry"]
    return list(dict.fromkeys(
        e for e in found if not any(s in e.lower() for s in skip)
    ))


def _extract_phones(html: str) -> list[str]:
    found = PHONE_RE.findall(html)
    # Return formatted, deduplicated
    seen = set()
    result = []
    for p in found:
        cleaned = re.sub(r"[^\d]", "", p)
        if len(cleaned) >= 10 and cleaned not in seen:
            seen.add(cleaned)
            result.append(p.strip())
    return result[:3]


def _extract_services(html: str, page_text: str) -> list[str]:
    """Extract service keywords from page content."""
    # Common service indicators for local businesses
    service_keywords = [
        "botox", "filler", "laser", "facial", "massage", "waxing", "microblading",
        "lashes", "nails", "haircut", "color", "highlights", "blowout", "keratin",
        "iv therapy", "coolsculpting", "microneedling", "hydrafacial", "chemical peel",
        "teeth whitening", "dental", "cleaning", "x-ray", "personal training",
        "yoga", "pilates", "spin", "crossfit", "boxing", "zumba",
        "manicure", "pedicure", "gel", "acrylic", "nail art",
    ]
    found = []
    page_lower = page_text.lower()
    for svc in service_keywords:
        if svc in page_lower:
            found.append(svc.title())
    return found[:10]


async def enrich_lead(website_url: str, timeout: int = 15) -> dict:
    """
    Enrich a single lead by scraping their website with Scrapling.
    Extracts email, phone, services, booking system, social links.
    """
    if not website_url or not website_url.startswith("http"):
        return {"error": "No valid URL", "enriched": False}

    result = {
        "website": website_url,
        "emails": [],
        "phone_from_web": None,
        "services": [],
        "has_booking_system": False,
        "booking_platform": None,
        "instagram": None,
        "social_links": {},
        "enriched": False,
    }

    try:
        from scrapling import AsyncFetcher
        fetcher = AsyncFetcher(auto_match=False)

        # Scrape homepage
        page = await fetcher.get(website_url, timeout=timeout)
        html = str(page.html) if hasattr(page, "html") else ""
        text = page.get_all_text(separator=" ") if hasattr(page, "get_all_text") else html

        # Extract data from homepage
        result["emails"] = _extract_emails(html)
        phones = _extract_phones(html)
        if phones:
            result["phone_from_web"] = phones[0]
        result["has_booking_system"], result["booking_platform"] = _detect_booking(html)
        result["services"] = _extract_services(html, text)

        ig = INSTAGRAM_RE.search(html)
        if ig and ig.group(1) not in ("p", "reel", "stories", "explore"):
            result["instagram"] = ig.group(1)

        for platform, pattern in SOCIAL_RE.items():
            m = pattern.search(html)
            if m:
                result["social_links"][platform] = m.group(1)

        # If no email on homepage, try /contact
        if not result["emails"]:
            contact_urls = [
                website_url.rstrip("/") + "/contact",
                website_url.rstrip("/") + "/contact-us",
                website_url.rstrip("/") + "/about",
            ]
            for url in contact_urls[:2]:
                try:
                    contact_page = await fetcher.get(url, timeout=10)
                    contact_html = str(contact_page.html) if hasattr(contact_page, "html") else ""
                    emails = _extract_emails(contact_html)
                    if emails:
                        result["emails"] = emails
                        # Also check booking system on contact page
                        if not result["has_booking_system"]:
                            result["has_booking_system"], result["booking_platform"] = _detect_booking(contact_html)
                        break
                except Exception:
                    pass

        result["email"] = result["emails"][0] if result["emails"] else None
        result["enriched"] = bool(result["emails"] or result["services"] or result["has_booking_system"])

    except ImportError:
        # Fallback: simple httpx scrape if Scrapling not installed
        try:
            import httpx
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(website_url, headers={"User-Agent": "Mozilla/5.0"})
                html = r.text
            result["emails"] = _extract_emails(html)
            result["email"] = result["emails"][0] if result["emails"] else None
            result["has_booking_system"], result["booking_platform"] = _detect_booking(html)
            phones = _extract_phones(html)
            if phones:
                result["phone_from_web"] = phones[0]
            result["enriched"] = True
        except Exception as e:
            result["error"] = str(e)

    except Exception as e:
        result["error"] = str(e)

    return result


async def enrich_leads_batch(leads: list[dict], max_concurrent: int = 5) -> list[dict]:
    """Enrich multiple leads in parallel."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def enrich_one(lead: dict) -> dict:
        website = lead.get("website", "")
        if not website:
            return lead
        async with semaphore:
            info = await enrich_lead(website)
            if info.get("enriched"):
                if info.get("email") and not lead.get("email"):
                    lead["email"] = info["email"]
                if info.get("phone_from_web") and not lead.get("phone"):
                    lead["phone"] = info["phone_from_web"]
                if info.get("services"):
                    lead["services_found"] = info["services"]
                lead["has_booking_system"] = info.get("has_booking_system", False)
                if info.get("booking_platform"):
                    lead["booking_platform"] = info["booking_platform"]
                if info.get("instagram"):
                    lead["instagram"] = info["instagram"]
                lead["enriched"] = True
        return lead

    return list(await asyncio.gather(*[enrich_one(l) for l in leads]))
