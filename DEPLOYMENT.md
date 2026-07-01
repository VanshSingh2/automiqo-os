# Automiqo OS — VPS Deployment Guide (Step by Step)

This guide walks you through deploying Automiqo OS on a fresh Linux VPS
(Ubuntu 22.04 / 24.04) using Docker. It assumes the **one-VPS-per-business** model,
but works fine multi-tenant on a single box too.

> **Architecture recap:** FastAPI backend + Next.js frontend + Redis + n8n, all behind
> Nginx, in Docker Compose. **Supabase (Postgres + pgvector)** is hosted by Supabase in
> the cloud — you do *not* run the database on the VPS.

---

## 0. What you need before you start

| Requirement | Notes |
|---|---|
| A VPS | 2 vCPU / **4 GB RAM** minimum (8 GB comfortable), 40 GB disk. Providers: Hetzner, DigitalOcean, Vultr, Linode. |
| A domain name | e.g. `app.yourbusiness.com` pointed at the VPS IP (an `A` record). |
| A Supabase project | Free tier works to start. https://supabase.com |
| API keys | OpenAI (required). Optional: Anthropic, Twilio/Telnyx (SMS), Vapi (voice), Cal.com (booking), Resend (email), Serper (lead scraping), Stripe. |
| SSH access | to the VPS as a sudo user. |

---

## 1. Prepare the VPS

SSH in, then create a non-root user and install Docker.

```bash
# as root
adduser automiqo
usermod -aG sudo automiqo
su - automiqo

# install Docker + compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker            # activate the docker group without re-login
docker --version && docker compose version
```

Open the firewall for web + SSH only:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

> Do **not** expose ports 8000 (backend), 3000 (frontend), 5678 (n8n), or 6379 (Redis)
> to the internet — Nginx fronts everything. The compose files publish some of these on
> localhost for convenience; lock them down in production (see step 8).

---

## 2. Set up Supabase (the database)

1. Create a project at https://supabase.com → wait for it to provision.
2. **Enable pgvector**: Dashboard → Database → Extensions → enable `vector`.
3. Open the **SQL Editor** and run, in order:
   - `scripts/setup_supabase_master.sql`  (all core tables, idempotent)
   - `scripts/migrations/004_business_os_modules.sql`
   - `scripts/migrations/005_agent_chat.sql`  (team chat / DM threads)
   - any other files in `scripts/migrations/` you haven't applied yet.
4. Grab your keys: Dashboard → Settings → **API**:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY` (service_role — **server-side only, never ship to a browser**)
   - `SUPABASE_ANON_KEY`
5. For Mem0 memory, grab the direct Postgres connection string: Settings → **Database**
   → Connection string → URI (this becomes `MEM0_DB_URL`).

---

## 3. Get the code onto the VPS

```bash
cd ~
git clone https://github.com/VanshSingh2/automiqo-os.git
cd automiqo-os
```

---

## 4. Configure environment variables

```bash
cp .env.example .env
nano .env
```

Fill in at minimum (the rest can stay blank until you wire that integration):

```ini
APP_ENV=production
JWT_SECRET=<run: openssl rand -hex 32>
CRON_SECRET=<run: openssl rand -hex 24>
FRONTEND_URL=https://app.yourbusiness.com

OPENAI_API_KEY=sk-proj-...
CEO_MODEL=openai/gpt-4.1
DEPT_MODEL=openai/gpt-4o-mini

SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
SUPABASE_ANON_KEY=eyJ...
MEM0_DB_URL=postgresql://postgres:<PW>@db.<project>.supabase.co:5432/postgres

REDIS_URL=redis://redis:6379

# Frontend → backend (server-side; Nginx routes /api to the backend)
BACKEND_URL=http://backend:8000
NEXT_PUBLIC_API_URL=https://app.yourbusiness.com
NEXT_PUBLIC_BUSINESS_ID=<your business UUID once onboarded>

# Autonomy / cost controls
AUTONOMOUS_MODE=true
MANAGER_AUTONOMY=true
MANAGER_PULSE_INTERVAL_MINUTES=180   # raise to 360 to cut AI cost in half
```

> **Cost tip:** the autonomous baseline is ~$3–6/month/business on `gpt-4o-mini`.
> If you want to launch cheap, set `MANAGER_AUTONOMY=false` and raise
> `MANAGER_PULSE_INTERVAL_MINUTES`; turn them up once you're happy.

Lock down the file:

```bash
chmod 600 .env
```

---

## 5. Point the frontend proxy at the backend

The frontend proxies API calls through `/api/proxy/...` to `BACKEND_URL`. In Docker,
services talk over the compose network, so `BACKEND_URL=http://backend:8000` (set in
step 4) is correct. No code change needed.

---

## 6. Build and start everything

Use the production compose file:

```bash
cd ~/automiqo-os

# build the images
docker compose -f docker/docker-compose.yml build

# start in the background
docker compose -f docker/docker-compose.yml up -d

# watch the logs
docker compose -f docker/docker-compose.yml logs -f backend
```

You should see the scheduler start:

```
✅ Task worker + Event worker + N scheduler tasks started
[manager_scheduler] ✅ manager autonomy started
```

Quick health check:

```bash
curl http://localhost:8000/health          # backend
curl http://localhost:3000                  # frontend
```

---

## 7. Onboard your first business

Create the business (this seeds config, the module blueprint, and the knowledge base):

```bash
curl -X POST http://localhost:8000/onboard \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Glow Med Spa",
    "industry": "med spa",
    "city": "Newark", "state": "NJ",
    "timezone": "America/New_York",
    "brand_voice": "warm, professional",
    "monthly_revenue_goal": 50000
  }'
```

Copy the returned `business_id` into `.env` as `NEXT_PUBLIC_BUSINESS_ID`, then restart
the frontend so the dashboard points at it:

```bash
docker compose -f docker/docker-compose.yml up -d --force-recreate frontend
```

Register an owner login (used once auth is enforced — see the roadmap):

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@biz.com","password":"<strong>","business_id":"<the id>"}'
```

---

## 8. Put Nginx + HTTPS in front

The included `docker/nginx.conf` already routes `/` → frontend and `/api/` → backend.
Add TLS with Let's Encrypt. The simplest path is to run Certbot on the host and have
Nginx terminate TLS, **or** add a companion container. Host-Certbot version:

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d app.yourbusiness.com   # stop nginx briefly or use webroot
```

Then mount the certs into the nginx container and add a `443` server block that
`proxy_pass`es the same way the `80` block does, with:

```
listen 443 ssl;
ssl_certificate     /etc/letsencrypt/live/app.yourbusiness.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/app.yourbusiness.com/privkey.pem;
```

and redirect `80` → `443`. Reload: `docker compose ... restart nginx`.

> **Harden the compose ports**: in `docker/docker-compose.yml`, change published ports
> for `backend`, `frontend`, `redis`, and `n8n` to bind to localhost only
> (e.g. `"127.0.0.1:8000:8000"`) so only Nginx is reachable from the internet.

---

## 9. Set up n8n (the automation layer)

n8n runs at `http://<vps>:5678` (proxy it behind Nginx + basic auth in production).

1. Open n8n, create your owner account.
2. Import the workflow JSONs from the `n8n/` directory (Workflows → Import from File).
3. Create the credentials the workflows expect (Supabase, Twilio/Telnyx, etc.).
4. Set `N8N_WEBHOOK_BASE_URL` and `N8N_API_KEY` in `.env` and restart the backend.

---

## 10. Verify the autonomous system is alive

```bash
# trigger a department loop manually (needs the cron secret)
curl -X POST "http://localhost:8000/cron/department-work?department=coo" \
  -H "x-cron-secret: <CRON_SECRET>"

# watch managers take their shifts
docker compose -f docker/docker-compose.yml logs -f backend | grep -E "manager_pulse|scheduler|heartbeat"
```

In the dashboard you should see: metrics, the **Team Members** roster, **Team Chat**
filling with standups/alerts, and the **Activity** feed translating backend events.

---

## 11. Ongoing operations

**Update to the latest code:**
```bash
cd ~/automiqo-os && git pull
docker compose -f docker/docker-compose.yml up -d --build
```

**Backups:** Supabase holds all state — enable Supabase's automated backups
(Dashboard → Database → Backups). Also snapshot the `n8n_data` volume:
```bash
docker run --rm -v automiqo-os_n8n_data:/data -v $PWD:/backup alpine \
  tar czf /backup/n8n-backup-$(date +%F).tar.gz -C /data .
```

**Logs / restart:**
```bash
docker compose -f docker/docker-compose.yml logs -f
docker compose -f docker/docker-compose.yml restart backend
```

**Watch AI spend:** query the `ai_costs` table in Supabase, or use the CFO cost report
endpoint. Tune `MANAGER_PULSE_INTERVAL_MINUTES` / `MANAGER_AUTONOMY` if it's higher than
you want.

---

## 12. Production hardening checklist

Before onboarding real paying customers, complete these (see
`docs/CODE_REVIEW_AND_ROADMAP.md` for details):

- [ ] **Enforce API authentication** — the JWT module exists but routers don't require
      it yet. Do this before exposing the API publicly (blocker B1).
- [ ] **Rate limiting + a daily AI spend cap** (blocker B2).
- [ ] **HTTPS/TLS** terminated at Nginx (step 8).
- [ ] **Bind internal ports to localhost** so only Nginx is public (step 8).
- [ ] **Strong `JWT_SECRET` and `CRON_SECRET`** (not the `.env.example` placeholders).
- [ ] **Keep `SUPABASE_SERVICE_KEY` server-side only** — never in the browser bundle.
- [ ] **n8n behind auth** (basic auth or Nginx-protected).
- [ ] **Enable Supabase backups** and test a restore.
- [ ] **Set up uptime monitoring** (e.g. UptimeRobot on `/health`).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Backend exits on boot | Missing/invalid `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`, or `OPENAI_API_KEY`. Check `docker compose logs backend`. |
| `ERROR 42703 column ... does not exist` | A migration wasn't applied — re-run the master SQL + all `scripts/migrations/*.sql`. |
| Dashboard shows "Backend unreachable" | `BACKEND_URL` wrong, or backend container down. Confirm `curl localhost:8000/health`. |
| Team chat empty | Migration `005_agent_chat.sql` not applied, or no autonomous runs have happened yet. |
| Managers never post | `MANAGER_AUTONOMY=false`, or `OPENAI_API_KEY` invalid — check `[manager_pulse]` logs. |
| AI bill higher than expected | Lower cadence: raise `MANAGER_PULSE_INTERVAL_MINUTES`, or set `MANAGER_AUTONOMY=false`. |
| Frontend build fails on `npm ci` | Delete `frontend/package-lock.json` mismatch or run `npm install` once to refresh the lock. |
