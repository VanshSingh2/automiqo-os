"""
UGC Ad Studio / Ad-Spy — generates unlimited short-form ad concepts for
TikTok / Instagram Reels and (optionally) renders influencer-style UGC videos.

The concept generator produces multiple *hooks* and *angles* for the same
product so a business can A/B test creative at scale. Each concept ships with
an influencer-style script, a CTA and a visual direction the owner (or an
editor/video model) can shoot from.

Design notes:
  * async, lazy imports, defensive — safe to call from an API route or an
    autonomous marketing loop; never raises on a provider/LLM failure.
  * LLM construction is delegated to BaseAgent._build_dept_llm so this module
    respects the same DEPT_MODEL / provider config as every dept agent.
  * Real video rendering is OPTIONAL: only attempted when VIDEO_API_KEY is set.
    Without it we return the script so nothing breaks in tests or offline.
"""
from __future__ import annotations

import json
import os

# Default creative angles used to spread A/B-test variants across a batch when
# the caller does not supply their own. Kept broad + platform-agnostic.
_DEFAULT_ANGLES = [
    "problem/solution",
    "before & after transformation",
    "founder story / authenticity",
    "social proof / testimonial",
    "unexpected hook / pattern interrupt",
    "day-in-the-life / UGC vlog",
    "listicle / top reasons",
    "objection-buster",
]

_PLATFORM_GUIDE = {
    "tiktok": (
        "TikTok short-form (9:16, 15-40s). Native, casual, hand-held UGC feel. "
        "Open with a scroll-stopping spoken hook in the first 2 seconds, fast "
        "cuts, trending-sound friendly, captions on-screen."
    ),
    "reels": (
        "Instagram Reels short-form (9:16, 15-45s). Polished-but-authentic UGC "
        "creator style. Strong visual hook + text overlay in the first 2 "
        "seconds, aspirational yet relatable, clear single CTA at the end."
    ),
}


def _platform_brief(platform: str) -> str:
    return _PLATFORM_GUIDE.get((platform or "").lower().strip(), _PLATFORM_GUIDE["tiktok"])


def _coerce_content(raw) -> str:
    """Flatten LLM response content (str | list-of-blocks | other) to text."""
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or block.get("content", ""))
            else:
                parts.append(str(block))
        return "".join(parts)
    if isinstance(raw, str):
        return raw
    return str(raw)


def _extract_json(text: str):
    """Best-effort parse of an LLM payload that may be fenced or chatty."""
    import re

    if not text:
        return None
    m = re.search(r"```[\w]*\s*([\s\S]*?)```", text)
    candidate = m.group(1).strip() if m else text.strip()
    # Try the whole candidate first, then the widest {...} / [...] slice.
    for attempt in (candidate,):
        try:
            return json.loads(attempt)
        except Exception:
            pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except Exception:
                continue
    return None


def _normalize_concept(item: dict) -> dict:
    """Coerce a raw concept dict into the strict 5-field shape we promise."""
    item = item if isinstance(item, dict) else {}
    return {
        "hook": str(item.get("hook", "") or "").strip(),
        "angle": str(item.get("angle", "") or "").strip(),
        "script": str(item.get("script", "") or "").strip(),
        "cta": str(item.get("cta", "") or "").strip(),
        "visual_direction": str(
            item.get("visual_direction", item.get("visuals", "")) or ""
        ).strip(),
    }


def _parse_concepts(payload) -> list[dict]:
    """Pull a list of concept dicts out of whatever shape the LLM returned."""
    if payload is None:
        return []
    concepts = None
    if isinstance(payload, list):
        concepts = payload
    elif isinstance(payload, dict):
        for key in ("concepts", "ads", "variants", "results", "items"):
            if isinstance(payload.get(key), list):
                concepts = payload[key]
                break
        if concepts is None:
            # A single concept object.
            concepts = [payload]
    if not isinstance(concepts, list):
        return []
    return [_normalize_concept(c) for c in concepts if isinstance(c, dict)]


async def generate_ad_concepts(
    business_id,
    product,
    count: int = 5,
    platform: str = "tiktok",
    angles: list | None = None,
) -> dict:
    """
    Generate ``count`` short-form ad concepts for ``product`` tuned to
    ``platform``. Each concept has {hook, angle, script, cta,
    visual_direction}. Hooks/angles are intentionally varied for A/B testing.

    Returns {"platform": platform, "concepts": [...]}; on any failure returns
    {"platform": platform, "concepts": []}. Never raises.
    """
    try:
        count = max(1, min(int(count or 5), 25))
    except Exception:
        count = 5

    platform = (platform or "tiktok").lower().strip() or "tiktok"
    angle_pool = [a for a in (angles or _DEFAULT_ANGLES) if str(a).strip()]
    # Spread the requested angles across the batch for variety.
    chosen_angles = [angle_pool[i % len(angle_pool)] for i in range(count)] if angle_pool else []

    brief = _platform_brief(platform)
    system = (
        "You are an elite UGC/short-form performance-marketing creative director "
        "and ad-spy analyst. You write scroll-stopping, native, influencer-style "
        "video ads that convert. You always reply with STRICT JSON only — no "
        "prose, no markdown fences."
    )
    angle_line = (
        f"Use a DIFFERENT angle for each concept, drawn from: {', '.join(chosen_angles)}."
        if chosen_angles
        else "Use a DIFFERENT distinct angle for each concept."
    )
    human = (
        f"Product / offer: {product}\n"
        f"Business id: {business_id}\n"
        f"Platform: {platform} — {brief}\n\n"
        f"Generate EXACTLY {count} distinct ad concepts for A/B testing. "
        f"{angle_line} Every hook must be unique and thumb-stopping.\n\n"
        "Reply with STRICT JSON of the form:\n"
        '{"concepts": [{"hook": "...", "angle": "...", "script": "...", '
        '"cta": "...", "visual_direction": "..."}]}\n'
        "- hook: the spoken/on-screen opening line (first 2 seconds).\n"
        "- angle: the creative angle/approach for this variant.\n"
        "- script: the full influencer-style spoken script/voiceover.\n"
        "- cta: the closing call to action.\n"
        "- visual_direction: shot list / b-roll / on-screen text guidance."
    )

    try:
        from agents.base_agent import BaseAgent
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = BaseAgent._build_dept_llm()
        response = await llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        text = _coerce_content(getattr(response, "content", response))
        concepts = _parse_concepts(_extract_json(text))
    except Exception:
        return {"platform": platform, "concepts": []}

    # Backfill angles for any concept the model left blank, keep at most `count`.
    for idx, c in enumerate(concepts):
        if not c.get("angle") and chosen_angles:
            c["angle"] = chosen_angles[idx % len(chosen_angles)]
    return {"platform": platform, "concepts": concepts[:count]}


async def generate_video(concept: dict, business_id=None) -> dict:
    """
    OPTIONAL real video generation for a single ad ``concept``.

    If the env var ``VIDEO_API_KEY`` is set we lazily POST the concept to a
    generic UGC-video provider (endpoint configurable via ``VIDEO_API_URL``,
    default assumes a provider that accepts {"prompt": ..., "script": ...} and
    returns a job/video payload). Otherwise — and on ANY error — we return the
    script only so callers never need the key and nothing ever raises.

    Assumption (documented): the provider is a generic REST endpoint that takes
    a Bearer token and a JSON body, and returns JSON. Adjust VIDEO_API_URL /
    payload to match your chosen vendor (e.g. a HeyGen/Runway-style API).
    """
    concept = concept if isinstance(concept, dict) else {}
    api_key = os.getenv("VIDEO_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "script_only",
            "note": "set VIDEO_API_KEY to render video",
            "concept": concept,
        }

    try:
        import httpx

        url = os.getenv("VIDEO_API_URL", "https://api.video-provider.example/v1/videos")
        prompt = concept.get("visual_direction") or concept.get("hook") or ""
        payload = {
            "prompt": prompt,
            "script": concept.get("script", ""),
            "hook": concept.get("hook", ""),
            "cta": concept.get("cta", ""),
            "business_id": str(business_id) if business_id is not None else None,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return {"status": "rendering", "provider_response": data, "concept": concept}
    except Exception as e:
        # Best-effort: fall back to script-only rather than surfacing an error.
        return {
            "status": "script_only",
            "note": f"video render unavailable: {type(e).__name__}",
            "concept": concept,
        }
