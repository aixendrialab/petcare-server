#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------
# Configuration (env with sensible defaults)
# ---------------------------------------

# Load optional project env
[[ -f ./.dbstack.env ]] && source ./.dbstack.env || true

# Compose file (auto if not set)
COMPOSE_FILE="${COMPOSE_FILE:-./docker-compose.yml}"

# Postgres & schema/seed
PG_CONTAINER="${PG_CONTAINER:-db}"     # compose **service** name, not a fixed container_name
PG_DB="${PG_DB:-petcare}"
PG_USER="${PG_USER:-postgres}"
PGPASSWORD="${PGPASSWORD:-postgres}"
PG_READY_TIMEOUT="${PG_READY_TIMEOUT:-60}"

SCHEMA_FILE="${SCHEMA_FILE:-./schema.sql}"
SEED_FILE="${SEED_FILE:-./seed.sql}"
RESET_PUBLIC="${RESET_PUBLIC:-0}"      # 1 = drop/recreate public schema before schema
SEED_TRUNCATE="${SEED_TRUNCATE:-0}"    # 1 = TRUNCATE all public tables before seeding

# App (non-docker)
PY_EXE="${PY_EXE:-python3}"
VENV_PATH="${VENV_PATH:-.venv}"
REQ_FILE="${REQ_FILE:-./requirements.txt}"
APP_IMPORT="${APP_IMPORT:-app.main:app}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8001}"
ENV_FILE="${ENV_FILE:-./env}"

# Behavior knobs
INSTALL_DEPS="${INSTALL_DEPS:-1}"      # fast/start set this to 0 on the fly
RUN_DAEMON="${RUN_DAEMON:-0}"

# Derived
RUN_DIR="${RUN_DIR:-.run}"
PIDFILE="$RUN_DIR/uvicorn.pid"
LOGFILE="$RUN_DIR/uvicorn.log"
DB_MODE="docker"                       # or "external" (set dynamically)

# ---------------------------------------
# Utilities
# ---------------------------------------

fail () { echo "❌ $*" >&2; exit 1; }
compose () { docker compose -f "$COMPOSE_FILE" "$@"; }

# Python helpers for tiny parsing tasks
py_cmd() { command -v python3 >/dev/null 2>&1 && echo python3 || echo python; }
py_run() { "$(py_cmd)" - "$@"; }

parse_db_url_env () {
  [[ -n "${DATABASE_URL:-}" ]] || return 1
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

db_alive_via_url () {
  [[ -n "${DATABASE_URL:-}" ]] || return 1
  # Prefer auth-checked psql
  if command -v psql >/dev/null 2>&1; then
    eval "$(parse_db_url_env | sed 's/^/export /')" || return 1
    if [[ -n "${DBP:-}" ]]; then
      PGPASSWORD="$DBP" psql -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -t -q -c "select 1" >/dev/null 2>&1 && return 0
    else
      psql                -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -t -q -c "select 1" >/dev/null 2>&1 && return 0
    fi
  fi
  # TCP fallback (no auth)
  py_run <<'PY'
import os, sys, socket
from urllib.parse import urlparse
u = os.environ.get("DATABASE_URL","")
if not u: sys.exit(1)
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

# Discover host port for service:5432 and compose DATABASE_URL
compose_database_url_from_mapping () {
  # Try to read host:container mapping for 5432
  local map hostport
  map=$(compose port "$PG_CONTAINER" 5432 2>/dev/null || true)
  hostport=$(awk -F: 'NF{print $2; exit}' <<<"$map")
  [[ -n "$hostport" ]] || return 1
  local _user="${PG_USER:-postgres}" _pass="${PGPASSWORD:-postgres}" _db="${PG_DB:-postgres}"
  DATABASE_URL="postgresql://${_user}:${_pass}@localhost:${hostport}/${_db}"
  export DATABASE_URL
  echo "ℹ️ DATABASE_URL derived from compose mapping → $DATABASE_URL"
}

resolve_database_url () {
  if [[ -n "${DATABASE_URL:-}" ]] && db_alive_via_url; then
    echo "ℹ️ DATABASE_URL preset & reachable; using as-is."
    DB_MODE="external"; export DB_MODE
    return 0
  fi
  # Try to form from compose mapping
  if compose_database_url_from_mapping; then
    return 0
  fi
  # Fallback (works for many local installs)
  local _user="${PG_USER:-postgres}" _pass="${PGPASSWORD:-postgres}" _db="${PG_DB:-postgres}"
  DATABASE_URL="postgresql://${_user}:${_pass}@localhost:5432/${_db}"
  export DATABASE_URL
  echo "ℹ️ DATABASE_URL fallback → $DATABASE_URL"
}

# Wait for DB (docker service)
wait_pg () {
  local end=$((SECONDS+PG_READY_TIMEOUT))
  echo "⏳ Waiting for Postgres in service '$PG_CONTAINER'…"
  until compose exec -T "$PG_CONTAINER" \
    psql -U "$PG_USER" -d postgres -t -q -c "select 1" >/dev/null 2>&1; do
    [[ $SECONDS -ge $end ]] && fail "Postgres not ready in time."
    sleep 2
  done
}

ensure_db () {
  echo "🧩 Ensuring Postgres…"
  # External DB → skip docker
  if [[ -n "${DATABASE_URL:-}" ]] && db_alive_via_url; then
    echo "✅ DATABASE_URL reachable; skipping docker DB."
    DB_MODE="external"; export DB_MODE
    return 0
  fi

  DB_MODE="docker"; export DB_MODE
  compose up -d --no-recreate "$PG_CONTAINER"
  wait_pg

  # Ensure logical DB exists
  echo "🗃️ Ensuring database '$PG_DB' exists…"
  local exists
  exists=$(compose exec -T "$PG_CONTAINER" \
    psql -U "$PG_USER" -d postgres -t -q -c "SELECT 1 FROM pg_database WHERE datname='${PG_DB}';" | tr -d '[:space:]')
  if [[ "$exists" != "1" ]]; then
    compose exec -T "$PG_CONTAINER" \
      psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE \"$PG_DB\";"
  fi

  # Refresh DATABASE_URL from live mapping if we didn't have one
  [[ -z "${DATABASE_URL:-}" ]] && compose_database_url_from_mapping || true
}

reset_public () {
  echo "♻️ Resetting schema 'public'…"
  if [[ "$DB_MODE" == "docker" ]]; then
    compose exec -T "$PG_CONTAINER" \
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
  else
    eval "$(parse_db_url_env | sed 's/^/export /')" || fail "Bad DATABASE_URL for reset_public"
    [[ -n "${DBP:-}" ]] && export PGPASSWORD="$DBP"
    psql -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$
BEGIN
  EXECUTE 'DROP SCHEMA IF EXISTS public CASCADE';
  EXECUTE 'CREATE SCHEMA public AUTHORIZATION CURRENT_USER';
  EXECUTE 'GRANT ALL ON SCHEMA public TO CURRENT_USER';
  EXECUTE 'GRANT ALL ON SCHEMA public TO PUBLIC';
END
$$;
SQL
  fi
}

apply_schema () {
  [[ -f "$SCHEMA_FILE" ]] || fail "Schema file not found: $SCHEMA_FILE"
  echo "📜 Applying schema…"
  if [[ "$DB_MODE" == "docker" ]]; then
    compose exec -T "$PG_CONTAINER" \
      psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f - < "$SCHEMA_FILE"
  else
    eval "$(parse_db_url_env | sed 's/^/export /')" || fail "Bad DATABASE_URL for schema"
    [[ -n "${DBP:-}" ]] && export PGPASSWORD="$DBP"
    psql -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"
  fi
}

apply_seed () {
  [[ -f "$SEED_FILE" ]] || fail "Seed file not found: $SEED_FILE"
  echo "🌱 Seeding data (tolerant)…"

  if [[ "${SEED_TRUNCATE:-0}" == "1" ]]; then
    echo "🧹 Truncating public tables before seeding…"
    if [[ "$DB_MODE" == "docker" ]]; then
      compose exec -T "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -q -c \
        "DO \$\$ DECLARE r RECORD; BEGIN
           FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public') LOOP
             EXECUTE 'TRUNCATE TABLE '||quote_ident(r.tablename)||' RESTART IDENTITY CASCADE';
           END LOOP;
         END \$\$;"
    else
      eval "$(parse_db_url_env | sed 's/^/export /')" || fail "Bad DATABASE_URL for truncation"
      [[ -n "${DBP:-}" ]] && export PGPASSWORD="$DBP"
      psql -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -v ON_ERROR_STOP=1 -q -c \
        "DO \$$ DECLARE r RECORD; BEGIN
           FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public') LOOP
             EXECUTE 'TRUNCATE TABLE '||quote_ident(r.tablename)||' RESTART IDENTITY CASCADE';
           END LOOP;
         END $$;"
    fi
  fi

  if [[ "$DB_MODE" == "docker" ]]; then
    {
      echo '\set ON_ERROR_STOP 0'
      echo '\set ON_ERROR_ROLLBACK on'
      echo '\set ECHO errors'
      echo '\errverbose'
      cat "$SEED_FILE"
    } | compose exec -T "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -f -
  else
    eval "$(parse_db_url_env | sed 's/^/export /')" || fail "Bad DATABASE_URL for seed"
    [[ -n "${DBP:-}" ]] && export PGPASSWORD="$DBP"
    {
      echo '\set ON_ERROR_STOP 0'
      echo '\set ON_ERROR_ROLLBACK on'
      echo '\set ECHO errors'
      echo '\errverbose'
      cat "$SEED_FILE"
    } | psql -h "$DBH" -p "$DBPORT" -U "$DBU" -d "$DBNAME" -f - || true
  fi

  echo "✅ Seeding finished (errors, if any, were logged but ignored)."
}

# Venv & app
ensure_venv () {
  local py="${PY_EXE:-python3}"; command -v "$py" >/dev/null 2>&1 || py="python"
  if [[ ! -d "$VENV_PATH" ]]; then
    [[ "${INSTALL_DEPS}" = "1" ]] || fail "Venv missing at $VENV_PATH. Run 'make full' once to set up deps."
    echo "🐍 Creating venv at $VENV_PATH"
    "$py" -m venv "$VENV_PATH"
  fi
  local PIP PYBIN
  if [[ -x "$VENV_PATH/bin/pip" ]]; then
    PIP="$VENV_PATH/bin/pip"; PYBIN="$VENV_PATH/bin/python"
  else
    PIP="$VENV_PATH/Scripts/pip.exe"; PYBIN="$VENV_PATH/Scripts/python.exe"
  fi
  [[ -x "$PIP" && -x "$PYBIN" ]] || fail "venv incomplete at '$VENV_PATH'"

  if [[ "${INSTALL_DEPS}" = "1" ]]; then
    echo "📦 Upgrading pip/setuptools/wheel"
    "$PIP" install --upgrade pip setuptools wheel
    [[ -f "$REQ_FILE" ]] || fail "requirements file not found: $REQ_FILE"
    echo "📦 Installing requirements from $REQ_FILE"
    "$PIP" install -r "$REQ_FILE"
  else
    echo "⏭️  Skipping pip install (fast mode)."
  fi

  # sanity
  "$PYBIN" - <<'PY'
import fastapi
print("FASTAPI_OK", fastapi.__version__)
PY
  export PY="$PYBIN" PIP
}

run_app () {
  mkdir -p "$RUN_DIR"
  local uv_args=( -m uvicorn "$APP_IMPORT" --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips "*" )
  if [[ -f "$ENV_FILE" ]]; then
    export $(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$ENV_FILE" | xargs) || true
  fi
  if [[ "${RUN_DAEMON}" = "1" ]]; then
    echo "🚀 Starting app in background → http://$HOST:$PORT"
    nohup "$PY" "${uv_args[@]}" >"$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "✅ App running (pid $(cat "$PIDFILE")) — log: $LOGFILE"
  else
    echo "🚀 Starting app (foreground) → http://$HOST:$PORT"
    exec "$PY" "${uv_args[@]}"
  fi
}

# Process helpers for stop/status
pids_by_port () {
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p && /pid=/{match($0,/pid=([0-9]+)/,m); if(m[1]!="") print m[1]}' | sort -u | xargs || true)"
  fi
  echo "$pids"
}
pids_by_cmdline () { pgrep -f "uvicorn .*${APP_IMPORT//\//\\/}" 2>/dev/null | xargs || true; }
pid_alive () { ps -p "${1:-0}" >/dev/null 2>&1; }
kill_pids () {
  local pids=($@); [[ ${#pids[@]} -eq 0 ]] && return 0
  echo "🛑 Stopping app PIDs: ${pids[*]}…"; kill "${pids[@]}" 2>/dev/null || true
  for _ in {1..20}; do
    sleep 0.2; local alive=(); for pid in "${pids[@]}"; do pid_alive "$pid" && alive+=("$pid"); done
    [[ ${#alive[@]} -eq 0 ]] && { echo "✅ Stopped."; return 0; }
    pids=("${alive[@]}")
  done
  echo "⚠️  Forcing kill: ${pids[*]}"; kill -9 "${pids[@]}" 2>/dev/null || true; echo "✅ Stopped."
}
kill_app () {
  local pids=""
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_alive "$pid"; then kill_pids "$pid"; rm -f "$PIDFILE"; return 0; fi
    rm -f "$PIDFILE" 2>/dev/null || true
  fi
  pids="$(pids_by_port)"; [[ -n "$pids" ]] && { kill_pids $pids; return 0; }
  pids="$(pids_by_cmdline)"; [[ -n "$pids" ]] && { kill_pids $pids; return 0; }
  echo "ℹ️ No local app pid found"
}
show_status () {
  if [[ -f "$PIDFILE" ]]; then
    local pid; pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_alive "$pid"; then
      echo "✅ App running (daemon) pid $pid — log: $LOGFILE — http://$HOST:$PORT"; return 0
    fi
  fi
  local pids; pids="$(pids_by_port)"
  if [[ -n "$pids" ]]; then echo "✅ App running (port $PORT) pid(s): $pids — http://$HOST:$PORT"; return 0; fi
  pids="$(pids_by_cmdline)"
  if [[ -n "$pids" ]]; then echo "✅ App running (cmdline match) pid(s): $pids — http://$HOST:$PORT"; return 0; fi
  echo "❌ App not running"
}

# ---------------------------------------
# Commands
# ---------------------------------------

usage () {
  cat <<EOF
Usage: $0 <command>

Non-docker app (Uvicorn on host):
  fast          DB up → run (NO schema/seed/tests, NO installs)
  full          DB up → (reset?) → schema → seed → (tests?) → run (installs deps)
  schema        Apply schema (RESET_PUBLIC honored)
  schema_seed   Apply schema then seed (tolerant)
  seed          Seed only (tolerant; continues on errors)
  seed-run      Seed (tolerant) then run (NO installs)
  tests         Run pytest only
  start         Fast run in background (daemon)
  status        Show app status (daemon or foreground)
  logs          Tail daemon log
  stop          Stop ONLY local uvicorn (daemon or foreground)
  info          Show resolved settings (compose/db/url)

Docker app:
  start-docker  Start all compose services (db/api/redis/minio)
  stop-docker   Stop all compose services
EOF
}

cmd_fast () {
  echo "▶ MODE=fast (db up → run) — NO schema/seed/tests, NO installs"
  ensure_db
  resolve_database_url
  INSTALL_DEPS=0 ensure_venv
  run_app
}

cmd_start () {
  echo "▶ MODE=start (daemon fast) — NO schema/seed/tests, NO installs"
  ensure_db
  resolve_database_url
  INSTALL_DEPS=0 ensure_venv
  RUN_DAEMON=1 run_app
}

cmd_full () {
  echo "▶ MODE=full (db up → (reset?) → schema → seed → deps → (tests?) → run)"
  ensure_db
  resolve_database_url
  [[ "${RESET_PUBLIC}" == "1" ]] && reset_public
  apply_schema
  apply_seed
  INSTALL_DEPS=1 ensure_venv
  run_app
}

cmd_schema () {
  echo "▶ MODE=schema"
  ensure_db
  resolve_database_url
  [[ "${RESET_PUBLIC}" == "1" ]] && reset_public
  apply_schema
}

cmd_schema_seed () {
  echo "▶ MODE=schema_seed (schema → seed, tolerant)"
  ensure_db
  resolve_database_url
  [[ "${RESET_PUBLIC}" == "1" ]] && reset_public
  apply_schema
  apply_seed
}

cmd_seed () {
  echo "▶ MODE=seed (tolerant)"
  ensure_db
  resolve_database_url
  apply_seed
}

cmd_seed_run () {
  echo "▶ MODE=seed-run (seed → run, tolerant)"
  ensure_db
  resolve_database_url
  apply_seed
  INSTALL_DEPS=0 ensure_venv
  run_app
}

cmd_tests () {
  echo "▶ MODE=tests"
  ensure_db
  resolve_database_url
  INSTALL_DEPS=0 ensure_venv
  "$PY" -m pytest -q
}

cmd_status () { show_status; }
cmd_logs ()   { [[ -f "$LOGFILE" ]] && tail -f "$LOGFILE" || echo "ℹ️ No daemon log at $LOGFILE"; }
cmd_stop ()   { kill_app; }
cmd_info ()   {
  echo "----- run-stack info -----"
  echo "COMPOSE_FILE : ${COMPOSE_FILE}"
  echo "PG_CONTAINER : ${PG_CONTAINER}"
  echo "DB_MODE      : ${DB_MODE}"
  echo "PG_DB        : ${PG_DB}"
  echo "PG_USER      : ${PG_USER}"
  echo "ENV_FILE     : ${ENV_FILE}"
  echo "VENV_PATH    : ${VENV_PATH}"
  echo "APP_IMPORT   : ${APP_IMPORT}"
  echo "HOST:PORT    : ${HOST}:${PORT}"
  echo "DATABASE_URL : ${DATABASE_URL:-<unset>}"
  echo "--------------------------"
}

cmd_start_docker () {
  echo "▶ MODE=start-docker (compose up all)"
  compose up -d --remove-orphans
}

cmd_stop_docker () {
  echo "▶ MODE=stop-docker"
  compose down
}

# ---------------------------------------
# Dispatcher
# ---------------------------------------

cmd="${1:-}"
case "$cmd" in
  fast)         shift; cmd_fast "$@";;
  start)        shift; cmd_start "$@";;
  full)         shift; cmd_full "$@";;
  schema)       shift; cmd_schema "$@";;
  schema_seed)  shift; cmd_schema_seed "$@";;
  seed)         shift; cmd_seed "$@";;
  seed-run)     shift; cmd_seed_run "$@";;
  tests)        shift; cmd_tests "$@";;
  status)       shift; cmd_status "$@";;
  logs)         shift; cmd_logs "$@";;
  stop)         shift; cmd_stop "$@";;
  info)         shift; cmd_info "$@";;
  start-docker) shift; cmd_start_docker "$@";;
  stop-docker)  shift; cmd_stop_docker "$@";;
  ""|-h|--help|help) usage;;
  *) echo "Unknown command: $cmd"; usage; exit 1;;
esac
