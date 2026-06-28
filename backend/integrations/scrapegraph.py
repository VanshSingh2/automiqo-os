"""ScrapeGraphAI API — extract structured data from websites for lead enrichment."""
import os
import asyncio
from typing import Optional


async def extract_business_info(website_url: str) -> dict:
    """Extract email, phone, services, booking system from a business website."""
    try:
        from scrapegraph_py import AsyncScrapeGraphAI
        async with AsyncScrapeGraphAI(api_key=os.getenv("SGAI_API_KEY", "")) as sgai:
            result = await sgai.extract(
                url=website_url,
                prompt=(
                    "Extract: email address, phone number, list of services, "
                    "booking or appointment URL, Instagram handle, owner name, "
                    "whether prices are shown on the site."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "phone": {"type": "string"},
                        "services": {"type": "array", "items": {"type": "string"}},
                        "booking_url": {"type": "string"},
                        "instagram": {"type": "string"},
                        "has_booking_system": {"type": "boolean"},
                        "pricing_mentioned": {"type": "boolean"},
                        "owner_name": {"type": "string"},
                    }
                }
            )
        if result.status == "success" and result.data:
            data = result.data.get("results", {})
            return {
                "email": data.get("email"),
                "phone": data.get("phone"),
                "services": data.get("services", []),
                "booking_url": data.get("booking_url"),
                "instagram": data.get("instagram"),
                "has_booking_system": bool(data.get("has_booking_system")),
                "pricing_mentioned": bool(data.get("pricing_mentioned")),
                "owner_name": data.get("owner_name"),
                "scraped_from": website_url,
            }
    except ImportError:
        return {"error": "scrapegraph-py not installed", "scraped_from": website_url}
    except Exception as e:
        return {"error": str(e), "scraped_from": website_url}
    return {}


async def enrich_leads_batch(leads: list, max_concurrent: int = 3) -> list:
    """Enrich multiple leads with website data in parallel (max 3 at once for free tier)."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def enrich_one(lead: dict) -> dict:
        website = lead.get("website", "")
        if not website or not str(website).startswith("http"):
            return lead
        async with semaphore:
            info = await extract_business_info(website)
            if not info.get("error"):
                if not lead.get("email") and info.get("email"):
                    lead["email"] = info["email"]
                if info.get("services"):
                    lead["services_found"] = info["services"]
                if info.get("has_booking_system") is not None:
                    lead["has_booking_system"] = info["has_booking_system"]
                if info.get("owner_name"):
                    lead["owner_name"] = info["owner_name"]
                lead["enriched"] = True
        return lead

    return list(await asyncio.gather(*[enrich_one(l) for l in leads]))
