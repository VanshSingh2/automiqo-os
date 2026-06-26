import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from backend.api.health import router as health_router
from backend.api.onboarding import router as onboarding_router
from backend.api.auth import router as auth_router
from backend.api.approvals import router as approvals_router

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
