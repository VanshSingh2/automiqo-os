import httpx, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

API_URL = "https://potential-space-succotash-g4rrr96vrv73pvgr-5678.app.github.dev/api/v1"
KEY = os.getenv("N8N_API_KEY")
headers = {"X-N8N-API-KEY": KEY}

SKIP = {"DHdmuHqgROJx6gNK","GwSsd95lO1EX82L2","RjFGS0jufb58QhLi","eU7mf80Ka2TRQLYl",
        "eXc5gE0k4nfI2yOa","iguUg4iK8okUmBZ8","auonbfRYmgLxhq7a","sc0eYTlJSdvQ8k7t",
        "f1udkyHcleYtFGaV","QxyDjiPUKROphNWt","ICyNCK7RtvSuZrF4","pJhX2JTCr43GscZ7"}

r = httpx.get(f"{API_URL}/workflows?limit=250", headers=headers, verify=False)
workflows = r.json().get("data", [])

activated = failed = skipped = 0
for wf in workflows:
    wid = wf["id"]
    if wid in SKIP:
        skipped += 1
        continue
    resp = httpx.post(f"{API_URL}/workflows/{wid}/activate", headers=headers, verify=False)
    if resp.status_code in (200, 201):
        activated += 1
        print(f"  ON  {wf['name']}")
    else:
        failed += 1
        print(f"  ERR {wf['name']}: {resp.status_code} {resp.text[:80]}")

print(f"\nActivated: {activated} | Failed: {failed} | Skipped: {skipped}")
