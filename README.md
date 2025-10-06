# Petcare Server — Dev & Ops Cheatsheet

This repo uses a single orchestrator script `run-stack.sh` plus a `Makefile` for common tasks. You can develop in two ways:

- **Non‑Docker app (default)** — run Uvicorn on your host for fast iteration; Postgres can be Docker or external.
- **Dockerized app** — run API + infra (db/redis/minio) in Docker.

> **Default goal:** `make` = `make fast` — ensure DB, launch the app locally. No schema, no seed, no tests, **no installs**.

---

## Quick Start

```bash
# 1) Ensure Docker is installed. For non‑docker app you also need Python 3.11+ (3.12+ OK).
# 2) Create a .dbstack.env from the template below.
# 3) Start developing:
make          # DB up → run app (no schema/seed/tests, no installs)
# Open http://localhost:8001/docs
```

Prefer the app in Docker?
```bash
make start-docker          # Start ALL compose services (db, api, redis, minio)
# Open http://localhost:8001/docs
```

---

## `.dbstack.env` template

Create this file at repo root:

```bash
# --- Compose ---
# COMPOSE_FILE=./docker-compose.yml   # optional; defaults to ./docker-compose.yml

# Service name for Postgres (Compose service name, not container_name)
PG_CONTAINER=db

# --- Postgres logical DB ---
PG_DB=petcare
PG_USER=postgres
PGPASSWORD=postgres
PG_READY_TIMEOUT=60

# --- Files ---
SCHEMA_FILE=./schema.sql
SEED_FILE=./seed.sql
RESET_PUBLIC=0            # 1 = drop & recreate schema public before applying schema
SEED_TRUNCATE=0           # 1 = TRUNCATE all public tables before seeding

# --- App (host) ---
VENV_PATH=.venv
REQ_FILE=./requirements.txt
APP_IMPORT=app.main:app
HOST=0.0.0.0
PORT=8001
ENV_FILE=./env

# --- DB URL precedence ---
# If you set DATABASE_URL, the scripts USE IT VERBATIM and won't start Docker DB if it’s reachable.
# Example (host-mapped db on 8432):
# DATABASE_URL=postgresql://postgres:postgres@localhost:8432/petcare
```

**Notes**

- In `docker-compose.yml`, avoid `container_name:`; let Compose auto‑name containers. Conflicts go away and you can keep the DB running while you churn the API.
- Example Postgres mapping:
  ```yaml
  ports:
    - "8432:5432"  # host:container
  ```
  Host app connects to `localhost:8432`. Containers connect to `db:5432`.

---

## Commands (Makefile)

### Non‑Docker app (Uvicorn on host)

| Command             | Description |
| ---                 | --- |
| `make` / `make fast`| **DB up** → **run app** (foreground). No schema/seed/tests. **No pip installs**. Requires `.venv` already set up. |
| `make start`        | Same as fast but **daemonized** (background). PID/log: `.run/uvicorn.pid`, `.run/uvicorn.log`. |
| `make status`       | Shows whether the app is running (works for both foreground & daemon). |
| `make logs`         | Tails daemon log (`.run/uvicorn.log`). |
| `make stop`         | Stops the app (daemon or foreground). PID file → port match → cmdline. DB untouched. |
| `make full`         | DB up → (optional `RESET_PUBLIC`) → **schema** → **seed** (tolerant) → (optional tests) → run app. **Installs deps**. |
| `make schema`       | Apply schema (honors `RESET_PUBLIC`). |
| `make schema_seed`  | Apply schema then **seed** (tolerant). |
| `make seed`         | **Seed only** (tolerant; continues past duplicates/conflicts). |
| `make seed-run`     | **Seed (tolerant)** then run app (no installs). |
| `make tests`        | Run `pytest`. |
| `make info`         | Print resolved settings (compose file, DB mode, URL, etc.). |
| `make help`         | Show a concise, colorized list of targets. |

### Dockerized app

| Command             | Description |
| ---                 | --- |
| `make start-docker` | Start **all** services in compose (`docker compose up -d --remove-orphans`). Idempotent/tolerant. |
| `make stop-docker`  | Stop all services (`docker compose down`). Volumes persist. |
| `make api-up`       | Start API **only** (`docker compose up -d --no-deps api`). Keeps DB running. |
| `make api-restart`  | Restart API **only**. |
| `make api-rebuild`  | Rebuild API image, then start it (`--no-deps`). |
| `make api-stop`     | Stop API **only**. |
| `make api-logs`     | Tail API logs. |

> If `api` has `depends_on: db` and you **only** want API, always use `--no-deps` (already baked into the targets above) so DB isn’t touched.

Run `make help` anytime to see these targets with one‑line descriptions.

---

## Behavior Details

### DB detection & precedence
- If `DATABASE_URL` is set **and reachable** → the scripts use it and **do not** start the Docker DB.
- Else, the script brings up the Compose **service** `PG_CONTAINER` (default `db`) and waits for readiness.
- When `DATABASE_URL` is missing, it will be **derived from the live compose port mapping** (no hardcoded `5432`).

### Fast vs Start vs Full
- **fast**: quickest; ensure DB, **skip installs**, run Uvicorn (foreground).
- **start**: same as fast but background (PID/log managed).
- **full**: installs/updates deps, applies schema/seed, optionally tests, then runs.

### Tolerant seeding
Seeding uses a tolerant psql wrapper:
- `\set ON_ERROR_STOP 0` so a single error doesn’t kill the whole run.
- `\set ON_ERROR_ROLLBACK on` so errors inside a transaction roll back to a savepoint and continue.
- Optional **hard reset**: set `SEED_TRUNCATE=1` to `TRUNCATE … RESTART IDENTITY CASCADE` all public tables before seeding.

### Stop/Status that work for both modes
- `make stop` kills the app whether it’s daemonized or foreground (PID file → port → cmdline).
- `make status` detects either mode.

---

## Typical Workflows

**Daily dev (host app, DB in Docker)**
```bash
make                 # run app in foreground
# edit, test, Ctrl+C to stop
make                 # run again
```

**Background server**
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

**Docker‑only runtime (PO/demo)**
```bash
make start-docker            # starts db, api, redis, minio
# use http://localhost:8001/docs
make stop-docker             # tear down stack
```

---

## Troubleshooting

- **“container name … already in use”**  
  Remove `container_name:` from compose and keep `PG_CONTAINER=db`. Compose auto‑names per project; conflicts disappear.

- **“orphan containers” warning**  
  Harmless. `make start-docker` uses `--remove-orphans`. You can also run `docker compose down` to clean up old ones.

- **`make fast` or `make start` installs deps**  
  They shouldn’t. Ensure `cmd_fast`/`cmd_start` set `INSTALL_DEPS=0` before `ensure_venv`. If `.venv` is missing, run `make full` once.

- **Use external (non‑Docker) Postgres**  
  Set a valid `DATABASE_URL`. The script verifies it and won’t start the Docker DB if reachable. Schema/seed run against that URL.

- **Inside‑Docker DB host/port**  
  Containers use container ports/hosts (e.g., `postgresql://…@db:5432/…`). Host‑mapped ports like `8432` are for **host apps** only.

---

## Windows / PowerShell Quick Start

This project ships a PowerShell orchestrator that mirrors the Ubuntu/Makefile flow:

**DB (docker) → schema → seed → venv + deps → tests → app**

```powershell
# From repo root in PowerShell
# 1) Ensure Docker Desktop is running
# 2) Ensure Python 3.11 is installed (see below)
# 3) Run the full dev flow in the foreground (live logs):
.
./make full

# Same flow, but run the app in the background (daemon/job):
.
./make full-daemon
```

### PowerShell Commands

| Command | What it does |
|---|---|
| `.
./make full` | DB up → schema → seed → deps → tests → run app **(foreground)** |
| `.
./make full-daemon` | Same as `full`, but run the app **in background** |
| `.
./make fast` | DB up → schema → seed → deps → tests → run app (foreground); fastest happy path |
| `.
./make schema_seed` | Apply schema + seed (tolerant) |
| `.
./make seed` | Apply seed only (tolerant) |
| `.
./make tests` | Run pytest suite |
| `.
./make start` | Start the app only (after deps) |
| `.
./make status` / `logs` / `stop` | Manage background job (`full-daemon`) |

> Foreground vs background: Foreground prints live request/response logs to the console. Use **Ctrl+C** to stop. Background runs as a PowerShell job (`app-job`); use `status`, `logs`, and `stop` to manage it.

---

## Python on Windows: `python` vs `py` (and why we use `py -3.11`)

- **`python`** → “first Python on PATH”. Could be any version—or a Microsoft Store alias that prints *“Python was not found…”*.
- **`py`** → the **Windows Python Launcher**. It selects exact versions reliably:
  - `py -3.11` → runs your installed Python **3.11**
  - `py -3.13` → runs **3.13**, etc.

The script prefers **Python 3.11**. If multiple Pythons are installed, `py -3.11` makes the choice unambiguous.

**Install Python 3.11** (recommended):
1. Download from the official site: https://www.python.org/downloads/release/python-3110/
2. During install, check **“Add Python to PATH”** (and optionally **“Install for all users”**).
3. Verify: `py -3.11 --version`

**Important (avoid Microsoft Store traps):**
- Windows Settings → Apps → Advanced app settings → **App execution aliases** → turn **off** **Python** and **Python 3**.

If the script can’t find 3.11, it will say:
```
Python 3.11 not found. Install it or set $env:PY_EXE='py -3.11'.
```

You can pin a custom interpreter via env var:
```powershell
# session-only
$env:PY_EXE = 'py -3.11'
# or a full path
$env:PY_EXE = 'C:\Python311\python.exe'
```

---

## Virtual Environment (`.venv`) — Create, Activate, Clean Up

You **don’t install Python inside** `.venv`; you **create** a venv **from** an installed (“base”) Python.
The venv isolates packages while reusing the base interpreter.

### Create
```powershell
# Create venv from Python 3.11
py -3.11 -m venv .venv
```

### Activate
```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1
# You should now see (.venv) prefix in your prompt
```

### Install deps (manual)
> Normally the script does this for you, but these are handy if you’re doing it by hand.
```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```

### Deactivate
```powershell
deactivate
```

### Clean up / Recreate (when switching Python versions or fixing a broken venv)
```powershell
Remove-Item -Recurse -Force .\.venv
py -3.11 -m venv .venv
```

> The orchestrator will also **auto-rebuild** `.venv` if it detects that the base interpreter changed (e.g., you moved from 3.13 to 3.11).

---

## Typical Workflows (Windows)

```powershell
# Full cycle in foreground (recommended while developing)
.
./make full

# Same flow, background app as a job (tail logs with 'logs')
.
./make full-daemon
.
./make logs
.
./make stop

# Only DB + schema (fast reset)
.
./make schema

# Run tests only (assumes deps already installed)
.
./make tests
```

**Troubleshooting quickies**

- “Python was not found …” → disable app execution aliases; ensure `py -3.11` exists.
- “Could not find platform independent libraries \<prefix\>” → benign Python probing; the script ignores it.
- DB issues → ensure Docker Desktop is running; `.
./make start-docker` / `stop-docker` can help.
- Port busy → set `APP_PORT` in `.env` or stop the conflicting process.

