import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from backend.api.health import router as health_router
from backend.api.onboarding import router as onboarding_router
from backend.api.auth import router as auth_router
from backend.api.approvals import router as approvals_router
from backend.api.chat import router as chat_router
from backend.api.reports import router as reports_router
from backend.api.specialists import router as specialists_router
from backend.api.memory_api import router as memory_router
from backend.api.leads_api import router as leads_router
from backend.api.qa_api import router as qa_router
from backend.api.system_test_api import router as test_router
from backend.api.growth_api import router as growth_router
from backend.api.engines_api import router as engines_router
from backend.api.business_modules_api import router as business_modules_router
from backend.api.webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.dispatcher.queue import worker_loop
    from backend.events.worker import event_worker_loop
    from backend.cron.autonomous_scheduler import start_autonomous_scheduler

    task_worker = asyncio.create_task(worker_loop())
    event_worker = asyncio.create_task(event_worker_loop())
    scheduler_tasks = await start_autonomous_scheduler()

    print(f"✅ Task worker + Event worker + {len(scheduler_tasks)} scheduler tasks started")
    yield

    task_worker.cancel()
    event_worker.cancel()
    for t in scheduler_tasks:
        t.cancel()
    print("All workers stopped")


app = FastAPI(title="Automiqo OS", version="1.0.0", lifespan=lifespan)

_env = os.getenv("APP_ENV", "development")
_origins = [os.getenv("FRONTEND_URL", "http://localhost:3000")]
if _env == "development":
    _origins += ["http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(onboarding_router)
app.include_router(auth_router)
app.include_router(approvals_router)
app.include_router(chat_router)
app.include_router(reports_router)
app.include_router(specialists_router)
app.include_router(memory_router)
app.include_router(leads_router)
app.include_router(qa_router)
app.include_router(test_router)
app.include_router(growth_router)
app.include_router(engines_router)
app.include_router(business_modules_router)
app.include_router(webhooks_router)


def _check_cron_secret(x_cron_secret: str = Header(None)):
    secret = os.getenv("CRON_SECRET", "")
    if secret and x_cron_secret != secret:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/cron/morning-briefing")
async def cron_morning_briefing(x_cron_secret: str = Header(None)):
    """Called by n8n at 7am daily."""
    _check_cron_secret(x_cron_secret)
    from backend.cron.morning_briefing import run_morning_briefing
    asyncio.create_task(run_morning_briefing())
    return {"status": "queued"}


@app.post("/cron/nightly-learning")
async def cron_nightly_learning(x_cron_secret: str = Header(None)):
    """Called at 10pm daily."""
    _check_cron_secret(x_cron_secret)
    from backend.cron.nightly_learning import run_nightly_learning
    asyncio.create_task(run_nightly_learning())
    return {"status": "queued"}


@app.post("/cron/department-work")
async def cron_department_work(x_cron_secret: str = Header(None), department: str = "", business_id: str = ""):
    """
    Manually trigger a department's autonomous work loop.
    department: coo|cmo|cro|cfo|cto|csd|learning|all
    Used by n8n cron workflows or for manual override.
    """
    _check_cron_secret(x_cron_secret)
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()

    # Get business IDs
    if business_id:
        bids = [business_id]
    else:
        bids = [str(r["id"]) for r in (sb.table("businesses").select("id").eq("active", True).execute().data or [])]

    if not bids:
        return {"status": "no_active_businesses"}

    loop_map = {
        "coo":      "backend.autonomous.coo_loop.run_coo_daily_loop",
        "cmo":      "backend.autonomous.cmo_loop.run_cmo_daily_loop",
        "cro":      "backend.autonomous.cro_loop.run_cro_daily_loop",
        "cfo":      "backend.autonomous.cfo_loop.run_cfo_daily_loop",
        "cto":      "backend.autonomous.cto_loop.run_cto_daily_loop",
        "csd":      "backend.autonomous.csd_loop.run_csd_daily_loop",
        "learning": "backend.autonomous.learning_loop.run_learning_daily_loop",
    }

    depts = list(loop_map.keys()) if department == "all" or not department else [department]
    queued = []

    for dept in depts:
        fn_path = loop_map.get(dept)
        if not fn_path:
            continue
        for bid in bids:
            async def _run(d=dept, fp=fn_path, b=bid):
                import importlib
                module_path, fn_name = fp.rsplit(".", 1)
                mod = importlib.import_module(module_path)
                return await getattr(mod, fn_name)(b)
            asyncio.create_task(_run())
            queued.append(f"{dept}:{bid[:8]}")

    return {"status": "queued", "tasks": queued}


@app.post("/cron/heartbeat")
async def cron_heartbeat(x_cron_secret: str = Header(None)):
    """Manually trigger hourly heartbeat for all businesses."""
    _check_cron_secret(x_cron_secret)
    from backend.events.worker import run_hourly_heartbeat
    from backend.memory.supabase_client import get_supabase
    sb = get_supabase()
    bids = [str(r["id"]) for r in (sb.table("businesses").select("id").eq("active", True).execute().data or [])]
    for bid in bids:
        asyncio.create_task(run_hourly_heartbeat(bid))
    return {"status": "queued", "businesses": len(bids)}
