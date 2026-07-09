"""
Slack integration — DM or @-mention any AI team member from Slack.

The business owner can talk to the CEO, any of the 7 department heads, or any
of the 32 managers straight from Slack. A message routes to the right member
(via an explicit @name / name: prefix, a per-channel map, or the CEO by
default), the matching PersonaChatAgent answers *in character*, and the reply
is posted back into the same Slack channel/thread.

Design notes (matches the rest of the codebase):
- Included WITHOUT auth, like the other webhook routers — Slack authenticates
  itself with a signed request (SLACK_SIGNING_SECRET).
- Heavy deps (httpx) are imported lazily so the module is import-safe.
- Every step is wrapped defensively; the endpoint always acks HTTP 200 fast
  (Slack requires a response within 3s) and never raises.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.engines.business_blueprint import HEAD_NAMES, member_display, team_roster

router = APIRouter()


# ── helpers ────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Normalize a name/key for case-insensitive matching."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _strip_bot_mention(text: str) -> str:
    """Remove a leading Slack bot mention like '<@U0123ABC> '."""
    return re.sub(r"^\s*<@[UW][A-Z0-9]+>\s*", "", text or "").strip()


def _verify_signature(request: Request, raw: bytes) -> bool:
    """
    Verify Slack's request signature (v0 HMAC-SHA256).

    If SLACK_SIGNING_SECRET is unset we SKIP verification (dev mode) but warn.
    Rejects requests whose timestamp is older than 5 minutes (replay guard).
    """
    secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not secret:
        print("⚠️  [slack] SLACK_SIGNING_SECRET unset — skipping signature verification (dev mode).")
        return True

    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    sig = request.headers.get("X-Slack-Signature", "")
    if not ts or not sig:
        return False
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    try:
        basestring = f"v0:{ts}:{raw.decode('utf-8')}"
        computed = "v0=" + hmac.new(
            secret.encode(), basestring.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, sig)
    except Exception:
        return False


def _build_name_lookup(config: dict | None) -> dict:
    """Map normalized member names / keys / head names -> agent_key."""
    lookup: dict[str, str] = {}
    try:
        roster = team_roster(config)
        for m in roster.get("members", []):
            key = m.get("key")
            name = m.get("name")
            if not key:
                continue
            if name:
                lookup.setdefault(_norm(name), key)
            lookup.setdefault(_norm(key), key)
            # short manager key ("inventory" -> "coo.inventory")
            if "." in key:
                lookup.setdefault(_norm(key.split(".", 1)[1]), key)
    except Exception:
        pass
    # department head names + dept keys
    for dept, nm in HEAD_NAMES.items():
        lookup.setdefault(_norm(nm), dept)
        lookup.setdefault(_norm(dept), dept)
    return lookup


def _match_prefix(after: str, lookup: dict) -> tuple[str | None, str]:
    """Match the longest known alias at the start of `after`; return (key, rest)."""
    low = after.lower()
    for alias in sorted(lookup, key=len, reverse=True):
        if not alias:
            continue
        if low.startswith(alias) and (
            len(after) == len(alias) or not after[len(alias)].isalnum()
        ):
            rest = after[len(alias):].lstrip(" :,-")
            return lookup[alias], rest.strip()
    return None, after.strip()


def resolve_agent_key(text: str, config: dict | None, channel: str | None = None) -> tuple[str, str]:
    """
    Decide which team member should answer, and return (agent_key, clean_text).

    Resolution order:
      a) explicit prefix — "@Name ..." or "Name: ..." matching a roster
         member name / key / department head name (case-insensitive).
      b) per-channel map — config["slack_agent_map"][channel_id] -> agent_key.
      c) default — "ceo".
    """
    config = config or {}
    stripped = (text or "").strip()
    lookup = _build_name_lookup(config)

    # a-1) "Name: rest" form
    if ":" in stripped:
        cand, rest = stripped.split(":", 1)
        key = lookup.get(_norm(cand.lstrip("@")))
        if key:
            return key, rest.strip()

    # a-2) "@Name rest" form
    if stripped.startswith("@"):
        key, rest = _match_prefix(stripped[1:], lookup)
        if key:
            return key, rest

    # b) per-channel mapping
    if channel:
        cmap = config.get("slack_agent_map") or {}
        if channel in cmap:
            return cmap[channel], stripped

    # c) default to the CEO
    return "ceo", stripped


def resolve_business_for_slack(team_id: str, channel: str) -> tuple[str | None, dict]:
    """
    Find which business owns this Slack workspace/channel.

    Tries (in order): a business whose config.slack_team_id matches the Slack
    team, then one whose slack_agent_map contains this channel, then falls back
    to the first business (single-tenant default; see webhooks.py).
    """
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        rows = sb.table("businesses").select("id, config").execute().data or []

        if team_id:
            for r in rows:
                cfg = r.get("config") or {}
                if cfg.get("slack_team_id") == team_id:
                    return str(r["id"]), cfg
        if channel:
            for r in rows:
                cfg = r.get("config") or {}
                if channel in (cfg.get("slack_agent_map") or {}):
                    return str(r["id"]), cfg
        if rows:
            r = rows[0]  # TODO: match by team/channel when multi-tenant
            return str(r["id"]), (r.get("config") or {})
    except Exception:
        pass
    return None, {}


async def post_to_slack(channel: str, text: str, thread_ts: str | None = None) -> bool:
    """
    Post a message to Slack via chat.postMessage. Graceful no-op if the bot
    token is unset. Never raises.
    """
    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        print("⚠️  [slack] SLACK_BOT_TOKEN unset — skipping chat.postMessage.")
        return False
    try:
        import httpx  # lazy import — keep module import-safe

        payload: dict = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
            )
        try:
            data = resp.json()
        except Exception:
            return False
        if not data.get("ok"):
            print(f"⚠️  [slack] chat.postMessage failed: {data.get('error')}")
        return bool(data.get("ok"))
    except Exception as e:
        print(f"⚠️  [slack] post_to_slack error: {e}")
        return False


async def _handle_event(body: dict, event: dict) -> str | None:
    """Route a Slack message to a team member and post the reply back. Never raises."""
    text = event.get("text", "") or ""
    channel = event.get("channel", "") or ""
    thread_ts = event.get("thread_ts") or event.get("ts")
    team_id = body.get("team_id", "") or event.get("team", "") or ""

    clean = _strip_bot_mention(text)

    business_id, config = resolve_business_for_slack(team_id, channel)
    if not business_id:
        return None

    agent_key, clean_text = resolve_agent_key(clean, config, channel)
    if not clean_text:
        clean_text = clean or "Hi"

    # Spend circuit-breaker — degrade gracefully if the daily cap is hit.
    try:
        from backend.security.spend_guard import within_budget
        allowed, spent, cap = await within_budget(business_id)
    except Exception:
        allowed = True
    if not allowed:
        msg = ("I've hit today's AI budget, so I can't reply right now. "
               "It resets tomorrow, or you can raise the daily cap.")
        await post_to_slack(channel, msg, thread_ts)
        return msg

    # Route to the in-character agent.
    try:
        from agents.persona_chat import PersonaChatAgent
        agent = PersonaChatAgent(UUID(business_id), agent_key)
        reply = (await agent.run(clean_text)).summary
    except Exception as e:
        print(f"⚠️  [slack] agent run failed for {agent_key}: {e}")
        reply = ("Sorry — I couldn't put a reply together just now. "
                 "Please try again in a moment.")

    # Mirror the exchange into team chat (best-effort).
    try:
        from backend.events.agent_chat import post_team_message
        await post_team_message(
            business_id, "owner", clean_text,
            to_agent=member_display(agent_key), channel="slack",
        )
        await post_team_message(
            business_id, agent_key, reply,
            to_agent="owner", channel="slack",
        )
    except Exception:
        pass

    await post_to_slack(channel, reply, thread_ts)
    return reply


# ── endpoint ─────────────────────────────────────────────────────────────
@router.post("/webhooks/slack/events")
async def slack_events(request: Request):
    """
    Slack Events API endpoint. Handles the setup handshake, verifies the
    request signature, ignores bot/retry traffic, routes the message to a
    team member, and always acks HTTP 200 quickly.
    """
    raw = await request.body()
    try:
        import json
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        body = {}

    # 1. URL verification handshake (Slack app setup).
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # 2. Verify Slack signature (skipped in dev if no signing secret).
    if not _verify_signature(request, raw):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)

    # 3a. Ignore Slack retries — ack fast to avoid duplicate handling.
    if request.headers.get("X-Slack-Retry-Num"):
        return {"ok": True}

    event = body.get("event", {}) or {}

    # 3b. Ignore bot messages (prevents reply loops).
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return {"ok": True}

    # 4. Handle real user messages / mentions.
    if body.get("type") == "event_callback" and event.get("type") in ("app_mention", "message"):
        reply = None
        try:
            reply = await _handle_event(body, event)
        except Exception as e:
            print(f"⚠️  [slack] event handling error: {e}")
        # If no bot token is configured, surface the reply for local testing.
        if not os.getenv("SLACK_BOT_TOKEN") and reply is not None:
            return {"ok": True, "reply": reply}
        return {"ok": True}

    return {"ok": True}
