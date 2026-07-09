#!/usr/bin/env python3
"""
Automiqo OS — Live HTTP smoke test
==================================

This is a STANDALONE, human-run smoke test for the Automiqo OS FastAPI backend.
It is NOT a pytest unit test:

  * The filename is ``smoke_test.py`` (not ``test_smoke.py``) so pytest's default
    ``test_*.py`` collection ignores it.
  * All logic runs under ``if __name__ == "__main__":`` — importing this module
    does nothing, so it never interferes with the offline ``pytest`` suite.

It makes REAL HTTP calls against a RUNNING backend that has REAL API keys/secrets
configured (Supabase, LLM provider, Slack, Telnyx, VAPI, etc.). Endpoints that
talk to the model or the database will actually execute, so run it against a
dev/staging deployment — not production — unless you know what you're doing.

Dependencies: only ``httpx`` and the Python standard library.

Usage
-----
    python tests/smoke_test.py \\
        --base-url http://localhost:8000 \\
        --business-id <uuid> \\
        [--token <bearer-token>] \\
        [--slack-signing-secret <secret>]

Defaults:
  * --base-url            env BASE_URL,           else http://localhost:8000
  * --business-id         env SMOKE_BUSINESS_ID,  else env NEXT_PUBLIC_BUSINESS_ID
  * --token               env AUTH / AUTH_TOKEN   (optional bearer token)
  * --slack-signing-secret env SLACK_SIGNING_SECRET (optional; enables check 12)

If a token is provided, every request is sent with an
``Authorization: Bearer <token>`` header.

Exit code: 1 if any CRITICAL check fails (health, chat stream, Slack handshake),
otherwise 0. Every check is wrapped in try/except so the script always finishes
and prints the final summary.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time

try:
    import httpx
except ImportError:  # pragma: no cover - only hit when run without httpx
    print("ERROR: this smoke test requires the 'httpx' package. Install it with:\n"
          "    pip install httpx", file=sys.stderr)
    sys.exit(2)


# ── timeouts ────────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 10.0   # seconds for normal endpoints
CHAT_TIMEOUT = 60.0      # seconds for the streaming /chat endpoint


# ── result tracking ──────────────────────────────────────────────────────────
class Results:
    """Collects check outcomes and prints a PASS/FAIL table."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"

    def __init__(self):
        self.rows = []            # (status, name, detail)
        self.critical_failed = False

    def record(self, status, name, detail="", critical=False):
        self.rows.append((status, name, detail))
        tag = {self.PASS: "[PASS]", self.FAIL: "[FAIL]", self.SKIP: "[SKIP]"}[status]
        crit = " (CRITICAL)" if critical else ""
        line = f"{tag} {name}{crit}"
        if detail:
            line += f" — {detail}"
        print(line, flush=True)
        if status == self.FAIL and critical:
            self.critical_failed = True

    def ok(self, name, detail="", critical=False):
        self.record(self.PASS, name, detail, critical)

    def fail(self, name, detail="", critical=False):
        self.record(self.FAIL, name, detail, critical)

    def skip(self, name, detail="", critical=False):
        self.record(self.SKIP, name, detail, critical)

    def summary(self):
        total = len(self.rows)
        passed = sum(1 for s, _, _ in self.rows if s == self.PASS)
        failed = sum(1 for s, _, _ in self.rows if s == self.FAIL)
        skipped = sum(1 for s, _, _ in self.rows if s == self.SKIP)
        print("\n" + "=" * 60)
        print(f"SUMMARY: {passed}/{total} passed  "
              f"({failed} failed, {skipped} skipped)")
        if self.critical_failed:
            print("RESULT: FAILED — at least one CRITICAL check did not pass.")
        else:
            print("RESULT: OK — no critical failures.")
        print("=" * 60)
        return 1 if self.critical_failed else 0


# ── helpers ───────────────────────────────────────────────────────────────────
def _short(text, n=160):
    s = str(text).replace("\n", " ").strip()
    return s if len(s) <= n else s[:n] + "…"


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return None


# ── checks ─────────────────────────────────────────────────────────────────────
def check_health(client, base_url, res):
    name = "1. GET /health"
    try:
        r = client.get(f"{base_url}/health", timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and data.get("status") == "ok":
            res.ok(name, f"status=ok service={data.get('service', '?')}", critical=True)
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}", critical=True)
    except Exception as e:
        res.fail(name, f"exception: {e}", critical=True)


def check_modules_registry(client, base_url, res):
    name = "2. GET /modules/registry"
    try:
        r = client.get(f"{base_url}/modules/registry", timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and isinstance(data.get("departments"), list):
            res.ok(name, f"{len(data['departments'])} departments")
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name, f"exception: {e}")


def check_modules_business(client, base_url, business_id, res):
    name = "3. GET /modules/{business_id}"
    try:
        r = client.get(f"{base_url}/modules/{business_id}", timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and "departments" in data:
            res.ok(name, "has departments")
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name, f"exception: {e}")


def check_chat_stream(client, base_url, business_id, res):
    name = "4. POST /chat (SSE stream)"
    body = {"business_id": business_id, "message": "Give me a one-line status."}
    try:
        chunks = []
        with client.stream("POST", f"{base_url}/chat", json=body, timeout=CHAT_TIMEOUT) as r:
            if r.status_code != 200:
                # Drain so the connection closes cleanly, then report.
                try:
                    detail = _short(r.read())
                except Exception:
                    detail = ""
                res.fail(name, f"HTTP {r.status_code} {detail}", critical=True)
                return
            for line in r.iter_lines():
                if not line:
                    continue
                # httpx yields str lines; be defensive about bytes too.
                if isinstance(line, bytes):
                    line = line.decode("utf-8", "replace")
                if line.startswith("data: "):
                    chunks.append(line[len("data: "):])
                if len(chunks) >= 5:
                    break
        if chunks:
            res.ok(name, f"received {len(chunks)} SSE data chunk(s)", critical=True)
        else:
            res.fail(name, "200 but no SSE data received", critical=True)
    except Exception as e:
        res.fail(name, f"exception: {e}", critical=True)


def get_team_members(client, base_url, business_id, res):
    """Check 5: fetch roster, return list of member keys (or [])."""
    name = "5. GET /team/{business_id}/members"
    try:
        r = client.get(f"{base_url}/team/{business_id}/members", timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        members = data.get("members") if isinstance(data, dict) else None
        if r.status_code == 200 and isinstance(members, list) and members:
            keys = [m.get("key") for m in members if isinstance(m, dict) and m.get("key")]
            res.ok(name, f"{len(keys)} members")
            return members
        res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
        return []
    except Exception as e:
        res.fail(name, f"exception: {e}")
        return []


def _select_members(members):
    """
    Pick which members to DM. If <=12, use all. Otherwise pick a representative
    subset: the CEO + one department head per department + up to 3 managers.
    """
    keys = [m.get("key") for m in members if isinstance(m, dict) and m.get("key")]
    if len(keys) <= 12:
        return keys

    selected = []
    # CEO first.
    for m in members:
        if m.get("key") == "ceo":
            selected.append("ceo")
            break
    # One department head per department (role == "department").
    seen_depts = set()
    for m in members:
        if m.get("role") == "department":
            dept = m.get("dept")
            if dept not in seen_depts:
                seen_depts.add(dept)
                if m.get("key") not in selected:
                    selected.append(m["key"])
    # Up to 3 managers.
    managers = [m["key"] for m in members
                if m.get("role") == "manager" and m.get("key") not in selected]
    selected.extend(managers[:3])
    return selected


def check_dm_each_member(client, base_url, business_id, members, res):
    name_group = "6. Per-manager DM /team/{business_id}/ask"
    if not members:
        res.skip(name_group, "no members from step 5")
        return
    keys = _select_members(members)
    if not keys:
        res.skip(name_group, "no member keys to DM")
        return

    print(f"\n-- Talking to {len(keys)} team member(s) --", flush=True)
    responded = 0
    for key in keys:
        line_name = f"   6.x DM {key}"
        body = {"agent_key": key,
                "message": "In one sentence, what are you focused on today?"}
        try:
            r = client.post(f"{base_url}/team/{business_id}/ask", json=body,
                            timeout=CHAT_TIMEOUT)
            data = _safe_json(r) or {}
            reply = (data.get("reply") or "").strip() if isinstance(data, dict) else ""
            if r.status_code == 200 and reply:
                responded += 1
                res.ok(line_name, _short(reply, 80))
            else:
                res.fail(line_name, f"HTTP {r.status_code} reply={_short(reply, 80)}")
        except Exception as e:
            res.fail(line_name, f"exception: {e}")

    summary = f"{responded}/{len(keys)} members responded"
    if responded == len(keys):
        res.ok(name_group, summary)
    elif responded > 0:
        res.fail(name_group, summary)
    else:
        res.fail(name_group, summary)


def check_team_chat_get(client, base_url, business_id, res):
    name = "7. GET /team-chat/{business_id}"
    try:
        r = client.get(f"{base_url}/team-chat/{business_id}", timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and "messages" in data:
            res.ok(name, f"{len(data.get('messages') or [])} messages")
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name, f"exception: {e}")


def check_team_chat_post(client, base_url, business_id, res):
    name = "8. POST /team-chat/{business_id}"
    try:
        r = client.post(f"{base_url}/team-chat/{business_id}",
                        json={"message": "Team, status check please."},
                        timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            res.ok(name, _short(r.text, 80))
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name, f"exception: {e}")


def check_backstage(client, base_url, business_id, res):
    name = "9. GET /backstage/{business_id}"
    try:
        r = client.get(f"{base_url}/backstage/{business_id}", timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and "activity" in data:
            res.ok(name, f"{len(data.get('activity') or [])} activity items")
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name, f"exception: {e}")


def check_approvals_and_reports(client, base_url, business_id, res):
    name_a = "10a. GET /approvals/{business_id}"
    try:
        r = client.get(f"{base_url}/approvals/{business_id}", timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            res.ok(name_a, _short(r.text, 80))
        else:
            res.fail(name_a, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name_a, f"exception: {e}")

    name_r = "10b. GET /reports/{business_id}"
    try:
        r = client.get(f"{base_url}/reports/{business_id}", timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200:
            res.ok(name_r, _short(r.text, 80))
        else:
            res.fail(name_r, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name_r, f"exception: {e}")


def check_slack_handshake(client, base_url, res):
    name = "11. POST /webhooks/slack/events (url_verification)"
    body = {"type": "url_verification", "challenge": "smoke123"}
    try:
        r = client.post(f"{base_url}/webhooks/slack/events", json=body,
                        timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and data.get("challenge") == "smoke123":
            res.ok(name, "challenge echoed", critical=True)
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}", critical=True)
    except Exception as e:
        res.fail(name, f"exception: {e}", critical=True)


def check_slack_routing(client, base_url, signing_secret, res):
    name = "12. POST /webhooks/slack/events (signed event_callback)"
    if not signing_secret:
        res.skip(name, "no --slack-signing-secret provided")
        return
    try:
        payload = {
            "type": "event_callback",
            "team_id": "T1",
            "event": {
                "type": "app_mention",
                "text": "@cfo what is our revenue?",
                "channel": "C1",
                "ts": "1.1",
            },
        }
        body = json.dumps(payload)
        ts = str(int(time.time()))
        base_string = f"v0:{ts}:{body}"
        sig = "v0=" + hmac.new(
            signing_secret.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Slack-Signature": sig,
            "X-Slack-Request-Timestamp": ts,
        }
        r = client.post(f"{base_url}/webhooks/slack/events", content=body,
                        headers=headers, timeout=DEFAULT_TIMEOUT)
        data = _safe_json(r) or {}
        if r.status_code == 200 and data.get("ok") is True:
            res.ok(name, "ok=true")
        else:
            res.fail(name, f"HTTP {r.status_code} body={_short(r.text)}")
    except Exception as e:
        res.fail(name, f"exception: {e}")


def check_webhook_reachable(client, base_url, path, body, res, label):
    """Endpoint exists & doesn't 500: accept 200/400/401/422, fail on 404/5xx."""
    name = f"13. POST {path} (reachable)"
    try:
        r = client.post(f"{base_url}{path}", json=body, timeout=DEFAULT_TIMEOUT)
        if r.status_code in (200, 400, 401, 422):
            res.ok(name, f"HTTP {r.status_code} ({label})")
        elif r.status_code == 404:
            res.fail(name, f"HTTP 404 — endpoint missing ({label})")
        elif r.status_code >= 500:
            res.fail(name, f"HTTP {r.status_code} — server error ({label})")
        else:
            # Any other status still means the route exists and didn't 500.
            res.ok(name, f"HTTP {r.status_code} ({label})")
    except Exception as e:
        res.fail(name, f"exception: {e}")


# ── main ────────────────────────────────────────────────────────────────────────
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="smoke_test.py",
        description="Live HTTP smoke test for the Automiqo OS FastAPI backend. "
                    "Requires a running backend with real API keys.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("BASE_URL", "http://localhost:8000"),
        help="Base URL of the running backend (env BASE_URL, default http://localhost:8000)",
    )
    parser.add_argument(
        "--business-id",
        default=os.getenv("SMOKE_BUSINESS_ID") or os.getenv("NEXT_PUBLIC_BUSINESS_ID"),
        help="Business UUID (env SMOKE_BUSINESS_ID or NEXT_PUBLIC_BUSINESS_ID)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("AUTH") or os.getenv("AUTH_TOKEN"),
        help="Optional bearer token (env AUTH or AUTH_TOKEN). Sent as Authorization header.",
    )
    parser.add_argument(
        "--slack-signing-secret",
        default=os.getenv("SLACK_SIGNING_SECRET"),
        help="Optional Slack signing secret (env SLACK_SIGNING_SECRET). Enables check 12.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    base_url = args.base_url.rstrip("/")

    if not args.business_id:
        print("ERROR: no business id. Pass --business-id or set SMOKE_BUSINESS_ID "
              "/ NEXT_PUBLIC_BUSINESS_ID.", file=sys.stderr)
        return 2

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    print("=" * 60)
    print("Automiqo OS — live smoke test")
    print(f"  base-url    : {base_url}")
    print(f"  business-id : {args.business_id}")
    print(f"  auth        : {'bearer token' if args.token else 'none'}")
    print(f"  slack sig   : {'provided' if args.slack_signing_secret else 'not provided'}")
    print("=" * 60)

    res = Results()

    with httpx.Client(headers=headers, follow_redirects=True) as client:
        check_health(client, base_url, res)
        check_modules_registry(client, base_url, res)
        check_modules_business(client, base_url, args.business_id, res)
        check_chat_stream(client, base_url, args.business_id, res)
        members = get_team_members(client, base_url, args.business_id, res)
        check_dm_each_member(client, base_url, args.business_id, members, res)
        check_team_chat_get(client, base_url, args.business_id, res)
        check_team_chat_post(client, base_url, args.business_id, res)
        check_backstage(client, base_url, args.business_id, res)
        check_approvals_and_reports(client, base_url, args.business_id, res)
        check_slack_handshake(client, base_url, res)
        check_slack_routing(client, base_url, args.slack_signing_secret, res)

        # 13. Webhook reachability (exists & doesn't 500).
        check_webhook_reachable(
            client, base_url, "/webhooks/sms/inbound",
            {"data": {"payload": {"from": {"phone_number": "+15550001111"},
                                  "to": [{"phone_number": "+15550002222"}],
                                  "text": "smoke test"}}},
            res, "Telnyx SMS")
        check_webhook_reachable(
            client, base_url, "/webhooks/vapi/call",
            {"message": {"type": "status-update",
                         "call": {"id": "smoke", "customer": {"number": "+15550001111"}}}},
            res, "VAPI call")
        check_webhook_reachable(
            client, base_url, "/webhooks/appointment",
            {"triggerEvent": "PING", "payload": {}},
            res, "appointment")

    return res.summary()


if __name__ == "__main__":
    sys.exit(main())
