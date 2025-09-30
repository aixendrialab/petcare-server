#!/usr/bin/env bash
set -euo pipefail
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

# ---------- Resolve repo root ----------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# ---------- Load config ----------
CONFIG_FILE="${CONFIG_FILE:-.dbstack.env}"
if [[ -f "$CONFIG_FILE" ]]; then
  set -a; . "$CONFIG_FILE"; set +a
else
  echo "ERROR: Config file not found: $CONFIG_FILE" >&2
  exit 1
fi

# ---------- Defaults ----------
# Deps behaviour: 1 = install/upgrade deps, 0 = skip (used by `fast`)
INSTALL_DEPS="${INSTALL_DEPS:-1}"

PG_CONTAINER="${PG_CONTAINER:?Set PG_CONTAINER in .dbstack.env (compose service or container name)}"
PG_DB="${PG_DB:-petcare}"
PG_USER="${PG_USER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
PG_READY_TIMEOUT="${PG_READY_TIMEOUT:-60}"

SCHEMA_FILE="${SCHEMA_FILE:-./schema.sql}"
SEED_FILE="${SEED_FILE:-./seed.sql}"
RESET_PUBLIC="${RESET_PUBLIC:-0}"

VENV_PATH="${VENV_PATH:-.venv}"
REQ_FILE="${REQ_FILE:-./requirements.txt}"

APP_IMPORT="${APP_IMPORT:-app.main:app}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
ENV_FILE="${ENV_FILE:-}"

# --- Local app process bookkeeping ---
RUN_DAEMON="${RUN_DAEMON:-0}"       # 1 = run uvicorn in background
RUN_DIR="${RUN_DIR:-.run}"
PIDFILE="${PIDFILE:-$RUN_DIR/uvicorn.pid}"
LOGFILE="${LOGFILE:-$RUN_DIR/uvicorn.log}"
mkdir -p "$RUN_DIR"

# Compose file: prefer repo root; else $HOME
COMPOSE_FILE="${COMPOSE_FILE:-}"
if [[ -z "${COMPOSE_FILE}" ]]; then
  if [[ -f "./docker-compose.yml" ]]; then
    COMPOSE_FILE="./docker-compose.yml"
  elif [[ -f "$HOME/docker-compose.yml" ]]; then
    COMPOSE_FILE="$HOME/docker-compose.yml"
  else
    echo "ERROR: docker-compose.yml not found (set COMPOSE_FILE or place in repo root or \$HOME)" >&2
    exit 1
  fi
fi

# ---------- Helpers ----------
fail(){ echo "ERROR: $1" >&2; exit 1; }
compose(){ docker compose -f "$COMPOSE_FILE" "$@"; }

wait_pg () {
  local end=$((SECONDS+PG_READY_TIMEOUT))
  echo "⏳ Waiting for Postgres in '$PG_CONTAINER'…"
  until docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d postgres -t -q -c "select 1" >/dev/null 2>&1; do
    [[ $SECONDS -ge $end ]] && fail "Postgres not ready in time."
    sleep 2
  done
}

# Parse DATABASE_URL into env vars using python (safe, no deps)
parse_db_url_env () {
  py_run <<'PY'
import os, sys
from urllib.parse import urlparse
u = os.environ.get("DATABASE_URL","")
if not u: sys.exit(1)
p = urlparse(u)
user = p.username or "postgres"
pw   = p.password or ""
host = p.hostname or "localhost"
port = p.port or 5432
db   = (p.path[1:] if p.path.startswith("/") else p.path) or "postgres"
print(f"DBU={user}\nDBP={pw}\nDBH={host}\nDBPORT={port}\nDBNAME={db}")
PY
}

# True DB readiness check against DATABASE_URL
db_alive_via_url () {
  [[ -n "${DATABASE_URL:-}" ]] || return 1

  # Try psql (most reliable)
  if command -v psql >/dev/null 2>&1; then
    eval "$(parse_db_url_env | sed 's/^/export /')"
    if [[ -n "${DBP:-}" ]]; then
      PGPASSWORD="$DBP" psql -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -t -q -c "select 1" >/dev/null 2>&1 && return 0
    else
      psql                -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -t -q -c "select 1" >/dev/null 2>&1 && return 0
    fi
  fi

  # Fallback: TCP reachability (no auth)
  py_run <<'PY'
import os, sys, socket
from urllib.parse import urlparse
u = os.environ.get("DATABASE_URL","")
if not u:
  sys.exit(1)
p = urlparse(u)
host = p.hostname or "localhost"
port = p.port or 5432
s = socket.socket(); s.settimeout(1.5)
try:
  s.connect((host, port)); s.close(); sys.exit(0)
except Exception:
  sys.exit(2)
PY
}

# pick python command (python3 preferred)
py_cmd() { command -v python3 >/dev/null 2>&1 && echo python3 || echo python; }

# run a heredoc with whichever python is available
py_run() { "$(py_cmd)" - "$@"; }

ensure_db () {
  echo "🧩 Ensuring Postgres…"

  # 1) If DATABASE_URL is preset & reachable → just use it, no docker
  if [[ -n "${DATABASE_URL:-}" ]]; then
    if db_alive_via_url; then
      echo "✅ DATABASE_URL reachable; skipping docker DB."
      return 0
    else
      echo "ℹ️ DATABASE_URL set but not reachable; will try docker DB."
    fi
  fi

  # 2) If a container named $PG_CONTAINER already exists and is running → use it
  if docker ps --format '{{.Names}}' | grep -Fxq "$PG_CONTAINER"; then
    echo "ℹ️ Reusing running container '$PG_CONTAINER'."
    return 0
  fi

  # 3) If it exists but stopped → start it
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$PG_CONTAINER"; then
    echo "ℹ️ Starting existing container '$PG_CONTAINER'."
    docker start "$PG_CONTAINER" >/dev/null
    wait_pg
    return 0
  fi

  # 4) Else bring up only the db service (no api)
  echo "🧩 Bringing up DB via compose ($COMPOSE_FILE)"
  compose up -d db
  wait_pg
}

reset_public () {
  echo "♻️ Resetting schema 'public'…"
  docker exec -i -e "PGPASSWORD=$PGPASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$
BEGIN
  EXECUTE 'DROP SCHEMA IF EXISTS public CASCADE';
  EXECUTE 'CREATE SCHEMA public AUTHORIZATION CURRENT_USER';
  EXECUTE 'GRANT ALL ON SCHEMA public TO CURRENT_USER';
  EXECUTE 'GRANT ALL ON SCHEMA public TO PUBLIC';
END
$$;
SQL
}

apply_schema () {
  [[ -f "$SCHEMA_FILE" ]] || fail "Schema file not found: $SCHEMA_FILE"
  echo "📜 Applying schema…"
  docker cp "$SCHEMA_FILE" "$PG_CONTAINER:/tmp/schema.sql"
  docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f /tmp/schema.sql
}

apply_seed () {
  [[ -f "$SEED_FILE" ]] || fail "Seed file not found: $SEED_FILE"
  echo "🌱 Seeding data (tolerant)…"
  docker cp "$SEED_FILE" "$PG_CONTAINER:/tmp/seed.sql"

if [[ "${SEED_TRUNCATE:-0}" == "1" ]]; then
  echo "🧹 Truncating public schema tables before seeding…"
  docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -q -c \
    "DO \$\$ DECLARE r RECORD; BEGIN
       FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public') LOOP
         EXECUTE 'TRUNCATE TABLE '||quote_ident(r.tablename)||' RESTART IDENTITY CASCADE';
       END LOOP;
     END \$\$;"
fi

  # Tolerant seeding:
  # - ON_ERROR_STOP=0 -> don't stop on errors
  # - ON_ERROR_ROLLBACK=on -> when inside a BEGIN/transaction, rollback to a savepoint and continue
  # - \echo and \errverbose help with debugging; we ignore exit code so the script continues
  docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONTAINER" bash -lc '
    set -e
    cat > /tmp/seed_tolerant.sql <<SQL
\\set ON_ERROR_STOP 0
\\set ON_ERROR_ROLLBACK on
\\set ECHO errors
\\errverbose
\\include /tmp/seed.sql
SQL
    psql -U "'"$PG_USER"'" -d "'"$PG_DB"'" -f /tmp/seed_tolerant.sql || true
  '
  echo "✅ Seeding finished (errors, if any, were logged but ignored)."
}


ensure_venv () {
  # pick python
  command -v python >/dev/null || command -v python3 >/dev/null || fail "Python not found on host"
  local py="${PY_EXE:-python3}"; command -v "$py" >/dev/null || py="python"

  # For fast mode (INSTALL_DEPS=0), we DO NOT create a venv or install packages.
  if [[ ! -d "$VENV_PATH" ]]; then
    if [[ "${INSTALL_DEPS}" = "1" ]]; then
      echo "🐍 Creating venv at $VENV_PATH"
      "$py" -m venv "$VENV_PATH"
    else
      fail "Venv missing at $VENV_PATH. Run 'make full' once to set up deps."
    fi
  fi

  if [[ -x "$VENV_PATH/bin/pip" ]]; then
    PIP="$VENV_PATH/bin/pip"; PY="$VENV_PATH/bin/python"
  else
    PIP="$VENV_PATH/Scripts/pip.exe"; PY="$VENV_PATH/Scripts/python.exe"
  fi
  [[ -x "$PIP" && -x "$PY" ]] || fail "venv incomplete at '$VENV_PATH'"

  if [[ "${INSTALL_DEPS}" = "1" ]]; then
    echo "📦 Upgrading pip/setuptools/wheel"
    "$PIP" install --upgrade pip setuptools wheel
    [[ -f "$REQ_FILE" ]] || fail "requirements file not found: $REQ_FILE"
    echo "📦 Installing requirements from $REQ_FILE"
    "$PIP" install -r "$REQ_FILE"
  else
    echo "⏭️  Skipping pip install (fast mode)."
  fi

  # Minimal sanity: ensure FastAPI import works (quiet if you want; I keep it)
  "$PY" - <<'PY'
import fastapi, sys
print("FASTAPI_OK", fastapi.__version__)
PY

  export PY PIP
}

# Derive DATABASE_URL without hard-coding 5432:
# Precedence:
# 1) If DATABASE_URL is set, use as-is.
# 2) Else, inspect the running container's published host port (first TCP port, preferring 5432 if present).
# 3) Else, fallback to localhost:5432 (last resort).
resolve_database_url () {
  if [[ -n "${DATABASE_URL:-}" ]]; then
    echo "ℹ️ DATABASE_URL preset → using as is"
    export DATABASE_URL
    return
  fi
  # Try to derive from container port map
  local ports host_port=""
  ports=$(docker inspect --format='{{range $k,$v := .NetworkSettings.Ports}}{{if $v}}{{printf "%s %s\n" $k (index $v 0).HostPort}}{{end}}{{end}}' "$PG_CONTAINER" 2>/dev/null || true)
  while read -r internal host; do
    [[ -z "$internal" ]] && continue
    if [[ "$internal" == "5432/tcp" && -n "$host" ]]; then host_port="$host"; break; fi
    if [[ -z "$host_port" && -n "$host" ]]; then host_port="$host"; fi
  done <<< "$ports"
  local _user="${PG_USER:-postgres}" _pass="${PGPASSWORD:-postgres}" _db="${PG_DB:-postgres}"
  if [[ -n "$host_port" ]]; then
    DATABASE_URL="postgresql://${_user}:${_pass}@localhost:${host_port}/${_db}"
    echo "ℹ️ DATABASE_URL derived from container mapping: $DATABASE_URL"
  else
    DATABASE_URL="postgresql://${_user}:${_pass}@localhost:5432/${_db}"
    echo "ℹ️ DATABASE_URL fallback: $DATABASE_URL"
  fi
  export DATABASE_URL
}

run_tests () {
  "$PIP" install pytest >/dev/null 2>&1 || true
  "$PY" -m pytest -q
}

run_app () {
  local args=( -m uvicorn "$APP_IMPORT" --reload --host "$HOST" --port "$PORT" )
  if [[ -n "${ENV_FILE}" && -f "$ENV_FILE" ]]; then
    args+=( --env-file "$ENV_FILE" )
  fi

  if [[ "$RUN_DAEMON" == "1" ]]; then
    echo "🚀 Starting app in background → http://$HOST:$PORT"
    # shellcheck disable=SC2086
    nohup "$PY" "${args[@]}" >"$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    show_status
    exit 0
  else
    echo "🚀 Starting app (foreground) → http://$HOST:$PORT"
    exec "$PY" "${args[@]}"
  fi
}


is_running () {
  [[ -f "$PIDFILE" ]] || return 1
  local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" >/dev/null 2>&1
}

kill_app () {
  if is_running; then
    local pid; pid="$(cat "$PIDFILE")"
    echo "🛑 Stopping local app (pid $pid)…"
    kill "$pid" 2>/dev/null || true
    # Give it a moment, then force if needed
    for i in {1..10}; do
      ps -p "$pid" >/dev/null 2>&1 || { rm -f "$PIDFILE"; echo "✅ Stopped"; return 0; }
      sleep 0.2
    done
    echo "⚠️  Forcing kill…"
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "✅ Stopped"
  else
    echo "ℹ️ No local app pid found"
  fi
}

show_status () {
  # 1) PID file path (daemon mode)
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_alive "$pid"; then
      echo "✅ App running (daemon) pid $pid — log: $LOGFILE — http://$HOST:$PORT"
      return 0
    fi
  fi

  # 2) Port-based detection (works for foreground `make fast`)
  local pids; pids="$(pids_by_port)"
  if [[ -n "$pids" ]]; then
    echo "✅ App running (port $PORT) pid(s): $pids — http://$HOST:$PORT"
    return 0
  fi

  # 3) Command-line fallback (uvicorn + APP_IMPORT)
  pids="$(pids_by_cmdline)"
  if [[ -n "$pids" ]]; then
    echo "✅ App running (cmdline match) pid(s): $pids — http://$HOST:$PORT"
    return 0
  fi

  echo "❌ App not running"
}

# Return space-separated PIDs listening on $PORT (lsof or ss), else empty
pids_by_port () {
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    # parse: ... users:(("python",pid=1234,fd=...))
    pids="$(ss -ltnp 2>/dev/null | awk -v p=":$PORT" '
      $4 ~ p && $0 ~ /pid=/ {
        match($0,/pid=([0-9]+)/,m); if (m[1]!="") print m[1]
      }' | sort -u | xargs || true)"
  fi
  echo "$pids"
}

# Return space-separated PIDs by command line match (uvicorn + APP_IMPORT)
pids_by_cmdline () {
  local patt="uvicorn .*${APP_IMPORT//\//\\/}"
  pgrep -f "$patt" 2>/dev/null | xargs || true
}

# True if PID is alive
pid_alive () { ps -p "$1" >/dev/null 2>&1; }

# Kill a list of PIDs nicely, then force if needed
kill_pids () {
  local pids=($@)
  [[ ${#pids[@]} -eq 0 ]] && return 0
  echo "🛑 Stopping app PIDs: ${pids[*]}…"
  kill "${pids[@]}" 2>/dev/null || true
  for _ in {1..20}; do
    sleep 0.2
    local alive=()
    for pid in "${pids[@]}"; do pid_alive "$pid" && alive+=("$pid"); done
    [[ ${#alive[@]} -eq 0 ]] && { echo "✅ Stopped."; return 0; }
    pids=("${alive[@]}")
  done
  echo "⚠️  Forcing kill: ${pids[*]}"
  kill -9 "${pids[@]}" 2>/dev/null || true
  echo "✅ Stopped."
}

# Enhanced stop: PID file → port → cmdline
kill_app () {
  local pids=""
  # 1) PID file
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_alive "$pid"; then
      kill_pids "$pid"
      rm -f "$PIDFILE"
      return 0
    fi
    rm -f "$PIDFILE" 2>/dev/null || true
  fi
  # 2) Port-based
  pids="$(pids_by_port)"
  if [[ -n "$pids" ]]; then
    kill_pids $pids
    return 0
  fi
  # 3) Command-line match
  pids="$(pids_by_cmdline)"
  if [[ -n "$pids" ]]; then
    kill_pids $pids
    return 0
  fi
  echo "ℹ️ No local app pid found"
}

# ---------- Commands ----------
cmd_full () {
  echo "▶ MODE=full (db up → (reset?) → schema → seed → deps → (tests?) → run)"
  ensure_db
  resolve_database_url
  [[ "${RESET_PUBLIC:-0}" == "1" ]] && reset_public
  apply_schema
  apply_seed
  ensure_venv
  # Run tests only if you want them in full; flip default with RUN_TESTS in .dbstack.env
  if [[ "${RUN_TESTS:-0}" == "1" ]]; then
    run_tests
  fi
  run_app
}

cmd_fast () {
  echo "▶ MODE=fast (db up → run) — NO schema/seed/tests, NO installs"
  ensure_db
  resolve_database_url
  INSTALL_DEPS=0 ensure_venv
  run_app
}

cmd_schema () {
  echo "▶ MODE=schema (apply schema; RESET_PUBLIC respected)"
  ensure_db
  resolve_database_url
  [[ "${RESET_PUBLIC:-0}" == "1" ]] && reset_public
  apply_schema
}

cmd_seed () {
  echo "▶ MODE=seed (tolerant)"
  ensure_db
  resolve_database_url
  apply_seed    # tolerant now
}

cmd_seed_run () {
  echo "▶ MODE=seed-run (seed → run, tolerant)"
  ensure_db
  resolve_database_url
  apply_seed    # tolerant now
  INSTALL_DEPS=0 ensure_venv
  run_app
}

cmd_tests () {
  echo "▶ MODE=tests (deps → pytest)"
  ensure_db
  resolve_database_url
  ensure_venv
  run_tests
}

cmd_start () {
  echo "▶ MODE=start (daemon fast) — NO schema/seed/tests, NO installs"
  ensure_db
  resolve_database_url
  INSTALL_DEPS=0 ensure_venv   # <- skip pip/requirements like 'fast'
  RUN_DAEMON=1 run_app         # <- background with PID file
}
# Improved stop: kill local app if running, then (optionally) docker down
cmd_stop () { kill_app; }

# Only docker down (keeps local app alone)
cmd_stop_docker () { compose down; }

cmd_status () { show_status; }
cmd_logs () { [[ -f "$LOGFILE" ]] && tail -n 200 -f "$LOGFILE" || echo "No log yet: $LOGFILE"; }

cmd_schema_seed () {
  echo "▶ MODE=schema_seed (schema → seed, tolerant)"
  ensure_db
  resolve_database_url
  [[ "${RESET_PUBLIC:-0}" == "1" ]] && reset_public
  apply_schema
  apply_seed
}

cmd_start_docker () {
  echo "▶ MODE=start-docker (tolerant)"

  # Which name to look for:
  # - If you removed `container_name` from compose, use the *service* name 'db' (recommended).
  # - If you kept a fixed container_name, set PG_CONTAINER to that exact name in .dbstack.env.
  local DB_NAME="${PG_CONTAINER:-db}"

  # 1) If DB container is already running -> keep it
  if docker ps --format '{{.Names}}' | grep -Fxq "$DB_NAME"; then
    echo "ℹ️ DB container '$DB_NAME' already running; skipping DB start."
  # 2) If it exists but stopped -> start it
  elif docker ps -a --format '{{.Names}}' | grep -Fxq "$DB_NAME"; then
    echo "ℹ️ Starting existing DB container '$DB_NAME'…"
    docker start "$DB_NAME" >/dev/null
  # 3) Else start it via compose (db service only)
  else
    echo "🧩 Bringing up DB via compose ($COMPOSE_FILE)"
    docker compose -f "$COMPOSE_FILE" up -d --no-recreate db
  fi

  # 4) Bring up the rest (idempotent; won’t error if already up)
  #    --no-recreate avoids churn; --remove-orphans quiets orphan warnings.
  docker compose -f "$COMPOSE_FILE" up -d --no-recreate --remove-orphans api

  echo "✅ Docker stack is up (db/redis/minio/api)."
}

#cmd_start_docker () {
 # echo "▶ MODE=start-docker (tolerant)"
  # (Your tolerant logic here; example:)
  #docker compose -f "$COMPOSE_FILE" up -d --no-recreate --remove-orphans
  #echo "✅ Docker stack is up."
#}

usage () {
  cat <<EOF
Usage: $0 <command>

Non-docker app (uvicorn on host):
  fast          DB up → run (NO schema/seed/tests, NO installs)
  full          DB up → (reset?) → schema → seed → (tests?) → run
  schema        Apply schema (RESET_PUBLIC honored)
  schema_seed   Apply schema then seed (tolerant; continues on errors)
  seed          Seed only (tolerant)
  seed-run      Seed (tolerant) then run (NO installs)
  tests         Run pytest only
  start         Fast run in background (daemon)
  status        Show app status (daemon or foreground)
  logs          Tail daemon log
  stop          Stop ONLY local uvicorn (daemon or foreground)

Docker app:
  start-docker  Start db, redis, minio, api
  stop-docker   Stop all docker services
  api-rebuild   Rebuild API image then (re)start API
  api-logs      Tail API logs
EOF
}

cmd="${1:-}"
case "$cmd" in
  full)         shift; cmd_full "$@";;
  fast)         shift; cmd_fast "$@";;
  schema)       shift; cmd_schema "$@";;
  schema_seed)  shift; cmd_schema_seed "$@";;
  seed)         shift; cmd_seed "$@";;
  seed-run)     shift; cmd_seed_run "$@";;
  tests)        shift; cmd_tests "$@";;
  start)        shift; cmd_start "$@";;
  status)       shift; cmd_status "$@";;
  logs)         shift; cmd_logs "$@";;
  stop)         shift; cmd_stop "$@";;

  # ← Add this new arm:
  start-docker) shift; cmd_start_docker "$@";;

  stop-docker)  shift; docker compose -f "$COMPOSE_FILE" down;;
  ""|-h|--help|help) usage;;
  *) echo "Unknown command: $cmd"; usage; exit 1;;
esac
