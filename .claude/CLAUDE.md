# Automiqo OS — Claude Code Context

## Project
AI operating system for local service businesses (med spas, gyms, salons, dental).
Target market: NJ.

## Stack
- Frontend: Next.js 14, Tailwind CSS, shadcn/ui (in /frontend)
- Backend: FastAPI, Python 3.12 (in /backend) — run with: uvicorn backend.main:app --reload
- Agents: LangGraph (in /agents) — all AI reasoning here
- Database: Supabase (PostgreSQL + pgvector)
- Queue: Redis — REDIS_URL in .env
- Workers: n8n (in /n8n) — all external API calls (SMS, payments, booking)
- Calendar: Cal.com API for booking management
- Containers: Docker + Docker Compose (in /docker)

## Hard Rules
1. EVERY Supabase table has business_id UUID — multi-tenant only
2. Agents NEVER call Twilio, Vapi, Google Calendar, or Stripe directly
   Always dispatch via: from backend.dispatcher.dispatcher import dispatch
3. No hardcoded credentials — os.getenv() only
4. CEO agent uses gpt-4.1. All others use gpt-4o-mini
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
uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev
docker compose -f docker/docker-compose.yml up
python scripts/seed_dev.py
python -m pytest tests/ -v
```

---

## Lead Intelligence Engine

### Architecture
5-stage pipeline: Serper.dev (Discovery) → Scrapling (Enrichment) → Crawl4AI fallback → Social → Scorer

### Files
- backend/integrations/serper_client.py — Google Maps API (search_google_maps_paginated, normalize_serper_result)
- backend/integrations/scrapling_enricher.py — enrich_with_fallback(): Scrapling → Crawl4AI
- backend/integrations/crawl4ai_extractor.py — AI extraction fallback (~$0.0002/site)
- backend/integrations/social_scrapers.py — Instagram, Facebook, LinkedIn (best-effort)
- backend/integrations/lead_scorer.py — score_lead_v2() 0-100 with social signals, segment_leads()
- backend/integrations/lead_intelligence.py — run_full_pipeline() orchestrator
- backend/api/leads_api.py — POST /leads/pipeline/run, /leads/pipeline/discover-only, GET /leads/{bid}/intelligence-summary
- n8n/marketing/run_lead_pipeline.json — n8n trigger
- scripts/migrations/001_lead_intelligence_social.sql — schema additions for leads table

### Scraping Decision Tree
1. Business websites → Scrapling (Fetcher → StealthyFetcher → DynamicFetcher → httpx fallback)
2. Scrapling fails → Crawl4AI (AI extraction, ~$0.0002/site)
3. Instagram → Hidden web_profile_info endpoint (no auth, breaks every 2-4 weeks)
4. Facebook → oEmbed API + httpx fallback
5. LinkedIn → Serper search for URL only (NEVER scrape directly)

### Scoring Logic (score_lead_v2)
- No online booking: +25 | No website: +20 | No chatbot: +15 | <50 reviews: +15
- Rating <4.0: +10 | Has email: +10 | Has phone: +5
- Basic booking (calendly/wix/square): +15 | Advanced (mindbody/vagaro): -10
- No Instagram: +10 | <500 followers: +8 | Email in bio: +8
- No Facebook: +5 | No LinkedIn: +5
- Tier A: >=75, B: 50-74, C: <50

### Scraping Setup (one-time per deployment)
```bash
pip install "scrapling[fetchers]" crawl4ai httpx
scrapling install
python -m crawl4ai.setup
```

### DO NOT
- Scrape LinkedIn — Serper search for URL only
- >3 concurrent social scrapes
- DynamicFetcher on >2 sites simultaneously
- Store raw HTML in Supabase

---

## QA & Reliability Department

### Architecture
QA Director → 11 sub-agents in 3 parallel phases

### Phases
- Phase 1 (Core): WorkflowTester, IntegrationTester, ScenarioSimulator, RegressionManager
- Phase 2 (Quality): AIQualityEvaluator, PerformanceMonitor, MemoryValidator
- Phase 3 (Reliability): SecurityTester, ChaosEngineer, DataIntegrityAuditor, DeploymentValidator

### Files
- agents/departments/cto/managers/qa/qa_director.py — orchestrates all 11 sub-agents
- agents/departments/cto/managers/qa/{workflow_tester,integration_tester,scenario_simulator,regression_manager}.py
- agents/departments/cto/managers/qa/{ai_quality_evaluator,performance_monitor,memory_validator}.py
- agents/departments/cto/managers/qa/{security_tester,chaos_engineer,data_integrity_auditor,deployment_validator}.py
- backend/api/qa_api.py — POST /qa/run, /qa/workflow-test, /qa/integration-test, /qa/security-test, /qa/deployment-check
- n8n/platform/run_qa_pipeline.json — n8n trigger
- prompts/cto/qa_director.md — QA Director prompt

### Decision Rules
- BLOCKED: critical failure, failure rate >20%, missing env vars, security vulnerability
- WARN: non-critical issues, performance degradation
- PASS: all checks pass

---

## Files Built (Sprint 1-8)
- backend/main.py — FastAPI app + cron endpoints
- backend/api/{health,auth,chat,onboarding,approvals,reports,specialists,memory_api,leads_api,qa_api}.py
- backend/memory/{supabase_client,episodic,customer,company,reflection,semantic}.py
- backend/dispatcher/{dispatcher,queue,retry}.py
- backend/integrations/{lead_discovery,lead_enricher,lead_pipeline,lead_scorer}.py — legacy (still works)
- backend/integrations/{serper_client,scrapling_enricher,crawl4ai_extractor,social_scrapers,lead_intelligence}.py — v2
- backend/auth/jwt.py
- backend/cron/{morning_briefing,nightly_learning}.py
- agents/base_agent.py
- agents/executive/ceo/{agent,tools}.py
- agents/executive/chief_of_staff/agent.py
- agents/departments/{coo,cro,cfo,cmo,cto,customer_success,learning}/agent.py
- agents/departments/cmo/managers/lead_manager.py — Lead Intelligence Manager (v2)
- agents/departments/cto/managers/qa/ — Full QA Department (12 agents)
- agents/cross_cutting/ — notification, audit, task managers
- shared/schemas.py — ALL Pydantic models
- scripts/setup_supabase.sql
- scripts/migrations/001_lead_intelligence_social.sql
- scripts/seed_dev.py
- n8n/ — 87 total workflow JSONs
