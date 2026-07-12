"""
AI Clone — Content Autopilot (feature #9).

Generates a full social-media content calendar in the brand's voice across
platforms, ready to schedule/post — so the owner never has to record/edit/post
by hand. Two best-effort, never-raising async entry points:

  generate_calendar(business_id, days, platforms, topics)
      -> pull the business profile (name, brand_voice, industry, services) from
         Supabase (best-effort), then use the shared dept LLM to produce a
         STRICT-JSON plan of posts across the given platforms, parsed defensively.
         Returns {"days": days, "posts": [...]}.

  schedule_calendar(business_id, posts)
      -> best-effort persist the generated posts into a `content_posts` table so
         the existing schedule_social_post n8n workflow / social APIs can pick
         them up and publish. Returns {"scheduled": n}.

NOTE: actual publishing is intentionally OUT OF SCOPE here — it is handled by the
existing `schedule_social_post` n8n workflow and the underlying social APIs. This
module only *plans* and *stages* the calendar.
"""
from __future__ import annotations

DEFAULT_PLATFORMS = ["instagram", "tiktok", "linkedin"]


def _load_business(business_id: str) -> dict:
    """Best-effort fetch of the business row + config. Never raises."""
    try:
        from backend.memory.supabase_client import get_supabase
        result = get_supabase().table("businesses") \
            .select("name,industry,config") \
            .eq("id", str(business_id)).limit(1).execute()
        rows = result.data or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def _build_prompt(biz: dict, days: int, platforms: list, topics: list | None) -> str:
    """Compose a brand-voice prompt asking for a STRICT-JSON content calendar."""
    cfg = (biz.get("config") or {}) if isinstance(biz, dict) else {}
    name = biz.get("name") or cfg.get("name") or "Your Business"
    industry = biz.get("industry") or cfg.get("industry") or "service"
    brand_voice = cfg.get("brand_voice") or "friendly, professional"
    services = cfg.get("services") or []
    try:
        svc_str = ", ".join(
            str(s.get("name")) for s in services[:12] if isinstance(s, dict) and s.get("name")
        ) or "not specified"
    except Exception:
        svc_str = "not specified"
    topic_str = ", ".join(str(t) for t in (topics or [])) or "owner's discretion (evergreen + promotional mix)"
    plat_str = ", ".join(str(p) for p in platforms)

    return (
        f"You are the social-media content director for {name}, a {industry} business.\n"
        f"Brand voice: {brand_voice}\n"
        f"Services: {svc_str}\n"
        f"Topics to cover: {topic_str}\n\n"
        f"Produce a {days}-day social-media content calendar across these platforms: {plat_str}.\n"
        f"Write every hook, caption and CTA in the brand voice above.\n\n"
        "Respond with STRICT JSON only (no markdown, no prose) in exactly this shape:\n"
        '{"posts": [{"day": 1, "platform": "instagram", "format": "reel", '
        '"hook": "...", "caption": "...", "hashtags": ["#..."], "cta": "..."}]}\n'
        f"Include a good spread of posts covering days 1..{days} and rotating across the platforms."
    )


def _coerce_posts(raw) -> list:
    """Normalize the parsed LLM output into a clean list of post dicts."""
    posts = []
    items = raw.get("posts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return posts
    for it in items:
        if not isinstance(it, dict):
            continue
        hashtags = it.get("hashtags")
        if isinstance(hashtags, str):
            hashtags = [h.strip() for h in hashtags.replace(",", " ").split() if h.strip()]
        elif isinstance(hashtags, list):
            hashtags = [str(h) for h in hashtags]
        else:
            hashtags = []
        try:
            day = int(it.get("day") or 1)
        except Exception:
            day = 1
        posts.append({
            "day": day,
            "platform": str(it.get("platform") or "instagram"),
            "format": str(it.get("format") or "post"),
            "hook": str(it.get("hook") or ""),
            "caption": str(it.get("caption") or ""),
            "hashtags": hashtags,
            "cta": str(it.get("cta") or ""),
        })
    return posts


def _parse_calendar(content) -> list:
    """Defensively parse the LLM response into a list of posts."""
    import re
    import json
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or block.get("content", ""))
            else:
                parts.append(str(block))
        content = "".join(parts)
    elif not isinstance(content, str):
        content = str(content)
    # Strip markdown fences if present.
    m = re.search(r"```[\w]*\s*([\s\S]*?)```", content)
    clean = m.group(1).strip() if m else content.strip()
    try:
        return _coerce_posts(json.loads(clean))
    except Exception:
        pass
    # Last-resort: try to locate the first JSON object in the text.
    try:
        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1 and end > start:
            return _coerce_posts(json.loads(clean[start:end + 1]))
    except Exception:
        pass
    return []


async def generate_calendar(business_id, days: int = 7, platforms=None, topics=None) -> dict:
    """
    Generate a social-media content calendar in the brand's voice.

    Returns {"days": days, "posts": [{day, platform, format, hook, caption,
    hashtags, cta}, ...]}. On any error returns {"days": days, "posts": []}.
    """
    try:
        days = int(days) if days else 7
    except Exception:
        days = 7
    platforms = platforms or DEFAULT_PLATFORMS
    if not isinstance(platforms, list) or not platforms:
        platforms = DEFAULT_PLATFORMS

    try:
        from agents.base_agent import BaseAgent
        from langchain_core.messages import HumanMessage, SystemMessage

        biz = _load_business(business_id)
        prompt = _build_prompt(biz, days, platforms, topics)
        llm = BaseAgent._build_dept_llm()
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Generate the {days}-day calendar now as STRICT JSON."),
        ]
        response = await llm.ainvoke(messages)
        content = getattr(response, "content", response)
        posts = _parse_calendar(content)
        return {"days": days, "posts": posts}
    except Exception:
        return {"days": days, "posts": []}


async def schedule_calendar(business_id, posts) -> dict:
    """
    Best-effort stage the generated posts into the `content_posts` Supabase table
    so the existing schedule_social_post workflow / social APIs can publish them.

    Never raises. Returns {"scheduled": n} where n is the number of rows staged.
    Actual publishing is out of scope (handled by schedule_social_post n8n).
    """
    if not isinstance(posts, list) or not posts:
        return {"scheduled": 0}

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    scheduled = 0
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        table = sb.table("content_posts")
        for post in posts:
            if not isinstance(post, dict):
                continue
            try:
                day = int(post.get("day") or 1)
            except Exception:
                day = 1
            scheduled_for = (now + timedelta(days=max(0, day - 1))).isoformat()
            try:
                table.insert({
                    "business_id": str(business_id),
                    "platform": str(post.get("platform") or "instagram"),
                    "scheduled_for": scheduled_for,
                    "caption": str(post.get("caption") or ""),
                    "status": "scheduled",
                    "created_at": now.isoformat(),
                }).execute()
                scheduled += 1
            except Exception:
                # Skip a bad row; keep staging the rest (best-effort).
                continue
    except Exception:
        return {"scheduled": scheduled}
    return {"scheduled": scheduled}
