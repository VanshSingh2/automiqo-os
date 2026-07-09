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
from agents.base_agent import BaseAgent
from agents.departments.learning.agent import LearningDirectorAgent


async def run_learning_daily_loop(business_id: str) -> dict:
    sb = get_supabase()
    bid = business_id
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()

    # Only run managers this business has enabled.
    from backend.engines.business_blueprint import is_manager_enabled
    try:
        _biz = sb.table("businesses").select("config").eq("id", bid).limit(1).execute().data
        config = (_biz[0].get("config") if _biz else {}) or {}
    except Exception:
        config = {}
    reflection_on = is_manager_enabled(config, "learning", "reflection")
    knowledge_on = is_manager_enabled(config, "learning", "knowledge")
    innovation_on = is_manager_enabled(config, "learning", "innovation")

    actions_taken = []
    approvals_queued = []

    # ── 0. CLOSE THE SELF-IMPROVEMENT LOOP ───────────────────
    # Evaluate any canaries started on a prior night: adopt if the metric held,
    # else roll back. evaluate_canary is a no-op unless AUTO_IMPROVE is on, and
    # is fully best-effort so it can never break the nightly loop.
    try:
        from backend.engines import improvement_manager
        pending = sb.table("improvements").select("id").eq("business_id", bid) \
            .eq("status", "canary").limit(50).execute().data or []
        for _imp in pending:
            await improvement_manager.evaluate_canary(bid, _imp.get("id"))
        if pending:
            actions_taken.append(f"evaluated {len(pending)} improvement canary(ies)")
    except Exception:
        pass

    # ── 1. ANALYZE TODAY'S CALLS ─────────────────────────────
    calls = sb.table("calls").select("id,transcript,summary,outcome,sentiment")\
        .eq("business_id", bid).gte("called_at", today_start)\
        .not_.is_("transcript", "null").execute().data or []
    for call in (calls[:10] if reflection_on else []):
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
    if knowledge_on and failed_tasks:
        await dispatch_action(bid, "detect_knowledge_gap", {
            "failed_workflows": [t["workflow"] for t in failed_tasks],
            "errors": [t.get("error", "") for t in failed_tasks if t.get("error")][:5],
        }, "Learning daily loop: knowledge gap from today's failures")
        actions_taken.append(f"knowledge gap analysis: {len(failed_tasks)} failures")

    # ── 3. FAILURE PATTERN STORAGE ───────────────────────────
    errors = [t.get("error", "") for t in failed_tasks if t.get("error")]
    if reflection_on and errors:
        await dispatch_action(bid, "store_failure_pattern", {
            "patterns": errors[:5],
            "workflows": [t["workflow"] for t in failed_tasks],
        }, "Learning daily loop: storing failure patterns")
        actions_taken.append("failure patterns stored")

    # ── 4. SCORE AGENT CONVERSATIONS ─────────────────────────
    reflections = sb.table("reflections").select("id,what_happened,lesson,confidence")\
        .eq("business_id", bid).gte("created_at", today_start).execute().data or []
    if reflection_on and reflections:
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
    for exp in (running_experiments if innovation_on else []):
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
        from backend.autonomous.work_memory import recall_block
        _mem = await recall_block(bid, "Learning Lead", "patterns lessons mistakes improvements experiments")
        resp = await agent.run(
            "Nightly learning review: analyze today's patterns, identify what the AI team "
            "did well and what needs improvement. Generate 3 specific prompt or workflow improvements. "
            "Reference what you remember from prior days where relevant." + _mem,
            context=context,
        )
        recs = list(resp.recommendations or [])[:5]
        for rec in recs:
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

        # SAFE CLOSED-LOOP SELF-IMPROVEMENT — PER-AGENT TARGETED (best-effort).
        # The owner-facing recommendations above are untouched. Here we make ONE
        # extra LLM call to turn the day's free-text suggestions into STRUCTURED,
        # TARGETED proposals aimed at a REAL prompt name (so an adopted addendum
        # actually reaches that agent) or a workflow. Everything is wrapped so a
        # failure here can never break the nightly loop.
        try:
            from backend.engines import improvement_manager
            valid_targets = sorted(improvement_manager.valid_prompt_targets())
            recs_text = "\n".join(f"- {r}" for r in recs)
            if recs_text.strip():
                from langchain_core.messages import HumanMessage, SystemMessage
                import json as _json
                _sys = (
                    "You convert nightly learning review notes into targeted "
                    "self-improvement proposals for an AI company OS. Respond with "
                    "STRICT JSON only, no prose, in exactly this shape:\n"
                    '{"improvements":[{"target_type":"prompt"|"workflow",'
                    '"target_key":"<prompt name or workflow>",'
                    '"improvement":"<specific change text>","rationale":"<why>"}]}\n'
                    "Rules: at most 3 items. For target_type 'prompt', target_key "
                    "MUST be exactly one of the valid prompt names listed. For "
                    "'workflow', target_key is the workflow name. 'improvement' is "
                    "the concrete additive instruction to apply."
                )
                _human = (
                    f"Valid prompt names: {', '.join(valid_targets)}\n\n"
                    f"Today's recommendations:\n{recs_text}\n\n"
                    "Produce the JSON now."
                )
                _llm = getattr(agent, "llm", None) or BaseAgent._build_dept_llm()
                _resp = await _llm.ainvoke([
                    SystemMessage(content=_sys),
                    HumanMessage(content=_human),
                ])
                _content = getattr(_resp, "content", _resp)
                if isinstance(_content, list):
                    _content = "".join(
                        (b.get("text", "") if isinstance(b, dict) else str(b))
                        for b in _content
                    )
                _content = str(_content or "")
                # Strip markdown fences if present.
                import re as _re
                _m = _re.search(r"```[\w]*\s*([\s\S]*?)```", _content)
                _clean = _m.group(1).strip() if _m else _content.strip()
                try:
                    _parsed = _json.loads(_clean)
                except Exception:
                    _parsed = {}
                _items = (_parsed or {}).get("improvements") or []
                _proposed = 0
                for _it in _items[:3]:
                    if not isinstance(_it, dict):
                        continue
                    _tt = (_it.get("target_type") or "").strip().lower()
                    _tk = (_it.get("target_key") or "").strip()
                    _imp = (_it.get("improvement") or "").strip()
                    _why = (_it.get("rationale") or "").strip()
                    if _tt not in ("prompt", "workflow") or not _tk or not _imp:
                        continue
                    # Skip prompt proposals whose target is not a real prompt name
                    # (an addendum on a non-existent key would never reach an agent).
                    if not improvement_manager._valid_target(_tt, _tk):
                        continue
                    imp_id = await improvement_manager.propose(
                        bid, _tt, _tk,
                        new_value=_imp, old_value="",
                        rationale=_why or "Nightly targeted learning improvement",
                    )
                    if imp_id:
                        _proposed += 1
                        # start_canary is a no-op/False unless AUTO_IMPROVE is on.
                        await improvement_manager.start_canary(bid, imp_id)
                if _proposed:
                    actions_taken.append(f"targeted improvement proposals: {_proposed}")
        except Exception:
            pass
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
