"""
Crawl4AI extractor — AI-powered structured data extraction.
Layer 2 enrichment fallback when Scrapling fails.
Cost per extraction: ~$0.0002 (GPT-4o-mini).
"""
import os
import json
import asyncio
from typing import Optional
from pydantic import BaseModel


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


async def extract_business_profile_ai(website_url: str) -> dict:
    """
    Use Crawl4AI + GPT-4o-mini to extract structured business data.
    Falls back gracefully if crawl4ai not installed or extraction fails.
    """
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
        from crawl4ai.extraction_strategy import LLMExtractionStrategy
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

        strategy = LLMExtractionStrategy(
            provider="openai/gpt-4o-mini",
            api_token=os.getenv("OPENAI_API_KEY"),
            schema=BusinessProfile.model_json_schema(),
            extraction_type="schema",
            instruction=(
                "Extract business contact and technology info. "
                "For booking_platform look for: mindbody, vagaro, fresha, booksy, "
                "calendly, acuity, square, jane_app, boulevard, zenoti. "
                "Set has_online_booking=true if any booking button or form exists. "
                "Set has_chatbot=true if chat bubble or chatbot widget present. "
                "Return null for fields not clearly on the page."
            ),
            apply_chunking=False,
        )
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            extraction_strategy=strategy,
            markdown_generator=DefaultMarkdownGenerator(options={"ignore_links": False}),
            page_timeout=20000,
            wait_for_images=False,
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=website_url, config=config)
        if result.success and result.extracted_content:
            data = json.loads(result.extracted_content)
            if isinstance(data, list) and data:
                data = data[0]
            return {**data, "extracted_by": "crawl4ai"}
    except ImportError:
        pass
    except Exception:
        pass
    return {"extracted_by": "crawl4ai_failed"}


async def get_page_as_markdown(url: str) -> Optional[str]:
    """Get clean markdown from any URL for further processing."""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            markdown_generator=DefaultMarkdownGenerator(options={"ignore_links": True, "ignore_images": True}),
            page_timeout=15000,
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
        if result.success and result.markdown:
            return result.markdown.raw_markdown
    except Exception:
        pass
    return None
