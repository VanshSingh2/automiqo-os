"""
Learning Director Autonomous Daily Work Loop — runs at 10pm.
Proactively improves the OS every night:
- Analyzes all call transcripts from today
- Identifies knowledge gaps from failed tasks
- Scores agent conversation quality
- Detects recurring failure patterns
- Updates agent confidence scores
- Generates prompt improvement suggestions
- Runs A/B experiment analysis
"""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from backend.memory.supabase_client import get_supabase
from backend.events.handlers import dispatch_action
from agents.departments.learning.agent import LearningDirectorAgent


async def run_learning_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    actions_taken = []
    approvals_queued = []

    # ── 1. ANALYZE TODAY'S CALLS ─────────────────────────────
    calls = sb.table("calls").select("id,transcript,summary,outcome,sentiment")\
        .eq("business_id", bid).gte("called_at", today_start)\
        .not_.is_("transcript", "null").execute().data or []
    for call in calls[:10]:
        if call.get("transcript"):
            await dispatch_action(bid, "analyze_call_transcript", {
                "call_id": call["id"],
                "transcript": (call.get("transcript") or "")[:1000],
                "outcome": call.get("outcome", ""),
                "sentiment": call.get("sentiment", ""),
            }, "Learning daily loop: analyze today's call")
            actions_taken.append(f"call analyzed: {call['id']}")

    # ── 2. KNOWLEDGE GAP DETECTION ───────────────────────────
    failed_tasks = sb.table("tasks").select("workflow,error,parameters")\
        .eq("business_id", bid).eq("status", "failed")\
        .gte("created_at", today_start).execute().data or []
    if failed_tasks:
        await dispatch_action(bid, "detect_knowledge_gap", {
            "failed_workflows": [t["workflow"] for t in failed_tasks],
            "errors": [t.get("error", "") for t in failed_tasks if t.get("error")][:5],
        }, "Learning daily loop: knowledge gap from today's failures")
        actions_taken.append(f"knowledge gap analysis: {len(failed_tasks)} failures")

    # ── 3. FAILURE PATTERN STORAGE ───────────────────────────
    errors = [t.get("error", "") for t in failed_tasks if t.get("error")]
    if errors:
        await dispatch_action(bid, "store_failure_pattern", {
            "patterns": errors[:5],
            "workflows": [t["workflow"] for t in failed_tasks],
        }, "Learning daily loop: storing failure patterns")
        actions_taken.append("failure patterns stored")

    # ── 4. SCORE AGENT CONVERSATIONS ─────────────────────────
    reflections = sb.table("reflections").select("id,what_happened,lesson,confidence")\
        .eq("business_id", bid).gte("created_at", today_start).execute().data or []
    if reflections:
        await dispatch_action(bid, "score_conversation", {
            "reflection_count": len(reflections),
            "date": now.strftime("%Y-%m-%d"),
        }, "Learning daily loop: scoring today's agent conversations")
        actions_taken.append(f"scored {len(reflections)} reflections")

    # ── 5. UPDATE AGENT CONFIDENCE ───────────────────────────
    await dispatch_action(bid, "update_agent_confidence", {
        "date": now.strftime("%Y-%m-%d"),
        "metrics": {
            "calls_analyzed": len(calls),
            "failures_detected": len(failed_tasks),
            "reflections_scored": len(reflections),
        }
    }, "Learning daily loop: daily confidence update")
    actions_taken.append("agent confidence updated")

    # ── 6. A/B EXPERIMENT ANALYSIS ───────────────────────────
    running_experiments = sb.table("experiments").select("id,name,metric,started_at")\
        .eq("business_id", bid).eq("status", "running").execute().data or []
    for exp in running_experiments:
        started = exp.get("started_at", "")
        # If running for more than 7 days, declare winner
        if started and started < week_ago:
            await dispatch_action(bid, "declare_experiment_winner", {
                "experiment_id": exp["id"],
                "experiment_name": exp.get("name", ""),
            }, f"Learning daily loop: experiment '{exp['name']}' has enough data")
            approvals_queued.append(f"experiment winner: {exp.get('name','?')}")

    # ── 7. GENERATE NIGHTLY REFLECTION ───────────────────────
    await dispatch_action(bid, "generate_reflection", {
        "date": now.strftime("%Y-%m-%d"),
        "calls_analyzed": len(calls),
        "failures_detected": len(failed_tasks),
        "experiments_evaluated": len(running_experiments),
    }, "Learning daily loop: nightly system reflection")
    actions_taken.append("nightly reflection generated")

    # ── 8. LEARNING AGENT STRATEGIC REVIEW ───────────────────
    try:
        agent = LearningDirectorAgent(UUID(bid))
        context = {
            "calls_today": len(calls),
            "failures_today": len(failed_tasks),
            "reflections_today": len(reflections),
            "running_experiments": len(running_experiments),
        }
        resp = await agent.run(
            "Nightly learning review: analyze today's patterns, identify what the AI team "
            "did well and what needs improvement. Generate 3 specific prompt or workflow improvements.",
            context=context,
        )
        for rec in (resp.recommendations or [])[:5]:
            sb.table("recommendations").insert({
                "business_id": bid,
                "generated_by": "learning_director",
                "category": "improvement",
                "title": rec[:100],
                "description": rec,
                "priority": "normal",
                "status": "pending",
            }).execute()
        approvals_queued.append(f"learning recommendations: {len(resp.recommendations or [])}")
    except Exception:
        pass

    return {
        "department": "Learning",
        "actions_taken": len(actions_taken),
        "approvals_queued": len(approvals_queued),
        "details": actions_taken + approvals_queued,
        "calls_analyzed": len(calls),
        "failures_processed": len(failed_tasks),
    }
