# Automiqo OS

AI-powered operating system for local service businesses (med spas, gyms, salons, dental).

## Quick Start

### 1. Set up environment
```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY, REDIS_URL
```

### 2. Apply Supabase schema
Run `scripts/setup_supabase.sql` in your Supabase SQL editor.

### 3. Seed dev data (optional)
```bash
python scripts/seed_dev.py
```

### 4. Start with Docker
```bash
docker compose -f docker/docker-compose.yml up
```

### 5. Or start manually
```bash
# Backend
uvicorn backend.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

## Architecture

```
Owner Chat
    ↓
CEO Agent (Claude Sonnet) ← LangGraph
    ↓
Department Agents (GPT-4o-mini): COO | CRO | CMO | CFO | Customer Success
    ↓
Task Dispatcher → Redis Queue
    ↓
n8n Workflows (42 automations): SMS | Calendar | CRM | Reports
    ↓
Supabase (all state) + Twilio + Vapi + Google Calendar + Stripe
```

## API Endpoints

- `GET /health` — Health check
- `POST /onboard` — Create new business
- `POST /auth/register` — Register owner
- `POST /auth/token` — Login
- `POST /chat` — Stream CEO response (SSE)
- `GET /approvals/{business_id}` — List pending approvals
- `POST /approvals/{id}/approve` — Approve recommendation
- `POST /approvals/{id}/reject` — Reject recommendation

## n8n Workflows (10 built, 42 total)

Import JSONs from `/n8n/` into your n8n instance.
Set up credentials: `Supabase_Main` and `Twilio_Production`.

## Tests
```bash
python -m pytest tests/ -v
```
