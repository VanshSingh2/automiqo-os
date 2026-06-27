"""Deploy all n8n workflow JSONs to the live n8n instance."""
import os, json, glob, httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

N8N_BASE = os.getenv("N8N_WEBHOOK_BASE_URL", "").replace("/webhook", "")
API_URL = f"{N8N_BASE}/api/v1"
API_KEY = os.getenv("N8N_API_KEY", "")

headers = {
    "X-N8N-API-KEY": API_KEY,
    "Content-Type": "application/json",
}

def get_existing():
    r = httpx.get(f"{API_URL}/workflows?limit=250", headers=headers, timeout=30, verify=False)
    r.raise_for_status()
    return {w["name"]: w["id"] for w in r.json().get("data", [])}

def deploy(path, existing):
    with open(path, encoding="utf-8-sig") as f:
        wf = json.load(f)
    name = wf.get("name", os.path.basename(path).replace(".json", ""))
    payload = {
        "name": name,
        "nodes": wf.get("nodes", []),
        "connections": wf.get("connections", {}),
        "settings": wf.get("settings", {}),
    }
    if name in existing:
        wf_id = existing[name]
        r = httpx.put(f"{API_URL}/workflows/{wf_id}", headers=headers,
                      json=payload, timeout=30, verify=False)
        action = "updated"
    else:
        r = httpx.post(f"{API_URL}/workflows", headers=headers,
                       json=payload, timeout=30, verify=False)
        action = "created"
    if r.status_code in (200, 201):
        return action, name, None
    return "failed", name, f"{r.status_code}: {r.text[:100]}"

base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = sorted(glob.glob(os.path.join(base, "n8n", "**", "*.json"), recursive=True))

print(f"Found {len(files)} workflows. Connecting to {API_URL}...")

try:
    existing = get_existing()
    print(f"Existing in n8n: {len(existing)}")
except Exception as e:
    print(f"ERROR connecting: {e}")
    exit(1)

created = updated = failed = 0
for path in files:
    try:
        action, name, err = deploy(path, existing)
    except Exception as ex:
        failed += 1; print(f"  FAIL {path}: {ex}"); continue
    if action == "created": created += 1; print(f"  + {name}")
    elif action == "updated": updated += 1; print(f"  ~ {name}")
    else: failed += 1; print(f"  FAIL {name}: {err}")

print(f"\nDone: {created} created, {updated} updated, {failed} failed")
