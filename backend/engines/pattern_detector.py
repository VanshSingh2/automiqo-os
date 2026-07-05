"""Read-only pattern detector — finds repeated failures, writes recommendations only."""
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from backend.memory.supabase_client import get_supabase


async def detect_repeated_failures(business_id: str, lookback_days: int = 14) -> list[dict]:
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    failures = sb.table("failure_patterns").select("*")\
        .eq("business_id", business_id).eq("fix_applied", False)\
        .gte("created_at", cutoff).execute().data or []

    reflections = sb.table("reflections").select("*")\
        .eq("business_id", business_id).eq("mistake", True)\
        .gte("created_at", cutoff).execute().data or []

    grouped = defaultdict(list)
    for f in failures:
        key = (f.get("pattern", "") or f.get("root_cause", ""))[:60]
        grouped[key].append({**f, "source": "failure_patterns"})
    for r in reflections:
        key = r.get("why", "")[:60]
        grouped[key].append({**r, "source": "reflections"})

    detected = []
    for pattern_key, occurrences in grouped.items():
        if len(occurrences) >= 3:
            detected.append({
                "pattern": pattern_key,
                "occurrence_count": len(occurrences),
                "agents_involved": list(set(o.get("agent_name", "unknown") for o in occurrences)),
                "first_seen": min(o.get("created_at", "") for o in occurrences),
                "last_seen": max(o.get("created_at", "") for o in occurrences),
                "sample_details": occurrences[0].get("what_failed") or occurrences[0].get("why", ""),
            })
    return detected


async def create_pattern_recommendations(business_id: str) -> dict:
    sb = get_supabase()
    patterns = await detect_repeated_failures(business_id)
    created = 0
    for p in patterns:
        existing = sb.table("recommendations").select("id")\
            .eq("business_id", business_id)\
            .eq("category", "repeated_failure_pattern")\
            .ilike("description", f"%{p['pattern'][:40]}%")\
            .eq("status", "pending").execute()
        if existing.data:
            continue
        agents_str = ", ".join(p["agents_involved"])
        sb.table("recommendations").insert({
            "business_id": business_id,
            "generated_by": "pattern_detector",
            "category": "repeated_failure_pattern",
            "title": f"Recurring issue: {p['pattern'][:80]}",
            "description": (
                f"Occurred {p['occurrence_count']} times in 14 days, involving: {agents_str}.\n\n"
                f"Example: {p['sample_details']}\n\n"
                f"No changes made — for your awareness and optional action."
            ),
            "priority": "normal",
            "status": "pending",
        }).execute()
        created += 1
    return {"patterns_detected": len(patterns), "new_recommendations": created}
