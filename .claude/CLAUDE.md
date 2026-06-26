# Automiqo OS — Claude Code Context

## Project
AI operating system for local service businesses (med spas, gyms, salons, dental).
Target market: NJ. Path: C:\Users\2477204\automiqo-os

## Stack
- Frontend: Next.js 14, Tailwind CSS, shadcn/ui (in /frontend)
- Backend: FastAPI, Python 3.12 (in /backend) — run with: uvicorn backend.main:app --reload
- Agents: LangGraph (in /agents) — all AI reasoning here
- Database: Supabase (PostgreSQL + pgvector)
- Queue: Redis — REDIS_URL in .env
- Workers: n8n (in /n8n) — all external API calls (SMS, calendar, payments)
- Containers: Docker + Docker Compose (in /docker)

## Hard Rules
1. EVERY Supabase table has business_id UUID — multi-tenant only
2. Agents NEVER call Twilio, Vapi, Google Calendar, or Stripe directly
   Always dispatch via: from backend.dispatcher.dispatcher import dispatch
3. No hardcoded credentials — os.getenv() only
4. CEO agent uses claude-sonnet-4-6. All others use gpt-4o-mini
5. Prompts in /prompts/*.md — never hardcoded in Python
6. All Pydantic models in /shared/schemas.py — import from there

## Architecture
- LangGraph agents = THINKING (planning, delegating)
- n8n workflows = DOING (API calls, SMS, calendar)
- Supabase = SHARED MEMORY
- Redis = TASK QUEUE

## n8n Webhook Contract
Input:  {"business_id": "uuid", "task_id": "uuid", "parameters": {}}
Output: {"success": true/false, "data": {}, "message": "human readable"}

## Dev Commands
```bash
# Backend
cd C:\Users\2477204\automiqo-os
uvicorn backend.main:app --reload --port 8000

# Frontend  
cd frontend && npm run dev

# Docker (full stack)
docker compose -f docker/docker-compose.yml up

# Seed dev data
python scripts/seed_dev.py

# Tests
python -m pytest tests/ -v
```

## Files Built (Sprint 1-6)
- backend/main.py — FastAPI app
- backend/api/{health,auth,chat,onboarding,approvals}.py — endpoints
- backend/memory/{supabase_client,episodic,customer,company,reflection}.py
- backend/dispatcher/{dispatcher,queue,retry}.py
- backend/auth/jwt.py
- agents/base_agent.py
- agents/executive/ceo/{agent,tools}.py
- agents/departments/{coo,cro,customer_success}/agent.py
- shared/schemas.py — ALL Pydantic models
- scripts/setup_supabase.sql
- scripts/seed_dev.py
- n8n/ — 10 priority workflow JSONs
