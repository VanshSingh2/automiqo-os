import httpx, os, sys, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API_URL = "https://potential-space-succotash-g4rrr96vrv73pvgr-5678.app.github.dev/api/v1"
KEY = os.getenv("N8N_API_KEY", "")
CAL_KEY = os.getenv("CAL_COM_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
hdrs = {"X-N8N-API-KEY": KEY, "Content-Type": "application/json"}

# Default URLs for each workflow
DEFAULTS = {
    "check_availability":    ("GET",  f"{SUPABASE_URL}/rest/v1/appointments?select=id,scheduled_at,staff_id"),
    "fill_waitlist_slot":    ("POST", f"{SUPABASE_URL}/rest/v1/appointments"),
    "send_reminder_2h":      ("POST", "https://api.telnyx.com/v2/messages"),
    "reschedule_appointment":("PATCH", f"https://api.cal.com/v2/bookings"),
}

r = httpx.get(f"{API_URL}/workflows?limit=250", headers={"X-N8N-API-KEY": KEY}, verify=False)
wfs = {w["name"]: w["id"] for w in r.json().get("data", [])}

for name, (method, url) in DEFAULTS.items():
    wid = wfs.get(name)
    if not wid:
        print(f"NOT FOUND: {name}"); continue
    r2 = httpx.get(f"{API_URL}/workflows/{wid}", headers={"X-N8N-API-KEY": KEY}, verify=False)
    full = r2.json()
    nodes = copy.deepcopy(full.get("nodes", []))

    for n in nodes:
        if n.get("name") == "Execute":
            n["typeVersion"] = 4
            p = n.setdefault("parameters", {})
            p["method"] = method
            p["url"] = url
            p["sendHeaders"] = True
            if "telnyx" in url:
                p["headerParameters"] = {"parameters": [
                    {"name": "Authorization", "value": f"Bearer {os.getenv('TELNYX_API_KEY','')}"},
                    {"name": "Content-Type", "value": "application/json"},
                ]}
            elif "cal.com" in url:
                p["headerParameters"] = {"parameters": [
                    {"name": "Authorization", "value": f"Bearer {CAL_KEY}"},
                    {"name": "cal-api-version", "value": "2024-08-13"},
                ]}
            else:
                p["headerParameters"] = {"parameters": [
                    {"name": "apikey", "value": SUPABASE_KEY},
                    {"name": "Authorization", "value": f"Bearer {SUPABASE_KEY}"},
                ]}

    payload = {"name": name, "nodes": nodes,
               "connections": full.get("connections", {}),
               "settings": full.get("settings", {})}
    upd = httpx.put(f"{API_URL}/workflows/{wid}", headers=hdrs, json=payload, verify=False, timeout=30)
    if upd.status_code not in (200, 201):
        print(f"  PATCH ERR {name}: {upd.text[:100]}"); continue
    act = httpx.post(f"{API_URL}/workflows/{wid}/activate", headers=hdrs, verify=False)
    if act.status_code in (200, 201):
        print(f"  ON  {name}")
    else:
        print(f"  ERR {name}: {act.json().get('message','')[:100]}")
