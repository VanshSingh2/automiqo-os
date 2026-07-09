# Automiqo OS

An autonomous "AI company" for local service businesses. A CEO agent leads
seven executive departments (COO, CMO, CRO, CFO, CTO, Customer Success,
Learning), each with its own managers — 32 in total — that run on schedules,
react to real business events, consult expert specialists, and either act
autonomously or escalate to the owner for approval.

This is the single source of truth for **running Automiqo OS on a VPS**.

---

## 1. Architecture at a glance

```
                         ┌───────────────────────────────┐
   Owner (browser) ──────▶  Next.js frontend (:3000)      │
                         │  /api/proxy  ──────────────┐   │
                         └────────────────────────────┼───┘
                                                       ▼
 Telnyx / VAPI / Cal.com / n8n ──/webhooks──▶  FastAPI backend (:8000)
                                                       │
        ┌──────────────────────────────┬──────────────┼───────────────┐
        ▼                              ▼               ▼               ▼
   Supabase (Postgres            Redis queue      Autonomous       Specialist
   + pgvector + Mem0)            (:6379)          schedulers       library
        │                              │          (dept loops,     (agency-agents
   business data,                 tasks/events    manager pulses,  submodule)
   memory, KPIs                                   CEO standup)
                                       │
                                       ▼
                                n8n (:5678) — 104 workflows fire real
                                actions (SMS, email, bookings, calls…)
```

- **Backend** (`backend/`): FastAPI app + agents + autonomous schedulers, all
  started from `backend/main.py`.
- **Frontend** (`frontend/`): Next.js 14 dashboard. All API calls go through a
  server-side proxy (`app/api/proxy`) to `BACKEND_URL`.
- **n8n** (`n8n/`): 104 workflow JSONs that perform the real-world actions.
- **Specialist library** (`specialist_library/`): the `agency-agents` repo,
  included as a **git submodule** — agents consult these experts.


---

## 2. Prerequisites

On the VPS (Ubuntu 22.04+ recommended, 2 vCPU / 4 GB RAM minimum):

- Docker Engine + Docker Compose plugin
- Git
- A domain name pointing at the VPS (for webhooks + TLS)

External accounts (fill their keys into `.env`, see §4):

| Service    | Used for                          | Required           |
|------------|-----------------------------------|--------------------|
| OpenAI     | all agent + specialist reasoning  | **yes**            |
| Supabase   | database, vector memory           | **yes**            |
| Telnyx     | SMS send/receive                  | yes (for SMS)      |
| VAPI       | inbound/outbound voice calls      | yes (for calls)    |
| Cal.com    | appointment booking               | yes (for booking)  |
| Resend     | transactional email               | yes (for email)    |
| Serper.dev | lead discovery / scraping         | optional           |
| Stripe     | payments                          | optional           |
| Anthropic / NVIDIA | alternative LLM providers | optional           |

---

## 3. Get the code (submodule matters!)

The specialist library is a **git submodule**. A plain `git clone` leaves it
empty and every specialist consultation silently returns "not available".

```bash
# Clone WITH submodules
git clone --recurse-submodules https://github.com/VanshSingh2/automiqo-os.git
cd automiqo-os

# If you already cloned without --recurse-submodules:
git submodule update --init --recursive
```

Verify it worked:

```bash
ls specialist_library/finance/    # should list *.md files, not be empty
```


---

## 4. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in every key marked required in `.env.example`. Critical notes:

- **`JWT_SECRET`** and **`CRON_SECRET`**: generate with `openssl rand -hex 32`.
- **`REQUIRE_AUTH=true`** for production (enforces auth + per-tenant ownership).
- **`REDIS_URL`** and **`N8N_WEBHOOK_BASE_URL`**: leave as the compose defaults
  (`redis://redis:6379`, `http://n8n:5678/webhook`) — the compose file already
  overrides these to the correct in-network service names.
- **`BACKEND_URL`** (frontend): stays `http://backend:8000` inside compose.
- **`SUPABASE_DB_URL`**: the direct Postgres connection string (enables Mem0
  semantic memory; without it, memory falls back to in-app pgvector).

---

## 5. Set up the database (Supabase)

1. Create a project at [supabase.com](https://supabase.com).
2. Open **SQL Editor** and paste the entire contents of
   **`scripts/setup_supabase_master.sql`**, then Run. It is idempotent (safe to
   re-run) and creates every table, view, index, RLS policy, and the pgvector
   functions the code needs.
3. Run the verification queries at the bottom of that file to confirm all
   tables exist.
4. Copy your **Project URL**, **service_role key**, and **anon key** from
   Settings → API into `.env` (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
   `SUPABASE_ANON_KEY`), and the DB connection string into `SUPABASE_DB_URL`.

> The master schema already includes the previously-missing tables
> (`agent_messages`, `applicants`, `expenses`, `reviews`, `shifts`,
> `disagreements`) and the `staff.certifications` column.


---

## 6. Build and run

```bash
# From the repo root
docker compose -f docker/docker-compose.yml up -d --build
```

This starts five services: `backend`, `frontend`, `redis`, `n8n`, `nginx`.

Check everything is healthy:

```bash
docker compose -f docker/docker-compose.yml ps
curl http://localhost:8000/health          # {"status":"ok",...}
curl http://localhost/health               # via nginx
```

- Dashboard: `http://<your-domain>/`
- Backend API (direct): `http://<vps-ip>:8000`
- n8n editor: `http://<vps-ip>:5678` (user `admin`, password from compose — change it)

### Production variant

`docker/docker-compose.prod.yml` uses pre-built images and adds TLS volumes.
Build/tag images first (`automiqo-backend:latest`, `automiqo-frontend:latest`),
put your certs under `/etc/letsencrypt`, then:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

---

## 7. Deploy the n8n workflows

The 104 workflow JSONs live in `n8n/`. After n8n is up:

1. In the n8n editor, create an API key (Settings → API).
2. Put it in `.env` as `N8N_API_KEY` and set `N8N_WEBHOOK_BASE_URL` to your n8n
   URL (e.g. `http://<vps-ip>:5678/webhook`).
3. Import + activate all workflows:

```bash
python scripts/deploy_n8n_workflows.py
python scripts/activate_workflows.py
```

Every workflow the backend dispatches has a matching JSON here — verified: all
33 dispatched workflow names resolve to a file.


---

## 8. Wire up external webhooks

Point each provider's webhook at your domain (routed by nginx to the backend):

| Provider | Webhook URL                                   |
|----------|-----------------------------------------------|
| Telnyx   | `https://<your-domain>/webhooks/sms/inbound`  |
| VAPI     | `https://<your-domain>/webhooks/vapi/call`    |
| Cal.com  | `https://<your-domain>/webhooks/appointment`  |

> **Security note:** these endpoints do not yet verify provider signatures
> (see §11). Add signature verification before going live with real traffic.

---

## 9. Onboard your first business

The UI loads the tenant in `NEXT_PUBLIC_BUSINESS_ID`. Create a business via the
onboarding endpoint (or the dashboard onboarding page):

```bash
curl -X POST http://localhost:8000/onboard \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Med Spa","industry":"med_spa","config":{"city":"Austin","state":"TX","booking_url":"https://cal.com/acme"}}'
```

Use the returned business `id` as `NEXT_PUBLIC_BUSINESS_ID` in `.env`, then
restart the frontend.

---

## 10. Operating it

```bash
# Logs
docker compose -f docker/docker-compose.yml logs -f backend
docker compose -f docker/docker-compose.yml logs -f n8n

# Restart one service after an .env change
docker compose -f docker/docker-compose.yml up -d backend

# The autonomous engine runs inside the backend process:
#  - department loops fire on their scheduled hour (DEPT_SCHEDULE_*)
#  - 32 managers pulse every MANAGER_PULSE_INTERVAL_MINUTES
#  - urgent scanner every URGENT_SCAN_INTERVAL_MINUTES
#  - CEO standup daily; heartbeat hourly
# Set AUTONOMOUS_MODE=false to run the API only (no self-driving).
```

Cost control: `DAILY_AI_SPEND_CAP_USD` caps AI spend per business/day, and
`MANAGER_PULSE_INTERVAL_MINUTES` trades autonomy frequency for token cost.


---

## 11. Production-readiness checklist

Already in place:
- [x] JWT auth + per-tenant ownership guard (enable with `REQUIRE_AUTH=true`)
- [x] Rate limiting + daily AI spend cap on cost-bearing endpoints
- [x] LLM retry/backoff wrapper
- [x] Prompt-injection sanitizer on untrusted event content
- [x] Human approval gate for high-risk actions
- [x] Docker healthchecks + dependency ordering
- [x] Complete DB schema (all code-referenced tables/columns present)
- [x] All 104 n8n workflows valid; specialist submodule wired

Before real/paying traffic — **do these**:
- [ ] **Webhook signature verification** (Telnyx / VAPI / Cal.com) — endpoints
      are currently open.
- [ ] **Multi-tenant webhook routing** — inbound SMS/calls currently resolve to
      the first business (`webhooks.py`); match by phone number.
- [ ] **Ownership check on body/query params** — the guard reads the path param
      only; `/chat` and similar take `business_id` in the body.
- [ ] **Route CEO direct-dispatch through the approval gate** (`ceo/tools.py`).
- [ ] **Dispatch idempotency** — add a dedup key so retries don't double-send.
- [ ] **Structured logging** — replace `print()` with JSON logs + a `trace_id`.
- [ ] Change the default n8n basic-auth password.

---

## 12. How close is this to a human-run organization?

**Structurally, very close; operationally, ~70–80% of the way.** What already
maps to a real company:

- **Org chart & delegation:** CEO → 7 department heads → 32 managers, each with
  a real prompt, schedule, and scope. Departments talk to each other via an
  event bus and a team chat, and can raise reasoned *disagreements*.
- **Proactivity:** agents act on a clock and on events, not just when asked —
  the hallmark of employees vs. tools.
- **Expertise on tap:** managers consult 28 specialist experts before deciding.
- **Judgement + guardrails:** risky moves are queued for owner approval; memory
  (Mem0/pgvector) lets agents learn from past outcomes.

What a human org still has that this doesn't yet:

- **Reliable senses:** webhooks are unauthenticated and single-tenant, so the
  "ears" (inbound SMS/calls) are fragile — the top gap to close.
- **Accountability trail:** no structured logs/metrics per employee, so you
  can't yet audit *why* an agent did something or track its cost/quality.
- **Safe hands:** the CEO can bypass the approval gate, and actions aren't
  idempotent — a human wouldn't send the same campaign twice.
- **Real cross-checking:** only shallow tests today; no agent-output evaluation,
  so quality drift goes unnoticed.

Close those four (senses, accountability, safe hands, cross-checking) and you
move from "impressive autonomous demo" to "trustworthy autonomous org." The
§11 checklist is exactly that path.
