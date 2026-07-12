"""UGC Ad Studio / Ad-Spy API — generate short-form ad concepts + (optional) video.

Mounted by main.py under the protected group (the caller adds `_protected`), so
these routes inherit the same auth/dependency wrapping as the other business
modules. Routes are thin and defer to backend.integrations.ugc_ad_studio.
"""
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["ugc"])


class ConceptsRequest(BaseModel):
    product: str
    count: int = 5
    platform: str = "tiktok"
    angles: Optional[List[str]] = None


class VideoRequest(BaseModel):
    concept: dict


@router.post("/ugc/{business_id}/concepts")
async def ugc_concepts(business_id: str, req: ConceptsRequest):
    """Generate `count` A/B-test-ready ad concepts for a product on a platform."""
    from backend.integrations.ugc_ad_studio import generate_ad_concepts
    return await generate_ad_concepts(
        business_id, req.product, req.count, req.platform, req.angles
    )


@router.post("/ugc/{business_id}/video")
async def ugc_video(business_id: str, req: VideoRequest):
    """Render (or, without VIDEO_API_KEY, return the script for) one concept."""
    from backend.integrations.ugc_ad_studio import generate_video
    return await generate_video(req.concept, business_id)
