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
CEO Agent (GPT-4.1 by default — configurable via CEO_MODEL) ← LangGraph
    ↓
Department Agents (GPT-4o-mini): COO | CRO | CMO | CFO | CTO | Customer Success | Learning
    ↓
Managers (32 total) + Manager autonomy pulses
    ↓
Task Dispatcher → Redis Queue
    ↓
n8n Workflows (100+ automations): SMS | Calendar | CRM | Reports | Campaigns
    ↓
Supabase (all state, pgvector memory) + Twilio/Telnyx + Vapi + Cal.com + Stripe
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

## n8n Workflows (100+ automations)

Import JSONs from `/n8n/` into your n8n instance.
Set up credentials: `Supabase_Main` and `Twilio_Production`.

## Deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for a step-by-step VPS guide, and
**[docs/CODE_REVIEW_AND_ROADMAP.md](docs/CODE_REVIEW_AND_ROADMAP.md)** for the
production-hardening checklist.

## Tests
```bash
python -m pytest tests/ -v
```
