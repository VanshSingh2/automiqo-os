"""
Replace Twilio nodes with Telnyx HTTP Request nodes in all n8n workflows,
update Cal.com API key references, then activate all automiqo-os workflows.
"""
import httpx, os, sys, json, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API_URL = "https://potential-space-succotash-g4rrr96vrv73pvgr-5678.app.github.dev/api/v1"
KEY = os.getenv("N8N_API_KEY")
TELNYX_KEY = os.getenv("TELNYX_API_KEY")
TELNYX_FROM = os.getenv("TELNYX_PHONE_NUMBER", "+19482194246")
CAL_KEY = os.getenv("CAL_COM_API_KEY")
headers = {"X-N8N-API-KEY": KEY, "Content-Type": "application/json"}

SKIP = {"DHdmuHqgROJx6gNK","GwSsd95lO1EX82L2","RjFGS0jufb58QhLi","eU7mf80Ka2TRQLYl",
        "eXc5gE0k4nfI2yOa","iguUg4iK8okUmBZ8","auonbfRYmgLxhq7a","sc0eYTlJSdvQ8k7t",
        "f1udkyHcleYtFGaV","QxyDjiPUKROphNWt","ICyNCK7RtvSuZrF4","pJhX2JTCr43GscZ7"}

def make_telnyx_node(old_node):
    """Replace a Twilio SMS node with a Telnyx HTTP Request node."""
    # Try to preserve the recipient phone from old params
    old_params = old_node.get("parameters", {})
    to_phone = "={{ $json.customer_phone || $json.phone || $json.to }}"
    # Check for body parameters
    for p in old_params.get("bodyParameters", {}).get("parameters", []):
        if p.get("name") == "To":
            to_phone = p.get("value", to_phone)
            break
    body_text = "={{ $json.message || $json.text || 'Hello from Automiqo OS' }}"
    for p in old_params.get("bodyParameters", {}).get("parameters", []):
        if p.get("name") == "Body":
            body_text = p.get("value", body_text)
            break

    return {
        "id": old_node["id"],
        "name": old_node.get("name", "Send SMS via Telnyx"),
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": old_node.get("position", [650, 300]),
        "parameters": {
            "url": "https://api.telnyx.com/v2/messages",
            "method": "POST",
            "sendHeaders": True,
            "headerParameters": {"parameters": [
                {"name": "Authorization", "value": f"Bearer {TELNYX_KEY}"},
                {"name": "Content-Type", "value": "application/json"},
            ]},
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": f'={{"from": "{TELNYX_FROM}", "to": "{{{{ $json.customer_phone || $json.phone }}}}", "text": "{{{{ $json.message || $json.body || \'Message from Automiqo OS\' }}}}"}}'
        }
    }

def patch_workflow_nodes(nodes):
    """Replace Twilio nodes and update Cal.com auth in all nodes."""
    patched = []
    changed = False
    for node in nodes:
        n = copy.deepcopy(node)
        ntype = n.get("type", "")
        # Replace Twilio SMS nodes
        if "twilio" in ntype.lower():
            n = make_telnyx_node(node)
            changed = True
        # Update Cal.com auth in HTTP Request nodes
        if ntype == "n8n-nodes-base.httpRequest":
            params = n.get("parameters", {})
            for hp in params.get("headerParameters", {}).get("parameters", []):
                if "cal" in str(hp.get("value","")).lower() or hp.get("name") == "Authorization":
                    if "cal_live_" in str(hp.get("value","")):
                        hp["value"] = f"Bearer {CAL_KEY}"
                        changed = True
            # Also check body params for cal api key
            url = str(params.get("url",""))
            if "cal.com" in url:
                for hp in params.get("headerParameters", {}).get("parameters", []):
                    if hp.get("name") == "Authorization" and "Bearer" in str(hp.get("value","")):
                        hp["value"] = f"Bearer {CAL_KEY}"
                        changed = True
        patched.append(n)
    return patched, changed

# Get all workflows
r = httpx.get(f"{API_URL}/workflows?limit=250", headers=headers, verify=False)
workflows = r.json().get("data", [])

patched_count = activated = failed = skipped = 0

for wf in workflows:
    wid = wf["id"]
    name = wf["name"]

    if wid in SKIP:
        skipped += 1
        continue

    # Get full workflow
    r = httpx.get(f"{API_URL}/workflows/{wid}", headers={"X-N8N-API-KEY": KEY}, verify=False)
    if r.status_code != 200:
        print(f"  SKIP (can't fetch) {name}")
        continue
    full = r.json()
    nodes = full.get("nodes", [])
    connections = full.get("connections", {})
    settings = full.get("settings", {})

    # Patch nodes
    new_nodes, changed = patch_workflow_nodes(nodes)

    # Update if changed
    if changed:
        payload = {"name": name, "nodes": new_nodes, "connections": connections, "settings": settings}
        upd = httpx.put(f"{API_URL}/workflows/{wid}", headers=headers,
                        json=payload, verify=False, timeout=30)
        if upd.status_code in (200, 201):
            patched_count += 1
            print(f"  PATCHED {name}")
        else:
            print(f"  PATCH ERR {name}: {upd.status_code} {upd.text[:80]}")

    # Activate
    if not wf.get("active"):
        act = httpx.post(f"{API_URL}/workflows/{wid}/activate", headers=headers, verify=False)
        if act.status_code in (200, 201):
            activated += 1
            print(f"  ON  {name}")
        else:
            err = act.json().get("message","")[:100]
            # Only print if not already active or webhook conflict (those are fine)
            if "conflict" not in err.lower() and "already" not in err.lower():
                failed += 1
                print(f"  ERR {name}: {err}")
    else:
        print(f"  ALREADY ON  {name}")

print(f"\nPatched: {patched_count} | Newly activated: {activated} | Failed: {failed} | Skipped: {skipped}")
