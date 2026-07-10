# Deployment Guide

Host the whole system on free tiers by splitting it across three services:

| Component | Platform | Free tier notes |
|-----------|----------|-----------------|
| Database  | [Neon](https://neon.tech) (serverless Postgres) | ~0.5 GB, auto-suspends when idle |
| Backend API | [Render](https://render.com) (web service) | Spins down after 15 min idle (~50s cold start) |
| Dashboard | [Streamlit Community Cloud](https://streamlit.io/cloud) | Free, deploys straight from GitHub |

> These free tiers are perfect for a portfolio/demo instance. They are **not**
> sized for production SLAs — expect cold starts and small storage. See
> [SECURITY.md](../SECURITY.md) before exposing real data.

The app needs no TimescaleDB-specific features, so plain Postgres (Neon) works.
Schema is created automatically on first boot; no migration step is required.

---

## 1. Database — Neon

1. Create a project at [neon.tech](https://neon.tech) and copy the connection
   string (looks like `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require`).
2. Keep it handy — you'll paste it into Render as `ASYNC_DATABASE_URL`.

You can paste the Neon URL **as-is**: the backend coerces it to the async
driver and enables SSL automatically (`sslmode`/`channel_binding` params are
handled for you).

---

## 2. Backend API — Render

**One click:** use the button in the [README](../README.md#-deploy) — it reads
[`render.yaml`](../render.yaml) and provisions the service. Then set:

- `ASYNC_DATABASE_URL` → your Neon connection string
- `BOOTSTRAP_API_KEY` → Render generates one; **copy its value** (you'll need it
  for the dashboard and SDK)

**Manual alternative:** New → Web Service → connect this repo →

- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment: `ASYNC_DATABASE_URL`, `DB_SSL=require`, `BOOTSTRAP_API_KEY=<a strong key>`

Once live, confirm health: `https://<your-app>.onrender.com/health` → `{"status": "healthy", ...}`
and open the interactive API docs at `/docs`.

---

## 3. Dashboard — Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → New app → this repo.
2. Main file path: `dashboard/app.py`.
3. Under **Advanced settings → Secrets**, add (Streamlit exposes secrets as env vars):

   ```toml
   FAILURE_INVESTIGATOR_ENDPOINT = "https://<your-app>.onrender.com"
   FAILURE_INVESTIGATOR_API_KEY  = "<the BOOTSTRAP_API_KEY from Render>"
   ```

4. Deploy. The dashboard talks to the backend server-side, so no CORS setup is needed.

---

## 4. Seed demo data

With the backend live, populate it so the dashboard isn't empty:

```bash
export FAILURE_INVESTIGATOR_API_KEY=<your key>
python scripts/seed_demo.py --endpoint https://<your-app>.onrender.com --events 250 --days 7
```

---

## Notes & troubleshooting

- **Cold starts:** the first request after idle wakes the Render service (~50s)
  and the Neon database. Subsequent requests are fast.
- **Multiple backend instances:** rate-limit state is per-process in memory. If
  you scale beyond one instance, set `RATE_LIMIT_STORAGE_URI` to a Redis URL.
- **Rotating the demo key:** change `BOOTSTRAP_API_KEY` in Render and update the
  Streamlit secret to match. Old keys stop working once they're no longer seeded.
- **Data hygiene:** set `DATA_RETENTION_DAYS` (e.g. `7`) on the backend so a
  public demo auto-purges old events. PII redaction is on by default.
