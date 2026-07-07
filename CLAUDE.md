# petcare-server

FastAPI backend for PetCare. Deployed on Vercel as `petcare-server-e9m7`
under the `aixendira-s-projects` team. Companion repo: `petcare-mobile`.

## First-time local setup (no Docker, no MySQL)

This repo's README describes a Docker Compose workflow (Postgres/Redis/Minio).
That is **not** what we use — the production DB is a Neon Postgres instance,
and local dev talks to that same instance directly. Skip Docker entirely.

1. **Vercel CLI + auth**: `npm i -g vercel`, then `vercel login` — must sign in
   with the `aixendrialab` account/team (not a personal Vercel account), or
   `vercel link` will silently create a stray new project instead of linking
   the real one. Verify with `vercel project ls` — you should see
   `petcare-mobile` and `petcare-server-e9m7`.
2. `vercel link --yes --project petcare-server-e9m7`
3. Python: `py -3.11 -m venv .venv`, activate it, then
   `pip install -r requirements.txt -r requirements-dev.txt`
4. **Database**: `DATABASE_URL` and `JWT_SECRET` are set in Vercel but marked
   **Sensitive** — `vercel env pull` will always return them as empty strings,
   even to the project owner, by design. Get the real connection string from
   the Neon console (console.neon.tech, same account) instead, and put it in
   `.env` as `DATABASE_URL=postgresql://...`. `JWT_SECRET` doesn't need the
   real prod value — `app/routers/auth.py` and `security.py` both fall back
   to `"dev-secret"` when unset, which is fine for local dev.
5. **Do not run `schema.sql` or `seed.sql`** against this DATABASE_URL — that
   Neon instance holds live production data (real users/vets/pets), and
   `seed.sql` / the Makefile's seed target can `TRUNCATE` tables
   (`SEED_TRUNCATE=1` in `.dbstack.env`). Local dev reads/writes the same data
   production does.
6. Run the server with **`python run_dev.py`**, not raw `uvicorn`. Reasons
   this file exists (both are real bugs, not style preferences):
   - `os.getenv("DATABASE_URL")` in `app/core/db.py` and `app/dependencies.py`
     reads straight from the process environment — it does **not** load
     `.env`. (The `pydantic-settings` `Settings` class in `app/core/config.py`
     that does read `.env` is unused elsewhere in the app.) `run_dev.py`
     parses `.env` and populates `os.environ` before anything else imports.
   - Windows only: psycopg's async connection pool cannot run under the
     default `ProactorEventLoop` (raises
     `Psycopg cannot use the 'ProactorEventLoop'...` repeatedly, and any
     route using `app.core.db.get_conn()` — `auth.py`, `vets.py`, `vet.py`,
     `security.py` — hangs for 30s then 500s). `app/main.py` now guards this
     with `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`
     at the top of the file, but that guard only takes effect if it's set
     *before* uvicorn creates its event loop — which means before uvicorn is
     even imported. `run_dev.py` does that; the `uvicorn app.main:app` CLI
     command does not (the fix inside `main.py` runs too late in that case).

Verify it's working:
```bash
curl http://127.0.0.1:8001/docs          # 200
curl http://127.0.0.1:8001/api/v1/health # {"status":"ok"}
curl http://127.0.0.1:8001/api/v1/vets   # real vet rows from Neon
```

### Known flaky (harmless) error

The very first request that touches the DB right after a cold start can
throw `psycopg.OperationalError: consuming input failed: SSL connection
has been closed unexpectedly` — Neon's pooler dropping a freshly-opened
connection. It surfaces in the browser as a CORS error (FastAPI's default
exception response doesn't carry CORS headers, so a backend 500 shows up
client-side as "blocked by CORS policy" — always check the server log for
the real traceback before chasing CORS config). Retrying the request works.
If it becomes annoying, pass `check=AsyncConnectionPool.check_connection`
to the pool constructor in `app/core/db.py`.

## Running the mobile app against this server

See `petcare-mobile/CLAUDE.md`. Its `.env` needs
`EXPO_PUBLIC_API_BASE=http://127.0.0.1:8001/api/v1` to point at this local
server instead of the deployed one.
