"""Fix workflows with Supabase node credential issues by replacing with plain HTTP requests."""
import httpx, os, sys, json, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API_URL = "https://potential-space-succotash-g4rrr96vrv73pvgr-5678.app.github.dev/api/v1"
KEY = os.getenv("N8N_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
headers = {"X-N8N-API-KEY": KEY, "Content-Type": "application/json"}

FAILING = [
    "Rollback to Version", "check_availability", "fill_waitlist_slot",
    "Run Regression Tests", "Check Tenant Isolation", "Generate Cost Report",
    "Rotate API Key Reminder", "send_reminder_2h", "reschedule_appointment",
    "Monitor VPS Health", "Execute Deployment", "Compress Agent Prompt"
]

SUPABASE_NODE_TYPES = ["n8n-nodes-base.supabase", "@n8n/n8n-nodes-langchain.supabase"]

def fix_node(node):
    """Replace Supabase credential node with plain HTTP Request to Supabase REST API."""
    ntype = node.get("type","")
    if not any(st in ntype for st in SUPABASE_NODE_TYPES):
        return node, False

    params = node.get("parameters", {})
    table = params.get("tableId", params.get("table", "tasks"))
    operation = params.get("operation", "getAll")

    method_map = {"create": "POST", "upsert": "POST", "update": "PATCH",
                  "delete": "DELETE", "get": "GET", "getAll": "GET"}
    method = method_map.get(operation, "GET")

    return {
        "id": node["id"],
        "name": node.get("name", "Supabase Query"),
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4,
        "position": node.get("position", [650, 300]),
        "parameters": {
            "url": f"{SUPABASE_URL}/rest/v1/{table}",
            "method": method,
            "sendHeaders": True,
            "headerParameters": {"parameters": [
                {"name": "apikey", "value": SUPABASE_KEY},
                {"name": "Authorization", "value": f"Bearer {SUPABASE_KEY}"},
                {"name": "Content-Type", "value": "application/json"},
            ]},
        }
    }, True

# Get all workflows
r = httpx.get(f"{API_URL}/workflows?limit=250", headers=headers, verify=False)
all_wf = {wf["name"]: wf for wf in r.json().get("data", [])}

patched = activated = failed = 0

for name in FAILING:
    if name not in all_wf:
        print(f"  NOT FOUND: {name}")
        continue
    wid = all_wf[name]["id"]

    r = httpx.get(f"{API_URL}/workflows/{wid}", headers={"X-N8N-API-KEY": KEY}, verify=False)
    if r.status_code != 200:
        continue
    full = r.json()
    nodes = full.get("nodes", [])

    new_nodes = []
    changed = False
    for node in nodes:
        fixed, was_changed = fix_node(node)
        new_nodes.append(fixed)
        if was_changed:
            changed = True

    if changed:
        payload = {"name": name, "nodes": new_nodes,
                   "connections": full.get("connections", {}),
                   "settings": full.get("settings", {})}
        upd = httpx.put(f"{API_URL}/workflows/{wid}", headers=headers,
                        json=payload, verify=False, timeout=30)
        if upd.status_code in (200, 201):
            patched += 1
            print(f"  PATCHED {name}")
        else:
            print(f"  PATCH ERR {name}: {upd.text[:100]}")

    # Activate
    act = httpx.post(f"{API_URL}/workflows/{wid}/activate", headers=headers, verify=False)
    if act.status_code in (200, 201):
        activated += 1
        print(f"  ON  {name}")
    else:
        err = act.json().get("message","")[:120]
        failed += 1
        print(f"  ERR {name}: {err}")

print(f"\nPatched: {patched} | Activated: {activated} | Failed: {failed}")
