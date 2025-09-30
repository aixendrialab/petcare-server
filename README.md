# Petcare Server — Dev & Ops Cheatsheet

This repo ships with a `Makefile` and a single orchestrator script `run-stack.sh` so you can develop in two ways:

- **Default (non‑Docker app)** — run Uvicorn on your host (fast iteration). Docker is used only for Postgres.
- **Dockerized app** — run API + infra (db/redis/minio) in Docker.

> **Default goal**: `make` is equivalent to `make fast` — it ensures DB is up and launches the app locally. No schema, no seed, no tests, **no installs**.

---

## Quick Start

```bash
# 1) Ensure you have Docker installed; for non-docker app you also need Python 3.11+ (or 3.12+).
# 2) Create a .dbstack.env from the template below.
# 3) Start developing:
make          # Non‑docker app: DB up → run app (no schema/seed/tests, no installs)
# Visit http://localhost:8001/docs
```

If you prefer the app in Docker:
```bash
make start-docker          # Start ALL compose services (db, api, redis, minio)
# Visit http://localhost:8001/docs
```

---

## .dbstack.env (template)

Create this file at the repo root:

```bash
# --- Compose ---
# Optional: if omitted, run-stack.sh auto-detects ./docker-compose.yml
# COMPOSE_FILE=./docker-compose.yml

# Service name to interact with (recommended to be the service name, not a fixed container_name)
PG_CONTAINER=db

# --- Postgres logical DB ---
PG_DB=petcare
PG_USER=postgres
PGPASSWORD=postgres
PG_READY_TIMEOUT=60

# --- Files ---
SCHEMA_FILE=./schema.sql
SEED_FILE=./seed.sql
RESET_PUBLIC=0            # 1 = drop & recreate schema public before schema
SEED_TRUNCATE=0           # 1 = TRUNCATE all public tables before seeding (optional)

# --- App (host) ---
VENV_PATH=.venv
REQ_FILE=./requirements.txt
APP_IMPORT=app.main:app
HOST=0.0.0.0
PORT=8001
ENV_FILE=./env

# --- DB URL precedence ---
# If you set DATABASE_URL, the scripts USE IT VERBATIM (external or docker). Example (host-mapped db on 8432):
# DATABASE_URL=postgresql://postgres:postgres@localhost:8432/petcare
```

**Notes**
- In `docker-compose.yml`, prefer **removing `container_name`** so Compose auto‑names containers; conflicts go away and the DB can stay up while you churn the API.
- Postgres port mapping example:
  ```yaml
  ports:
    - "8432:5432"  # host:container
  ```
  Your local (non‑Docker) app connects to `localhost:8432`. Any app **inside** Docker connects to `db:5432`.

---

## Command Reference

### Non‑Docker app (Uvicorn on host)

| Command         | What it does |
|---              |---|
| `make` / `make fast` | **DB up** (tolerant) → **run app** (foreground). No schema/seed/tests. **No pip installs**. Requires an existing `.venv` that already has deps. |
| `make start`    | Same as **fast**, but runs in **background** (daemon). PID/log: `.run/uvicorn.pid`, `.run/uvicorn.log`. |
| `make status`   | Shows whether the app is running (works for **foreground** and **daemon** runs). |
| `make logs`     | Tails daemon log (`.run/uvicorn.log`). |
| `make stop`     | Stops the app (daemon or foreground). Tries PID file → port match → cmdline. DB untouched. |
| `make full`     | DB up → (optional `RESET_PUBLIC`) → **schema** → **seed** (tolerant) → (optional tests) → run app. **Installs deps** if needed. |
| `make schema`   | Apply schema (honors `RESET_PUBLIC`). |
| `make schema_seed` | Apply schema, then **seed** (tolerant). |
| `make seed`     | **Seed only**, tolerant of errors (continues through duplicate/conflicts). |
| `make seed-run` | **Seed (tolerant)** then run app (no installs). |
| `make tests`    | Run `pytest`. |

### Dockerized app

| Command             | What it does |
|---                  |---|
| `make start-docker` | `docker compose up -d --remove-orphans` — starts **all** services from compose. Idempotent, tolerant. |
| `make stop-docker`  | `docker compose down` — stops all services and removes network (volumes persist). |
| `make api-up`       | Start API only: `docker compose up -d --no-deps api`. |
| `make api-restart`  | Restart API only. |
| `make api-rebuild`  | Rebuild API image and start it (DB untouched). |
| `make api-stop`     | Stop API only. |
| `make api-logs`     | Tail API logs. |

> If `api` depends_on `db` in compose and you **only** want API, use `--no-deps` to avoid touching DB (`make api-up` already does this).

Run `make help` to print a one‑page list of targets and descriptions.

---

## Behavior Details

### DB detection & precedence
- If `DATABASE_URL` is set and reachable → the scripts **use it** and **do not** start Docker DB.
- Else, the scripts will **reuse** a running DB container named `PG_CONTAINER` (service name recommended), or start it via Compose if missing.
- `resolve_database_url` builds a DB URL from the **live** Docker port mapping (no hard‑coded `5432`), so `8432:5432` just works.

### Fast vs Full vs Start
- **fast**: quickest; ensure DB, **skip installs**, run Uvicorn (foreground).
- **start**: same as fast but **daemonized** (background).
- **full**: installs deps, applies schema/seed, optionally tests, then runs.

### Tolerant seeding
`make seed` and the seeding phase of `full`, `schema_seed`, `seed-run` use a tolerant psql driver:
- `\set ON_ERROR_STOP 0` so single errors don’t terminate the session.
- `\set ON_ERROR_ROLLBACK on` so statements inside a `BEGIN` roll back to a savepoint and continue.
- This means duplicates/conflicts don’t abort the whole run.
- Optional **hard reset** before seeding: set `SEED_TRUNCATE=1` to `TRUNCATE … RESTART IDENTITY CASCADE` all public tables.

### Stop/Status that work for both foreground & background
- `make stop` kills the app if it’s running in **daemon** or **foreground** (via PID file, then listening port, then command‑line match).
- `make status` detects either mode.

---

## Typical Workflows

**Daily dev (host app, DB in Docker)**
```bash
make                 # run app in foreground
# edit, test, Ctrl+C to stop
make                 # run again
```

**Run in background**
```bash
make start           # daemonize
make status          # confirm it's up
make logs            # tail logs
make stop            # stop app (DB untouched)
```

**Apply schema & reseed (don’t stop on duplicates)**
```bash
make schema_seed
```

**Recreate everything cleanly**
```bash
RESET_PUBLIC=1 make full
```

**Docker-only runtime (PO/demo)**
```bash
make start-docker            # starts db, api, redis, minio
# work with http://localhost:8001/docs
make stop-docker             # tear down stack
```

---

## Troubleshooting

- **“container name … already in use”**  
  Remove `container_name:` from compose and set `PG_CONTAINER=db` in `.dbstack.env`. Compose auto‑names per project (e.g., `petcare-server-db-1`) and avoids conflicts.

- **“orphan containers” warning**  
  Harmless. `make start-docker` uses `--remove-orphans`. You can also run `docker compose down` to clean up.

- **`make fast` tries to install deps**  
  It shouldn’t. Ensure `cmd_fast`/`cmd_start` set `INSTALL_DEPS=0` before `ensure_venv`. If `.venv` is missing, run `make full` once.

- **Using an existing non‑Docker Postgres**  
  Set `DATABASE_URL` to your external DB. The script verifies reachability and never starts Docker DB if reachable.

- **App uses wrong DB host/port inside Docker**  
  Containers talk on container ports: use `postgresql://…@db:5432/…` inside Docker. Host‑mapped ports like `8432` are for **host apps** only.

---

## Zero‑Python on host (optional)

If you want your product owner to run everything via Docker only:
- Keep the `api` service in compose (builds from `Dockerfile`).
- They can just run:
  ```bash
  docker compose up -d
  # or
  make start-docker
  ```
- The API image runs Uvicorn inside the container; local Python is not required.

---

## License
Internal project docs. Update as needed for your org.
