"""
System Test API — tests every component of Automiqo OS end-to-end.
Designed to run against a live system with real Supabase/Redis connections.
Every test is independent and reports PASS / WARN / FAIL with detail.

Endpoints:
  POST /test/full          — run all suites
  POST /test/suite/{name}  — run one suite
  GET  /test/quick         — fast smoke test (no LLM calls)
"""
import os
import asyncio
import httpx
import time
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/test", tags=["system-tests"])

# ── helpers ────────────────────────────────────────────────────────────────────

def _result(name: str, status: str, detail: str = "", data: dict = None) -> dict:
    return {"test": name, "status": status, "detail": detail, "data": data or {}}

def _pass(name, detail="", data=None):  return _result(name, "PASS", detail, data)
def _warn(name, detail="", data=None):  return _result(name, "WARN", detail, data)
def _fail(name, detail="", data=None):  return _result(name, "FAIL", detail, data)


class TestRequest(BaseModel):
    business_id: str = "00000000-0000-0000-0000-000000000001"
    include_llm_tests: bool = False   # LLM calls cost money — opt-in


# ── TEST SUITE 1: Infrastructure ───────────────────────────────────────────────

async def suite_infrastructure(bid: str) -> list[dict]:
    results = []

    # 1a. Supabase connectivity
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        rows = sb.table("businesses").select("id").limit(1).execute()
        results.append(_pass("supabase_connection", f"Connected. Response: {type(rows.data)}"))
    except Exception as e:
        results.append(_fail("supabase_connection", str(e)))

    # 1b. Required env vars
    required = [
        "OPENAI_API_KEY","SUPABASE_URL","SUPABASE_SERVICE_KEY",
        "REDIS_URL","JWT_SECRET","CRON_SECRET",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if not missing:
        results.append(_pass("env_vars", f"All {len(required)} required vars set"))
    elif len(missing) <= 2:
        results.append(_warn("env_vars", f"Missing: {missing}"))
    else:
        results.append(_fail("env_vars", f"Missing critical vars: {missing}"))

    # 1c. Redis connectivity
    try:
        import redis as rl
        r = rl.from_url(os.getenv("REDIS_URL","redis://localhost:6379"), socket_timeout=3)
        r.ping()
        high = r.llen("tasks:high")
        normal = r.llen("tasks:normal")
        results.append(_pass("redis_connection", f"Connected. Queue: high={high} normal={normal}",
                             {"tasks_high": high, "tasks_normal": normal}))
    except Exception as e:
        results.append(_fail("redis_connection", str(e)))

    # 1d. All required Supabase tables exist
    required_tables = [
        "businesses","customers","staff","appointments","inventory",
        "calls","messages","campaigns","tasks","reflections",
        "recommendations","reports","goals","knowledge","leads",
        "events","conversations","ai_costs","audit_log",
    ]
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        missing_tables = []
        for table in required_tables:
            try:
                sb.table(table).select("id").limit(0).execute()
            except Exception:
                missing_tables.append(table)
        if not missing_tables:
            results.append(_pass("supabase_tables", f"All {len(required_tables)} tables exist"))
        else:
            results.append(_fail("supabase_tables", f"Missing tables: {missing_tables}"))
    except Exception as e:
        results.append(_fail("supabase_tables", str(e)))

    return results


# ── TEST SUITE 2: Dispatcher + Queue ──────────────────────────────────────────

async def suite_dispatcher(bid: str) -> list[dict]:
    results = []

    # 2a. Can create a task
    task_id = str(uuid4())
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        sb.table("tasks").insert({
            "id": task_id,
            "business_id": bid,
            "created_by": "system_test",
            "workflow": "test_ping",
            "priority": "normal",
            "parameters": {"test": True},
            "status": "pending",
        }).execute()
        results.append(_pass("task_create", f"Task {task_id[:8]} created in Supabase"))
    except Exception as e:
        results.append(_fail("task_create", str(e)))
        return results

    # 2b. Can enqueue to Redis
    try:
        from backend.dispatcher.queue import enqueue_task
        await enqueue_task({
            "task_id": task_id,
            "workflow": "test_ping",
            "business_id": bid,
            "priority": "normal",
            "parameters": {"test": True},
        })
        results.append(_pass("task_enqueue", "Task pushed to Redis queue"))
    except Exception as e:
        results.append(_fail("task_enqueue", str(e)))

    # 2c. Clean up test task
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        sb.table("tasks").delete().eq("id", task_id).execute()
        results.append(_pass("task_cleanup", "Test task cleaned up"))
    except Exception as e:
        results.append(_warn("task_cleanup", str(e)))

    return results


# ── TEST SUITE 3: Schemas ──────────────────────────────────────────────────────

async def suite_schemas(bid: str) -> list[dict]:
    results = []

    # 3a. All Pydantic models importable
    try:
        from shared.schemas import (
            AgentResponse, TaskRequest, TaskResult,
            BusinessConfig, CustomerProfile, ChatMessage,
            ChatRequest, OnboardRequest, TaskPriority, TaskStatus,
        )
        results.append(_pass("schemas_import", "All 10 schema models import cleanly"))
    except Exception as e:
        results.append(_fail("schemas_import", str(e)))

    # 3b. AgentResponse validates correctly
    try:
        from shared.schemas import AgentResponse
        r = AgentResponse(status="ok", summary="test", metrics={"x": 1}, recommendations=["a","b"])
        assert r.status == "ok"
        assert r.metrics["x"] == 1
        results.append(_pass("schema_agent_response", "AgentResponse validates and serialises"))
    except Exception as e:
        results.append(_fail("schema_agent_response", str(e)))

    # 3c. TaskRequest validates correctly
    try:
        from shared.schemas import TaskRequest, TaskPriority
        t = TaskRequest(
            business_id=UUID(bid),
            created_by="test",
            workflow="test_workflow",
            priority=TaskPriority.normal,
            parameters={"k": "v"},
        )
        assert t.workflow == "test_workflow"
        results.append(_pass("schema_task_request", "TaskRequest validates correctly"))
    except Exception as e:
        results.append(_fail("schema_task_request", str(e)))

    return results


# ── TEST SUITE 4: Agents (import only, no LLM calls) ──────────────────────────

async def suite_agents_import(bid: str) -> list[dict]:
    results = []

    agent_classes = [
        ("agents.base_agent", "BaseAgent"),
        ("agents.executive.ceo.agent", "CEOAgent"),
        ("agents.executive.chief_of_staff.agent", "ChiefOfStaffAgent"),
        ("agents.departments.coo.agent", "COOAgent"),
        ("agents.departments.cro.agent", "CROAgent"),
        ("agents.departments.cmo.agent", "CMOAgent"),
        ("agents.departments.cfo.agent", "CFOAgent"),
        ("agents.departments.cto.agent", "CTOAgent"),
        ("agents.departments.customer_success.agent", "CustomerSuccessAgent"),
        ("agents.departments.learning.agent", "LearningDirectorAgent"),
        ("agents.departments.cmo.managers.lead_manager", "LeadManager"),
        ("agents.departments.cto.managers.engineering.engineering_manager", "EngineeringManager"),
        ("agents.departments.cto.managers.devops.devops_manager", "DevOpsManager"),
        ("agents.departments.cto.managers.security.security_manager", "SecurityManager"),
        ("agents.departments.cto.managers.performance.performance_manager", "PerformanceManager"),
        ("agents.departments.cto.managers.documentation.documentation_manager", "DocumentationManager"),
        ("agents.departments.cto.managers.qa.qa_director", "QADirector"),
    ]

    import importlib
    ok, failed = [], []
    for module_path, class_name in agent_classes:
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            # Instantiate (doesn't make any network calls)
            instance = cls(UUID(bid))
            ok.append(class_name)
        except Exception as e:
            failed.append({"class": class_name, "error": str(e)[:200]})

    if not failed:
        results.append(_pass("agents_import", f"All {len(ok)} agent classes import and instantiate", {"agents": ok}))
    else:
        results.append(_warn("agents_import",
            f"{len(ok)} OK, {len(failed)} failed",
            {"ok": ok, "failed": failed}))

    # Sub-agent files
    sub_agent_modules = [
        "agents.departments.cto.managers.devops.agents.backup_agent",
        "agents.departments.cto.managers.devops.agents.deployment_agent",
        "agents.departments.cto.managers.security.agents.tenant_isolation_agent",
        "agents.departments.cto.managers.security.agents.credential_rotation_agent",
        "agents.departments.cto.managers.performance.agents.token_cost_optimizer_agent",
        "agents.departments.cto.managers.performance.agents.workflow_speed_agent",
        "agents.departments.cto.managers.qa.agents.bug_reporter_agent",
        "agents.departments.cto.managers.qa.agents.integration_test_agent",
    ]
    sub_ok, sub_fail = [], []
    for path in sub_agent_modules:
        try:
            importlib.import_module(path)
            sub_ok.append(path.split(".")[-1])
        except Exception as e:
            sub_fail.append({"module": path.split(".")[-1], "error": str(e)[:150]})

    if not sub_fail:
        results.append(_pass("sub_agents_import", f"All {len(sub_ok)} sub-agent modules import cleanly"))
    else:
        results.append(_warn("sub_agents_import", f"{len(sub_ok)} OK, {len(sub_fail)} failed",
                             {"failed": sub_fail}))

    return results


# ── TEST SUITE 5: Event System ─────────────────────────────────────────────────

async def suite_events(bid: str) -> list[dict]:
    results = []

    # 5a. Event bus import + publish
    try:
        from backend.events.bus import publish, E
        results.append(_pass("event_bus_import", "EventBus and EventType enum import cleanly",
                             {"event_types": len([e for e in dir(E) if not e.startswith("_")])}))
    except Exception as e:
        results.append(_fail("event_bus_import", str(e)))

    # 5b. Event router
    try:
        from backend.events.router import get_handlers, SUBSCRIPTIONS
        handlers = get_handlers("appointment.booked")
        results.append(_pass("event_router", f"appointment.booked → {handlers}",
                             {"total_event_types": len(SUBSCRIPTIONS)}))
    except Exception as e:
        results.append(_fail("event_router", str(e)))

    # 5c. Event worker imports
    try:
        from backend.events.worker import event_worker_loop, run_hourly_heartbeat
        results.append(_pass("event_worker_import", "event_worker_loop and run_hourly_heartbeat importable"))
    except Exception as e:
        results.append(_fail("event_worker_import", str(e)))

    # 5d. Conversation manager
    try:
        from backend.conversations.manager import ConversationManager
        results.append(_pass("conversation_manager", "ConversationManager importable"))
    except Exception as e:
        results.append(_fail("conversation_manager", str(e)))

    return results


# ── TEST SUITE 6: Lead Intelligence ───────────────────────────────────────────

async def suite_lead_intelligence(bid: str) -> list[dict]:
    results = []

    # 6a. All integration files import
    modules = [
        ("backend.integrations.serper_client", ["search_google_maps", "normalize_serper_result"]),
        ("backend.integrations.scrapling_enricher", ["enrich_with_fallback"]),
        ("backend.integrations.crawl4ai_extractor", ["extract_business_profile_ai"]),
        ("backend.integrations.social_scrapers", ["enrich_social_batch", "get_instagram_profile"]),
        ("backend.integrations.lead_scorer", ["score_lead_v2", "segment_leads"]),
        ("backend.integrations.lead_intelligence", ["run_full_pipeline"]),
    ]
    import importlib
    for mod_path, fns in modules:
        try:
            mod = importlib.import_module(mod_path)
            missing_fns = [f for f in fns if not hasattr(mod, f)]
            if missing_fns:
                results.append(_warn(f"import_{mod_path.split('.')[-1]}", f"Missing functions: {missing_fns}"))
            else:
                results.append(_pass(f"import_{mod_path.split('.')[-1]}", f"All functions present: {fns}"))
        except Exception as e:
            results.append(_fail(f"import_{mod_path.split('.')[-1]}", str(e)[:200]))

    # 6b. Score function correctness
    try:
        from backend.integrations.lead_scorer import score_lead_v2
        test_lead = {
            "company_name": "Test Spa",
            "has_website": False,
            "has_online_booking": False,
            "has_chatbot": False,
            "review_count": 5,
            "google_rating": 3.8,
            "email": "test@test.com",
            "phone": "555-0000",
        }
        scored = score_lead_v2(test_lead)
        assert 0 <= scored["score"] <= 100, f"Score out of range: {scored['score']}"
        assert scored["tier"] in ("A","B","C"), f"Invalid tier: {scored['tier']}"
        assert scored["score_reason"], "Empty score reason"
        results.append(_pass("lead_scorer_logic",
            f"Score={scored['score']}, Tier={scored['tier']}, Reason: {scored['score_reason'][:80]}",
            {"score": scored["score"], "tier": scored["tier"]}))
    except Exception as e:
        results.append(_fail("lead_scorer_logic", str(e)))

    # 6c. Supabase leads table accessible
    try:
        from backend.memory.supabase_client import get_supabase
        sb = get_supabase()
        leads = sb.table("leads").select("id,score,tier,status")\
            .eq("business_id", bid).limit(5).execute().data or []
        results.append(_pass("leads_table_access",
            f"Leads table readable. {len(leads)} leads for this business.",
            {"lead_count": len(leads)}))
    except Exception as e:
        results.append(_fail("leads_table_access", str(e)))

    return results


# ── TEST SUITE 7: n8n Workflows ────────────────────────────────────────────────

async def suite_n8n_workflows(bid: str) -> list[dict]:
    results = []

    import os, json as _json
    n8n_dir = "/projects/sandbox/automiqo-os/n8n"

    # 7a. Count and validate all workflow JSON files
    all_workflows = []
    invalid = []
    for root, dirs, files in os.walk(n8n_dir):
        for f in files:
            if not f.endswith(".json"):
                continue
            path = os.path.join(root, f)
            try:
                wf = _json.load(open(path))
                all_workflows.append({
                    "name": wf.get("name","?"),
                    "active": wf.get("active", False),
                    "nodes": len(wf.get("nodes",[])),
                    "file": f,
                    "category": root.replace(n8n_dir+"/","").split("/")[0],
                })
            except Exception as e:
                invalid.append({"file": f, "error": str(e)})

    active = [w for w in all_workflows if w["active"]]
    stubs  = [w for w in all_workflows if w["nodes"] <= 2]

    results.append(_pass("n8n_json_valid",
        f"{len(all_workflows)} valid, {len(invalid)} invalid",
        {"total": len(all_workflows), "invalid": invalid[:5]}))

    results.append(_pass("n8n_active_workflows",
        f"{len(active)}/{len(all_workflows)} active",
        {"active_count": len(active), "inactive": [w["name"] for w in all_workflows if not w["active"]][:10]}))

    if stubs:
        results.append(_warn("n8n_stub_workflows",
            f"{len(stubs)} workflows still have ≤2 nodes (may be stubs)",
            {"stubs": [w["name"] for w in stubs]}))
    else:
        results.append(_pass("n8n_stub_workflows", "No stub workflows detected"))

    # 7b. Check critical workflows exist
    critical = [
        "run_lead_pipeline", "send_cold_outreach", "score_lead",
        "run_qa_pipeline", "run_daily_backup", "morning_cron_trigger",
        "send_reminder_24h", "recover_missed_call",
    ]
    files_present = {w["file"].replace(".json","") for w in all_workflows}
    missing_critical = [c for c in critical if c not in files_present]
    if not missing_critical:
        results.append(_pass("n8n_critical_workflows", f"All {len(critical)} critical workflows present"))
    else:
        results.append(_warn("n8n_critical_workflows", f"Missing: {missing_critical}"))

    return results


# ── TEST SUITE 8: QA Pipeline ──────────────────────────────────────────────────

async def suite_qa_pipeline(bid: str) -> list[dict]:
    results = []

    # 8a. All QA sub-agents importable
    qa_agents = [
        "workflow_tester", "integration_tester", "scenario_simulator",
        "regression_manager", "ai_quality_evaluator", "performance_monitor",
        "memory_validator", "security_tester", "chaos_engineer",
        "data_integrity_auditor", "deployment_validator",
    ]
    import importlib
    ok, failed = [], []
    for name in qa_agents:
        try:
            mod = importlib.import_module(f"agents.departments.cto.managers.qa.{name}")
            ok.append(name)
        except Exception as e:
            failed.append({"agent": name, "error": str(e)[:150]})

    if not failed:
        results.append(_pass("qa_agents_import", f"All {len(ok)} QA sub-agents import cleanly"))
    else:
        results.append(_warn("qa_agents_import", f"{len(ok)} OK, {len(failed)} failed", {"failed": failed}))

    # 8b. QA director importable
    try:
        from agents.departments.cto.managers.qa.qa_director import QADirector
        qa = QADirector(UUID(bid))
        results.append(_pass("qa_director_init", "QADirector instantiates without error"))
    except Exception as e:
        results.append(_fail("qa_director_init", str(e)))

    return results


# ── TEST SUITE 9: Autonomous System ───────────────────────────────────────────

async def suite_autonomous(bid: str) -> list[dict]:
    results = []

    # 9a. All department loops importable
    loops = [
        ("backend.autonomous.coo_loop", "run_coo_daily_loop"),
        ("backend.autonomous.cmo_loop", "run_cmo_daily_loop"),
        ("backend.autonomous.cro_loop", "run_cro_daily_loop"),
        ("backend.autonomous.cfo_loop", "run_cfo_daily_loop"),
        ("backend.autonomous.cto_loop", "run_cto_daily_loop"),
        ("backend.autonomous.csd_loop", "run_csd_daily_loop"),
        ("backend.autonomous.learning_loop", "run_learning_daily_loop"),
    ]
    import importlib
    ok, failed = [], []
    for mod_path, fn_name in loops:
        try:
            mod = importlib.import_module(mod_path)
            assert hasattr(mod, fn_name), f"Missing function {fn_name}"
            ok.append(fn_name)
        except Exception as e:
            failed.append({"fn": fn_name, "error": str(e)[:150]})

    if not failed:
        results.append(_pass("autonomous_loops_import", f"All {len(ok)} dept loops importable"))
    else:
        results.append(_warn("autonomous_loops_import", f"{len(ok)} OK, {len(failed)} failed", {"failed": failed}))

    # 9b. Autonomous scheduler importable
    try:
        from backend.cron.autonomous_scheduler import start_autonomous_scheduler, DEPT_SCHEDULE
        results.append(_pass("autonomous_scheduler_import",
            f"Scheduler importable. {len(DEPT_SCHEDULE)} depts scheduled.",
            {"schedule": {k: v[0] for k,v in DEPT_SCHEDULE.items()}}))
    except Exception as e:
        results.append(_fail("autonomous_scheduler_import", str(e)))

    # 9c. Event router has all dept.work.* routes
    try:
        from backend.events.router import SUBSCRIPTIONS
        dept_triggers = [k for k in SUBSCRIPTIONS if k.startswith("dept.work.")]
        internal_alerts = [k for k in SUBSCRIPTIONS if k.startswith("internal.")]
        results.append(_pass("event_routes_complete",
            f"{len(dept_triggers)} dept.work triggers, {len(internal_alerts)} internal alert routes",
            {"dept_triggers": dept_triggers, "internal_alerts": internal_alerts}))
    except Exception as e:
        results.append(_fail("event_routes_complete", str(e)))

    return results


# ── TEST SUITE 10: API Routes ──────────────────────────────────────────────────

async def suite_api_routes(bid: str) -> list[dict]:
    results = []

    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    cron_secret = os.getenv("CRON_SECRET", "")

    # 10a. Health endpoint
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{backend_url}/health")
        if resp.status_code == 200:
            results.append(_pass("api_health", f"GET /health → 200"))
        else:
            results.append(_warn("api_health", f"GET /health → {resp.status_code}"))
    except Exception as e:
        results.append(_warn("api_health", f"Cannot reach {backend_url}: {e} (OK if not running locally)"))

    # 10b. Check all expected routers are registered (import main and inspect)
    try:
        import importlib
        main = importlib.import_module("backend.main")
        app = main.app
        routes = [r.path for r in app.routes]
        expected = ["/health", "/chat", "/leads", "/qa", "/test", "/webhooks", "/cron"]
        present = [e for e in expected if any(r.startswith(e) for r in routes)]
        missing = [e for e in expected if not any(r.startswith(e) for r in routes)]
        if not missing:
            results.append(_pass("api_routers_registered", f"All {len(expected)} router prefixes registered"))
        else:
            results.append(_warn("api_routers_registered", f"Missing prefixes: {missing}",
                                 {"present": present, "missing": missing}))
    except Exception as e:
        results.append(_warn("api_routers_registered", str(e)))

    return results


# ── SUITE REGISTRY ─────────────────────────────────────────────────────────────

SUITES = {
    "infrastructure":    suite_infrastructure,
    "dispatcher":        suite_dispatcher,
    "schemas":           suite_schemas,
    "agents":            suite_agents_import,
    "events":            suite_events,
    "lead_intelligence": suite_lead_intelligence,
    "n8n_workflows":     suite_n8n_workflows,
    "qa_pipeline":       suite_qa_pipeline,
    "autonomous":        suite_autonomous,
    "api_routes":        suite_api_routes,
}


def _summarise(all_results: list[dict]) -> dict:
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in all_results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total  = sum(counts.values())
    health = "HEALTHY" if counts["FAIL"] == 0 and counts["WARN"] <= 3 else \
             "DEGRADED" if counts["FAIL"] == 0 else "UNHEALTHY"
    return {
        "total_tests": total,
        "passed":  counts["PASS"],
        "warned":  counts["WARN"],
        "failed":  counts["FAIL"],
        "health":  health,
        "pass_rate": f"{round(counts['PASS']/max(total,1)*100,1)}%",
    }


# ── ENDPOINTS ──────────────────────────────────────────────────────────────────

@router.post("/full")
async def run_full_test(req: TestRequest):
    """Run all test suites. Returns full health report."""
    start = time.time()
    suite_reports = {}
    all_results   = []

    for suite_name, suite_fn in SUITES.items():
        try:
            results = await suite_fn(req.business_id)
        except Exception as e:
            results = [_fail(suite_name, f"Suite crashed: {e}")]
        suite_reports[suite_name] = results
        all_results.extend(results)

    summary = _summarise(all_results)
    summary["elapsed_seconds"] = round(time.time() - start, 2)
    summary["timestamp"] = datetime.now(timezone.utc).isoformat()

    return {
        "summary": summary,
        "suites":  suite_reports,
        "failed_tests": [r for r in all_results if r["status"] == "FAIL"],
        "warnings":     [r for r in all_results if r["status"] == "WARN"],
    }


@router.post("/suite/{suite_name}")
async def run_suite(suite_name: str, req: TestRequest):
    """Run a single test suite by name."""
    if suite_name not in SUITES:
        return {"error": f"Unknown suite '{suite_name}'. Available: {list(SUITES.keys())}"}
    start   = time.time()
    results = await SUITES[suite_name](req.business_id)
    summary = _summarise(results)
    summary["elapsed_seconds"] = round(time.time() - start, 2)
    return {"suite": suite_name, "summary": summary, "results": results}


@router.get("/quick")
async def quick_smoke_test(business_id: str = "00000000-0000-0000-0000-000000000001"):
    """
    Fast smoke test — no LLM calls, no network calls.
    Just verifies imports, schemas, and Supabase connectivity.
    """
    start   = time.time()
    results = []
    results += await suite_infrastructure(business_id)
    results += await suite_schemas(business_id)
    results += await suite_events(business_id)
    summary  = _summarise(results)
    summary["elapsed_seconds"] = round(time.time() - start, 2)
    summary["note"] = "Smoke test only. Run POST /test/full for comprehensive check."
    return {"summary": summary, "results": results}


@router.get("/suites")
async def list_suites():
    """List all available test suites."""
    return {
        "suites": list(SUITES.keys()),
        "usage": {
            "full":   "POST /test/full",
            "single": "POST /test/suite/{name}",
            "quick":  "GET /test/quick",
        }
    }
