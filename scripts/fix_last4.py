import httpx, os, sys, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API_URL = "https://potential-space-succotash-g4rrr96vrv73pvgr-5678.app.github.dev/api/v1"
KEY = os.getenv("N8N_API_KEY", "")
CAL_KEY = os.getenv("CAL_COM_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
headers = {"X-N8N-API-KEY": KEY, "Content-Type": "application/json"}

r = httpx.get(f"{API_URL}/workflows?limit=250", headers={"X-N8N-API-KEY": KEY}, verify=False)
wfs = {w["name"]: w["id"] for w in r.json().get("data", [])}

TARGETS = ["check_availability", "fill_waitlist_slot", "send_reminder_2h", "reschedule_appointment"]

for name in TARGETS:
    wid = wfs.get(name)
    if not wid:
        print(f"NOT FOUND: {name}")
        continue
    r2 = httpx.get(f"{API_URL}/workflows/{wid}", headers={"X-N8N-API-KEY": KEY}, verify=False)
    full = r2.json()
    nodes = copy.deepcopy(full.get("nodes", []))

    for n in nodes:
        if n.get("name") == "Execute" and n.get("type") == "n8n-nodes-base.httpRequest":
            p = n.setdefault("parameters", {})
            url = str(p.get("url") or "")
            p.pop("authentication", None)
            p.pop("genericAuthType", None)
            p.pop("credentials", None)
            n.pop("credentials", None)
            p["sendHeaders"] = True
            supa_host = SUPABASE_URL.replace("https://", "").split(".")[0] if SUPABASE_URL else ""
            if "cal.com" in url:
                p["headerParameters"] = {"parameters": [
                    {"name": "Authorization", "value": f"Bearer {CAL_KEY}"},
                    {"name": "cal-api-version", "value": "2024-08-13"},
                ]}
            elif supa_host and supa_host in url:
                p["headerParameters"] = {"parameters": [
                    {"name": "apikey", "value": SUPABASE_KEY},
                    {"name": "Authorization", "value": f"Bearer {SUPABASE_KEY}"},
                ]}
            else:
                p["headerParameters"] = {"parameters": [
                    {"name": "Authorization", "value": f"Bearer {CAL_KEY}"},
                ]}

    payload = {"name": name, "nodes": nodes,
               "connections": full.get("connections", {}),
               "settings": full.get("settings", {})}
    upd = httpx.put(f"{API_URL}/workflows/{wid}", headers=headers, json=payload, verify=False, timeout=30)
    if upd.status_code not in (200, 201):
        print(f"  PATCH ERR {name}: {upd.text[:100]}")
        continue
    act = httpx.post(f"{API_URL}/workflows/{wid}/activate", headers=headers, verify=False)
    if act.status_code in (200, 201):
        print(f"  ON  {name}")
    else:
        print(f"  ERR {name}: {act.json().get('message','')[:100]}")
