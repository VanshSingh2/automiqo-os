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


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.dispatcher.queue import worker_loop
    worker_task = asyncio.create_task(worker_loop())
    print("✅ Redis worker started")
    yield
    worker_task.cancel()
    print("Redis worker stopped")


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
