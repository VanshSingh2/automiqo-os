"""Content Autopilot API — generate & stage a brand-voice social calendar.

Mounted by main.py under the protected routers (require_auth). Endpoints are
thin wrappers over backend.integrations.content_autopilot (lazy-imported).
"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["content"])


class CalendarRequest(BaseModel):
    days: Optional[int] = 7
    platforms: Optional[list] = None
    topics: Optional[list] = None


class ScheduleRequest(BaseModel):
    posts: list = []


@router.post("/content/{business_id}/calendar")
async def generate_content_calendar(business_id: str, req: Optional[CalendarRequest] = None):
    """Generate a full social-media content calendar in the brand voice."""
    from backend.integrations.content_autopilot import generate_calendar
    req = req or CalendarRequest()
    return await generate_calendar(
        business_id, days=req.days or 7, platforms=req.platforms, topics=req.topics)


@router.post("/content/{business_id}/schedule")
async def schedule_content_calendar(business_id: str, req: ScheduleRequest):
    """Stage generated posts into content_posts for the publishing workflow."""
    from backend.integrations.content_autopilot import schedule_calendar
    return await schedule_calendar(business_id, req.posts)
