"""Creates one fake medspa business with sample data for local dev."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from backend.memory.supabase_client import get_supabase
from datetime import datetime, timezone, timedelta
import uuid

BUSINESS_ID = "00000000-0000-0000-0000-000000000001"


def seed():
    sb = get_supabase()

    sb.table("businesses").upsert({
        "id": BUSINESS_ID,
        "name": "Glow Med Spa",
        "industry": "medspa",
        "phone": "+12015551234",
        "email": "owner@glowmedspa.com",
        "address": "123 Main St, Hoboken, NJ 07030",
        "timezone": "America/New_York",
        "active": True,
    }).execute()
    print("Business created")

    staff_id = str(uuid.uuid4())
    sb.table("staff").upsert({
        "id": staff_id,
        "business_id": BUSINESS_ID,
        "name": "Sarah Chen",
        "role": "aesthetician",
        "services": ["botox", "filler", "facial"],
        "active": True,
    }).execute()
    print("Staff created")

    customers = [
        {"name": "Emma Wilson", "phone": "+12015550001", "email": "emma@test.com", "tags": ["vip"], "lifetime_value": 2400, "visit_count": 8},
        {"name": "James Park", "phone": "+12015550002", "tags": ["dormant"], "lifetime_value": 600,
         "last_visit": (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()},
        {"name": "Lisa Torres", "phone": "+12015550003", "tags": ["churn_risk"], "lifetime_value": 300, "visit_count": 2},
        {"name": "Mike Johnson", "phone": "+12015550004", "tags": [], "lifetime_value": 0, "visit_count": 0},
    ]
    for c in customers:
        c["business_id"] = BUSINESS_ID
        sb.table("customers").insert(c).execute()
    print(f"{len(customers)} customers created")

    now = datetime.now(timezone.utc)
    appts = [
        {"service": "Botox", "scheduled_at": now.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
         "status": "completed", "revenue": 450},
        {"service": "Filler", "scheduled_at": now.replace(hour=13, minute=0, second=0, microsecond=0).isoformat(),
         "status": "scheduled", "revenue": 650},
        {"service": "Facial", "scheduled_at": now.replace(hour=15, minute=0, second=0, microsecond=0).isoformat(),
         "status": "no_show", "revenue": 120},
    ]
    for a in appts:
        a["business_id"] = BUSINESS_ID
        a["staff_id"] = staff_id
        sb.table("appointments").insert(a).execute()
    print(f"{len(appts)} appointments created")

    print("\nDev seed complete. Business ID:", BUSINESS_ID)


if __name__ == "__main__":
    seed()
