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
                                n8n (:5678) — 103 workflows fire real
                                actions (SMS, email, bookings, calls…)
```

- **Backend** (`backend/`): FastAPI app + agents + autonomous schedulers, all
  started from `backend/main.py`.
- **Frontend** (`frontend/`): Next.js 14 dashboard. All API calls go through a
  server-side proxy (`app/api/proxy`) to `BACKEND_URL`.
- **n8n** (`n8n/`): 103 workflow JSONs that perform the real-world actions.
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

The 103 workflow JSONs live in `n8n/`. After n8n is up:

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
> (see §12). Add signature verification before going live with real traffic.

---

## 9. Connecting Slack (talk to your AI team from Slack)

You can chat with the CEO, any of the 7 department heads, or any of the 32
managers straight from Slack — they reply *in character* right in the channel.

> **Creating Slack channels is not enough.** Channels are just rooms; they
> carry no credentials. To let the backend read messages and post replies you
> must create a **Slack App**, which gives you the two secrets the backend
> needs:
>
> - **`SLACK_BOT_TOKEN`** (`xoxb-…`) — lets the bot *post* replies.
> - **`SLACK_SIGNING_SECRET`** — lets the backend *verify* that inbound events
>   really came from Slack.

### What the backend already does

- **Endpoint:** `POST /webhooks/slack/events` (in `backend/api/slack.py`),
  registered **without auth** like the other webhook routers — Slack
  authenticates itself by signing each request, which the endpoint verifies
  against `SLACK_SIGNING_SECRET` (with a 5-minute replay guard). It also
  auto-answers Slack's one-time URL-verification handshake and acks fast.
- **Routing — how a message finds the right team member:**
  1. **Explicit prefix** — an `@name` or `name:` prefix matching any member,
     department, or manager (e.g. `@cfo what's our runway?`,
     `@Inventory Manager reorder gloves`, `cmo: draft a promo`). Matching is
     case-insensitive against member names, keys, and department-head names.
  2. **Per-channel map** — `businesses.config.slack_agent_map`, a
     `{channel_id: agent_key}` mapping, so a whole channel routes to one agent.
  3. **Default** — the **CEO**, if nothing above matches.
- The chosen **`PersonaChatAgent`** answers in character, and the reply is
  posted back to the same channel/thread. Bot messages and Slack retries are
  ignored to prevent reply loops and duplicates.

### Step-by-step setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**
   → **From scratch** → name it and pick your workspace.
2. **Basic Information** → **App Credentials** → copy the **Signing Secret**
   into `SLACK_SIGNING_SECRET`.
3. **OAuth & Permissions** → **Bot Token Scopes**, add:
   - `chat:write`, `app_mentions:read`, `channels:history`, `channels:read`
   - (add `groups:history` for private channels; `im:history` + `im:write`
     for DMs)

   Then **Install to Workspace** → copy the **Bot User OAuth Token**
   (`xoxb-…`) into `SLACK_BOT_TOKEN`.
4. **Event Subscriptions** → **Enable Events** → set the **Request URL** to
   `https://<your-domain>/webhooks/slack/events` (the endpoint auto-answers
   Slack's verification handshake, so it should turn green). Under **Subscribe
   to bot events**, add: `app_mention` and `message.channels`.
5. **Invite the bot to your channels** — in Slack, run `/invite @YourApp` in
   `#automiqo-ceo` and `#automiqo-team`.
6. Put `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` in `.env` and restart the
   backend.

### Mapping your channels

Get each channel's ID (in Slack: **View channel details** → the ID is at the
bottom of the panel), then set `businesses.config.slack_agent_map`, e.g.:

```json
{
  "slack_agent_map": {
    "C0ABC111CEO": "ceo",
    "C0ABC222TEAM": "ceo"
  }
}
```

Here the `#automiqo-ceo` channel id → `"ceo"` and the `#automiqo-team` channel
id → `"ceo"`. In `#automiqo-team`, `@`-mention a specific manager to reach
them (e.g. `@Inventory Manager …`); with no mention it falls back to the CEO.

### Gotchas

- **Slack must reach the backend over public HTTPS.** For local testing, run a
  tunnel (e.g. `ngrok` or `cloudflared`) and use the tunnel's HTTPS URL as the
  Request URL — Slack will not call `localhost`.
- **Pick ONE Slack path.** There are two ways messages can flow: this backend
  endpoint **and** the n8n `slack_ceo_chat` / `slack_team_chat` workflows.
  Enabling both causes **double replies** — use only one. The backend endpoint
  is recommended.

---

## 10. Onboard your first business

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

## 11. Operating it

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

## 12. Production-readiness checklist

Already in place:
- [x] JWT auth + per-tenant ownership guard (enable with `REQUIRE_AUTH=true`)
- [x] Rate limiting + daily AI spend cap on cost-bearing endpoints
- [x] LLM retry/backoff wrapper
- [x] Prompt-injection sanitizer on untrusted event content
- [x] Human approval gate for high-risk actions
- [x] Docker healthchecks + dependency ordering
- [x] Complete DB schema (all code-referenced tables/columns present)
- [x] All 103 n8n workflows valid; specialist submodule wired

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

## 13. How close is this to a human-run organization?

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
§12 checklist is exactly that path.


---

## 14. How autonomous is this today, and the path to a fully self-running org

**Honest read: structurally it already resembles a real company; operationally
it's roughly 70–85% of the way to a *trustworthy* fully-autonomous org.**

What's already company-like:

- **Real org chart:** CEO → 7 department heads → 32 managers, each with a
  scoped prompt, schedule, and remit.
- **Event-driven proactivity:** agents act on a clock and on business events,
  not only when prompted.
- **Specialist consulting:** managers consult expert specialists before
  deciding.
- **Human-approval gates:** high-risk actions queue for owner sign-off.
- **Layered memory:** Mem0 + pgvector let agents learn from past outcomes.

"100% autonomous" is a **maturity journey, not a single switch** — and the
human owner-approval layer is a deliberate **feature (safety)**, not a gap.

### Phased roadmap to "100%"

| Group | Item | Status |
|-------|------|--------|
| **Senses** (reliable input) | Webhook signature verification | Done |
| | Multi-tenant inbound routing by phone number | Planned |
| | Inbound email intake | Planned |
| **Accountability** | Structured logging with a per-run `trace_id` | Partial |
| | Per-agent cost / latency / quality metrics | Partial |
| | Audit-trail UI | Planned |
| **Safe hands** | Route CEO direct-dispatch through the approval/policy gate | Done |
| | Dispatch idempotency (dedup key on retries) | Done |
| | Spend caps per department | Partial |
| **Cross-checking** (quality) | Agent-output evaluation harness (LLM-as-judge / rule checks) | Planned |
| | Regression scoring of manager decisions | Planned |
| | Canary rollouts of prompt changes | Planned |
| **Cooperation** | Shared task-handoff protocol between departments | Partial |
| | SLA / escalation timers | Planned |
| | Weekly cross-department retro that updates strategy | Planned |

**Status key:** *Done* = shipped; *Partial* = foundations exist, needs
hardening; *Planned* = designed but not yet built.

### Recommended next 3 steps

1. **Finish accountability first** — land structured JSON logging with a
   `trace_id` per run plus per-agent cost/latency metrics, so every autonomous
   action is explainable and priced before you widen autonomy.
2. **Close the senses gap** — add multi-tenant inbound routing by phone number
   and inbound email intake, so the org reliably hears *every* customer.
3. **Stand up cross-checking** — introduce an agent-output evaluation harness
   (LLM-as-judge + rule checks) to catch quality drift before it reaches
   customers.
