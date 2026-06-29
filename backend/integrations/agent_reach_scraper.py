"""
Agent-Reach Social Media Lead Scraper.
Uses CLI tools installed by Agent-Reach (twitter-cli, rdt-cli, opencli)
to find local service businesses from social platforms.

Architecture:
  Twitter  → twitter-cli (pipx install twitter-cli)
  Reddit   → rdt-cli     (pipx install git+https://github.com/public-clis/rdt-cli.git)
  Instagram→ opencli     (npm install -g @jackwener/opencli + Chrome extension)

These are subprocess calls — no API keys, no cost.
All parsing done locally.
"""
import asyncio
import json
import re
import shutil
import subprocess
from typing import Optional

from agent_reach.utils.process import utf8_subprocess_env

# ── NJ local service business queries ────────────────────────────────────────

TWITTER_QUERIES = [
    '"med spa" "New Jersey" -filter:retweets',
    '"medspa" "NJ" booking appointment',
    '"hair salon" "New Jersey" -filter:retweets',
    '"nail salon" "NJ" OR "New Jersey"',
    '"gym" "New Jersey" -filter:retweets',
    '"dental" "New Jersey" -filter:retweets',
    '"wellness" "New Jersey" -filter:retweets',
]

REDDIT_QUERIES = [
    "med spa New Jersey",
    "medspa NJ",
    "hair salon New Jersey",
    "gym New Jersey",
    "dental New Jersey",
]

REDDIT_SUBREDDITS = [
    "newjersey",
    "newjerseylocal",
    "njbusiness",
]

# Regex patterns to extract business info from social posts
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I)
URL_RE   = re.compile(r"https?://[^\s\"'<>]+", re.I)

BOOKING_SIGNALS = [
    "book now", "book online", "book appointment", "schedule",
    "mindbody", "vagaro", "fresha", "booksy", "calendly",
    "square appointments", "book a", "reserve",
]
NO_BOOKING_SIGNALS = [
    "call us to book", "call to schedule", "dm to book",
    "text to book", "walk-in", "walk in welcome",
    "no online booking", "call for appointment",
]

# ── Health check ──────────────────────────────────────────────────────────────

def check_agent_reach_tools() -> dict:
    """Check which Agent-Reach CLI tools are available."""
    tools = {
        "twitter_cli": bool(shutil.which("twitter")),
        "rdt_cli":     bool(shutil.which("rdt")),
        "opencli":     bool(shutil.which("opencli")),
        "agent_reach": bool(shutil.which("agent-reach")),
    }
    tools["any_available"] = any([tools["twitter_cli"], tools["rdt_cli"], tools["opencli"]])
    return tools


# ── Twitter scraping ──────────────────────────────────────────────────────────

async def search_twitter_leads(
    query: str,
    num_results: int = 20,
) -> list[dict]:
    """
    Search Twitter for local business leads using twitter-cli.
    Command: twitter search "QUERY" -n NUM --json
    Returns list of extracted lead dicts.
    """
    if not shutil.which("twitter"):
        return []

    try:
        proc = await asyncio.create_subprocess_exec(
            "twitter", "search", query, "-n", str(num_results), "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=utf8_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return []
        data = json.loads(raw)
        tweets = data if isinstance(data, list) else data.get("tweets", data.get("data", []))
        return [_parse_twitter_tweet(t, query) for t in tweets if _is_business_tweet(t)]
    except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
        return []


async def search_twitter_user(username: str) -> dict:
    """
    Get a Twitter business profile using twitter-cli.
    Command: twitter user @USERNAME --json
    """
    if not shutil.which("twitter"):
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "twitter", "user", f"@{username.lstrip('@')}", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=utf8_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        user = data.get("user", data) if isinstance(data, dict) else {}
        return _parse_twitter_user(user)
    except Exception:
        return {}


async def search_twitter_all_queries(industry: str = "medspa") -> list[dict]:
    """Run all Twitter queries for an industry and return deduplicated leads."""
    industry_map = {
        "medspa":  TWITTER_QUERIES[:3],
        "salon":   [TWITTER_QUERIES[2], TWITTER_QUERIES[3]],
        "gym":     [TWITTER_QUERIES[4]],
        "dental":  [TWITTER_QUERIES[5]],
        "wellness":[TWITTER_QUERIES[6]],
    }
    queries = industry_map.get(industry.lower(), TWITTER_QUERIES[:2])

    all_leads = []
    seen = set()

    for query in queries:
        leads = await search_twitter_leads(query, num_results=15)
        for lead in leads:
            key = lead.get("company_name", "") or lead.get("twitter_username", "")
            if key and key not in seen:
                seen.add(key)
                all_leads.append(lead)
        await asyncio.sleep(1.5)  # Rate limit: twitter-cli is sensitive

    return all_leads


# ── Reddit scraping ───────────────────────────────────────────────────────────

async def search_reddit_leads(
    query: str,
    limit: int = 20,
) -> list[dict]:
    """
    Search Reddit for local business mentions using rdt-cli.
    Command: rdt search "QUERY" --limit NUM --yaml
    """
    if not shutil.which("rdt"):
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "rdt", "search", query, "--limit", str(limit),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=utf8_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return []
        # rdt outputs YAML or JSON depending on version
        posts = _parse_rdt_output(raw)
        return [_parse_reddit_post(p, query) for p in posts if _is_business_post(p)]
    except Exception:
        return []


async def browse_reddit_subreddit(subreddit: str, limit: int = 20) -> list[dict]:
    """
    Browse a subreddit for business listings using rdt-cli.
    Command: rdt sub SUBREDDIT --limit NUM
    """
    if not shutil.which("rdt"):
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "rdt", "sub", subreddit, "--limit", str(limit),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=utf8_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return []
        posts = _parse_rdt_output(raw)
        return [_parse_reddit_post(p, f"r/{subreddit}") for p in posts if _is_business_post(p)]
    except Exception:
        return []


async def search_reddit_all_queries(industry: str = "medspa") -> list[dict]:
    """Run Reddit search + subreddit browse and return deduplicated leads."""
    industry_queries = {
        "medspa":  ["med spa New Jersey", "medspa NJ"],
        "salon":   ["hair salon New Jersey", "nail salon NJ"],
        "gym":     ["gym New Jersey", "fitness center NJ"],
        "dental":  ["dentist New Jersey", "dental NJ"],
        "wellness":["wellness center New Jersey", "massage NJ"],
    }
    queries = industry_queries.get(industry.lower(), [f"{industry} New Jersey"])

    all_leads = []
    seen = set()

    # Search
    for query in queries:
        leads = await search_reddit_leads(query, limit=15)
        for lead in leads:
            key = lead.get("reddit_post_url") or lead.get("company_name", "")
            if key and key not in seen:
                seen.add(key)
                all_leads.append(lead)
        await asyncio.sleep(1)

    # Browse NJ subreddits
    for sub in REDDIT_SUBREDDITS[:2]:
        leads = await browse_reddit_subreddit(sub, limit=20)
        for lead in leads:
            key = lead.get("reddit_post_url") or lead.get("company_name", "")
            if key and key not in seen:
                seen.add(key)
                all_leads.append(lead)
        await asyncio.sleep(1)

    return all_leads


# ── Instagram scraping ────────────────────────────────────────────────────────

async def search_instagram_leads(
    query: str,
    limit: int = 20,
) -> list[dict]:
    """
    Search Instagram for business profiles using opencli.
    Command: opencli instagram search "QUERY" -f yaml
    NOTE: Requires desktop Chrome + OpenCLI extension + logged in to Instagram.
    """
    if not shutil.which("opencli"):
        return []
    try:
        proc = await asyncio.create_subprocess_exec(
            "opencli", "instagram", "search", query, "-f", "yaml",
            "--limit", str(limit),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=utf8_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=45)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return []
        users = _parse_opencli_yaml(raw)
        leads = []
        for user in users:
            lead = _parse_instagram_user(user, query)
            if lead:
                leads.append(lead)
        return leads
    except Exception:
        return []


async def get_instagram_user_profile(username: str) -> dict:
    """
    Get an Instagram business profile using opencli.
    Command: opencli instagram profile USERNAME -f yaml
    """
    if not shutil.which("opencli"):
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "opencli", "instagram", "profile", username, "-f", "yaml",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=utf8_subprocess_env(),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return {}
        data = _parse_opencli_yaml(raw)
        profile = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
        return _parse_instagram_profile(profile, username)
    except Exception:
        return {}


# ── Parse helpers ─────────────────────────────────────────────────────────────

def _parse_twitter_tweet(tweet: dict, query: str) -> dict:
    """Extract lead fields from a twitter-cli tweet object."""
    text = tweet.get("text") or tweet.get("full_text") or ""
    user = tweet.get("user") or tweet.get("author") or {}
    username = user.get("screen_name") or user.get("username") or ""
    bio = user.get("description") or ""
    location = user.get("location") or ""
    website = user.get("url") or user.get("website") or ""
    followers = user.get("followers_count") or user.get("follower_count") or 0

    combined = f"{text} {bio} {location}"
    emails = EMAIL_RE.findall(combined)
    phones = PHONE_RE.findall(combined)
    urls = URL_RE.findall(combined)

    has_booking = any(s in combined.lower() for s in BOOKING_SIGNALS)
    no_booking  = any(s in combined.lower() for s in NO_BOOKING_SIGNALS)

    return {
        "source": "twitter",
        "company_name": user.get("name") or username,
        "twitter_username": username,
        "twitter_followers": followers,
        "twitter_bio": bio[:300],
        "twitter_location": location,
        "website": _clean_url(website or (urls[0] if urls else "")),
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "has_online_booking": has_booking,
        "no_booking_signal": no_booking,
        "score": 0,
        "tier": "C",
        "status": "new",
        "search_query": query,
    }


def _parse_twitter_user(user: dict) -> dict:
    """Parse a twitter-cli user profile object."""
    bio = user.get("description") or ""
    emails = EMAIL_RE.findall(bio)
    return {
        "twitter_username": user.get("screen_name") or user.get("username") or "",
        "twitter_followers": user.get("followers_count") or 0,
        "twitter_bio": bio[:300],
        "twitter_location": user.get("location") or "",
        "website": _clean_url(user.get("url") or user.get("website") or ""),
        "email": emails[0] if emails else None,
        "verified": user.get("verified", False),
    }


def _parse_reddit_post(post: dict, query: str) -> dict:
    """Extract lead fields from a rdt-cli post object."""
    title = post.get("title") or ""
    text  = post.get("selftext") or post.get("text") or post.get("body") or ""
    url   = post.get("url") or ""
    author= post.get("author") or ""

    combined = f"{title} {text}"
    emails = EMAIL_RE.findall(combined)
    phones = PHONE_RE.findall(combined)
    urls   = [u for u in URL_RE.findall(combined) if "reddit.com" not in u]

    has_booking = any(s in combined.lower() for s in BOOKING_SIGNALS)
    no_booking  = any(s in combined.lower() for s in NO_BOOKING_SIGNALS)

    # Try to extract business name from title
    name = _extract_business_name(title)

    return {
        "source": "reddit",
        "company_name": name or title[:60],
        "reddit_post_url": url,
        "reddit_author": author,
        "reddit_title": title[:200],
        "website": _clean_url(urls[0] if urls else ""),
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "has_online_booking": has_booking,
        "no_booking_signal": no_booking,
        "score": 0,
        "tier": "C",
        "status": "new",
        "search_query": query,
    }


def _parse_instagram_user(user: dict, query: str) -> Optional[dict]:
    """Parse opencli instagram search result user object."""
    username = user.get("username") or user.get("handle") or ""
    if not username:
        return None
    bio = user.get("bio") or user.get("biography") or ""
    fullname = user.get("full_name") or user.get("name") or username
    followers = user.get("followers") or user.get("follower_count") or 0
    website = user.get("website") or user.get("external_url") or ""
    emails = EMAIL_RE.findall(bio)

    has_booking = any(s in bio.lower() for s in BOOKING_SIGNALS)
    no_booking  = any(s in bio.lower() for s in NO_BOOKING_SIGNALS)

    return {
        "source": "instagram_opencli",
        "company_name": fullname,
        "instagram_username": username,
        "instagram_followers": followers,
        "instagram_bio": bio[:300],
        "website": _clean_url(website),
        "email": emails[0] if emails else None,
        "has_online_booking": has_booking,
        "no_booking_signal": no_booking,
        "score": 0,
        "tier": "C",
        "status": "new",
        "search_query": query,
    }


def _parse_instagram_profile(profile: dict, username: str) -> dict:
    """Parse opencli instagram profile result."""
    bio = profile.get("bio") or profile.get("biography") or ""
    emails = EMAIL_RE.findall(bio)
    return {
        "instagram_username": username,
        "instagram_followers": profile.get("followers") or 0,
        "instagram_following": profile.get("following") or 0,
        "instagram_posts": profile.get("posts") or profile.get("media_count") or 0,
        "instagram_bio": bio[:300],
        "instagram_verified": profile.get("verified") or False,
        "instagram_is_business": profile.get("is_business") or False,
        "instagram_category": profile.get("category") or "",
        "website": _clean_url(profile.get("website") or profile.get("external_url") or ""),
        "email": emails[0] if emails else None,
    }


def _parse_rdt_output(raw: str) -> list[dict]:
    """Parse rdt-cli output — handles JSON or YAML."""
    # Try JSON first
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return data.get("posts", data.get("data", data.get("results", [])))
    except json.JSONDecodeError:
        pass
    # Try YAML
    try:
        import yaml
        data = yaml.safe_load(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("posts", data.get("data", []))
    except Exception:
        pass
    return []


def _parse_opencli_yaml(raw: str) -> list:
    """Parse opencli -f yaml output."""
    try:
        import yaml
        data = yaml.safe_load(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("results", data.get("users", data.get("data", [data])))
    except Exception:
        pass
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    except Exception:
        pass
    return []


def _is_business_tweet(tweet: dict) -> bool:
    """Filter: only keep tweets that seem to be about actual businesses."""
    text = (tweet.get("text") or "").lower()
    user = tweet.get("user") or tweet.get("author") or {}
    bio  = (user.get("description") or "").lower()
    combined = f"{text} {bio}"
    # Must have at least one business signal
    business_signals = [
        "spa", "salon", "gym", "dental", "wellness", "fitness",
        "clinic", "studio", "medspa", "aesthetics", "beauty",
        "book now", "appointment", "visit us", "call us",
    ]
    return any(s in combined for s in business_signals)


def _is_business_post(post: dict) -> bool:
    """Filter: only keep Reddit posts about actual businesses."""
    title = (post.get("title") or "").lower()
    text  = (post.get("selftext") or post.get("text") or "").lower()
    combined = f"{title} {text}"
    business_signals = [
        "spa", "salon", "gym", "dental", "wellness",
        "clinic", "studio", "fitness", "beauty", "appointment",
        "book", "located", "opening", "now open",
    ]
    return any(s in combined for s in business_signals)


def _extract_business_name(title: str) -> str:
    """Try to extract a business name from a Reddit post title."""
    # Common patterns: "[Business Name] - NJ" or "Check out Business Name"
    patterns = [
        r"^([\w\s&'\.]+(?:spa|salon|gym|dental|clinic|studio|fitness|beauty|wellness)[\w\s&'\.]*)",
        r"\[([^\]]+)\]",
        r'"([^"]+)"',
    ]
    for pattern in patterns:
        m = re.search(pattern, title, re.I)
        if m:
            name = m.group(1).strip()
            if 3 < len(name) < 80:
                return name
    return ""


def _clean_url(url: str) -> str:
    """Clean and validate a URL."""
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = f"https://{url}"
    # Remove tracking params
    url = re.sub(r"\?.*", "", url)
    return url if len(url) > 10 else ""
