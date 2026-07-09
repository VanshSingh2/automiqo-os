#!/usr/bin/env python3
"""
Live n8n workflow tester — fires a synthetic request at EVERY webhook workflow
and reports pass/fail, so you can validate the whole n8n layer in one command.

It is SAFE BY DEFAULT: any workflow that would text/call/email a real person
(Twilio / VAPI / Telnyx / Resend, or a send_*/recover_*/nurture_* style name) is
SKIPPED unless you pass --include-comms (use test phone numbers if you do).
Cron/Slack workflows (no webhook trigger) are skipped too.

Zero dependencies — pure stdlib. Run it against a LIVE n8n (with the backend +
Supabase reachable, since many workflows call back into them).

USAGE
    python scripts/test_n8n_workflows.py \
        --base-url http://localhost:5678/webhook \
        --business-id <uuid>

    # also fire SMS/voice/email workflows (they will send real messages!):
    python scripts/test_n8n_workflows.py --include-comms --business-id <uuid>

    # just show what WOULD run, fire nothing:
    python scripts/test_n8n_workflows.py --list

    # test a single workflow:
    python scripts/test_n8n_workflows.py --only generate_daily_report --business-id <uuid>

DEFAULTS
    --base-url  : $N8N_WEBHOOK_BASE_URL or http://localhost:5678/webhook
    --business-id: $SMOKE_BUSINESS_ID or $NEXT_PUBLIC_BUSINESS_ID
Exit code is non-zero if any fired workflow failed.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
N8N_DIR = REPO / "n8n"

# Nodes / payload markers that mean "this contacts a real customer".
_COMMS_NODE_HINTS = ("twilio", "vapi", "telnyx")
_COMMS_BLOB_HINTS = ("api.twilio.com", "resend.com", "messages.json", "whatsapp")
# Name patterns that indicate outbound messaging (belt-and-suspenders).
_COMMS_NAME_RE = re.compile(
    r"^(send_|recover_|reactivate_|win_back|nurture_|make_outbound|request_google_review)"
    r"|campaign|outreach|reminder|survey|renewal|upsell|loyalty|referral|payment_link",
    re.IGNORECASE,
)



# A superset of dummy parameters so each workflow's validation node passes.
# Uses obviously-fake test values; real actions should be no-ops or safely logged.
def _dummy_params():
    return {
        "_test": True,
        "customer_id": "00000000-0000-0000-0000-0000000000c1",
        "lead_id": "00000000-0000-0000-0000-0000000000e1",
        "appointment_id": "00000000-0000-0000-0000-0000000000a1",
        "staff_id": "00000000-0000-0000-0000-0000000000f1",
        "call_id": "test-call-1",
        "campaign_id": "test-campaign-1",
        "phone": "+15555550100",
        "email": "test@example.com",
        "name": "Test User",
        "service": "Test Service",
        "amount": 1.0,
        "revenue": 1.0,
        "rating": 5,
        "transcript": "This is a synthetic test transcript.",
        "message": "synthetic test message",
        "query": "test", "location": "Test City", "count": 1,
        "version": "test", "workflow": "test", "role": "provider",
        "reason": "n8n_live_test",
    }


def categorize(path: Path):
    """Return (category, reason). category in {no-webhook, comms, testable}."""
    name = path.stem
    try:
        wf = json.loads(path.read_text())
    except Exception as e:
        return "invalid", f"bad JSON: {e}"
    nodes = wf.get("nodes", [])
    has_webhook = any(
        "webhook" in n.get("type", "").lower()
        and "respondtowebhook" not in n.get("type", "").lower()
        and (n.get("parameters", {}) or {}).get("path")
        for n in nodes
    )
    if not has_webhook:
        return "no-webhook", "cron/slack or no webhook trigger"
    blob = json.dumps(wf).lower()
    node_types = " ".join(n.get("type", "").lower() for n in nodes)
    if (any(h in node_types for h in _COMMS_NODE_HINTS)
            or any(h in blob for h in _COMMS_BLOB_HINTS)
            or _COMMS_NAME_RE.search(name)):
        return "comms", "sends SMS/voice/email to a real person"
    return "testable", ""


def build_payload(name, business_id):
    return {
        "business_id": business_id,
        "task_id": f"test-{name}-{int(time.time())}",
        "test": True,
        "parameters": _dummy_params(),
    }



def fire(base_url, name, business_id, timeout):
    """POST the test payload to {base_url}/{name}; return (ok, status, detail)."""
    url = f"{base_url.rstrip('/')}/{name}"
    data = json.dumps(build_payload(name, business_id)).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(400).decode("utf-8", "replace").replace("\n", " ")
            return True, resp.status, body[:160]
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read(200).decode("utf-8", "replace").replace("\n", " ")
        except Exception:
            pass
        # 404 = workflow not deployed/active; 5xx = workflow error.
        return False, e.code, detail[:160]
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"


def discover():
    groups = {"testable": [], "comms": [], "no-webhook": [], "invalid": []}
    for f in sorted(N8N_DIR.rglob("*.json")):
        cat, reason = categorize(f)
        groups[cat].append((f.stem, reason))
    return groups


C = {"g": "\033[92m", "r": "\033[91m", "y": "\033[93m", "d": "\033[90m", "x": "\033[0m"}


def _c(color, text):
    return f"{C[color]}{text}{C['x']}" if sys.stdout.isatty() else text



def main():
    p = argparse.ArgumentParser(description="Live-test all n8n webhook workflows.")
    p.add_argument("--base-url", default=os.getenv("N8N_WEBHOOK_BASE_URL", "http://localhost:5678/webhook"))
    p.add_argument("--business-id", default=os.getenv("SMOKE_BUSINESS_ID") or os.getenv("NEXT_PUBLIC_BUSINESS_ID", ""))
    p.add_argument("--include-comms", action="store_true", help="ALSO fire SMS/voice/email workflows (sends real messages!)")
    p.add_argument("--only", default="", help="test just this workflow name")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--list", action="store_true", help="show categorization, fire nothing")
    args = p.parse_args()

    groups = discover()
    total = sum(len(v) for v in groups.values())
    print(f"Discovered {total} workflows: "
          f"{len(groups['testable'])} testable, {len(groups['comms'])} comms, "
          f"{len(groups['no-webhook'])} cron/slack, {len(groups['invalid'])} invalid\n")

    if args.list:
        for cat in ("testable", "comms", "no-webhook", "invalid"):
            print(f"== {cat} ({len(groups[cat])}) ==")
            for name, reason in groups[cat]:
                print(f"   {name}" + (f"  — {reason}" if reason else ""))
            print()
        return 0

    if not args.business_id:
        print(_c("r", "ERROR: --business-id (or SMOKE_BUSINESS_ID env) is required to fire tests."))
        return 2

    to_fire = list(groups["testable"])
    if args.include_comms:
        to_fire += groups["comms"]
    if args.only:
        to_fire = [(n, r) for (n, r) in (groups["testable"] + groups["comms"]) if n == args.only]
        if not to_fire:
            print(_c("r", f"'{args.only}' is not a testable/comms workflow (maybe cron/slack).")); return 2

    print(f"Firing {len(to_fire)} workflows at {args.base_url}\n")
    passed = failed = 0
    fails = []
    for name, _ in to_fire:
        ok, status, detail = fire(args.base_url, name, args.business_id, args.timeout)
        if ok:
            passed += 1
            print(f"  {_c('g','PASS')} {name}  ({status})")
        else:
            failed += 1
            fails.append((name, status, detail))
            hint = " [not deployed/active?]" if status == 404 else ""
            print(f"  {_c('r','FAIL')} {name}  ({status}){hint}  {_c('d', detail)}")

    skipped = len(groups["comms"]) if not args.include_comms else 0
    print(f"\n{_c('g', str(passed)+' passed')}, {_c('r', str(failed)+' failed')}, "
          f"{skipped} comms skipped (use --include-comms), "
          f"{len(groups['no-webhook'])} cron/slack skipped.")
    if fails:
        print("\nFailures:")
        for name, status, detail in fails:
            print(f"  - {name} ({status}) {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
