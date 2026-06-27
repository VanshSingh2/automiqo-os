import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from backend.api.health import router as health_router
from backend.api.onboarding import router as onboarding_router
from backend.api.auth import router as auth_router
from backend.api.approvals import router as approvals_router
from backend.api.chat import router as chat_router
from backend.api.reports import router as reports_router

app = FastAPI(title="Automiqo OS", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:3000"), "*"],
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


@app.post("/cron/morning-briefing")
async def cron_morning_briefing():
    """Called by n8n at 7am daily."""
    import asyncio
    from backend.cron.morning_briefing import run_morning_briefing
    asyncio.create_task(run_morning_briefing())
    return {"status": "queued"}


@app.post("/cron/nightly-learning")
async def cron_nightly_learning():
    """Called at 10pm daily."""
    import asyncio
    from backend.cron.nightly_learning import run_nightly_learning
    asyncio.create_task(run_nightly_learning())
    return {"status": "queued"}
