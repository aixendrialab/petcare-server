#!/usr/bin/env bash
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"
set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:-.dbstack.env}"
if [[ -f "$CONFIG_FILE" ]]; then
  set -a; . "$CONFIG_FILE"; set +a
else
  echo "ERROR: Config file not found: $CONFIG_FILE" >&2; exit 1
fi

PG_DB="${PG_DB:-tos}"
PG_USER="${PG_USER:-postgres}"
PG_READY_TIMEOUT="${PG_READY_TIMEOUT:-60}"
SCHEMA_FILE="${SCHEMA_FILE:-./app/sql/schema.sql}"
SEED_FILE="${SEED_FILE:-./app/sql/seed.sql}"
RESET_PUBLIC="${RESET_PUBLIC:-0}"
RUN_TESTS="${RUN_TESTS:-1}"
PY_EXE="${PY_EXE:-python3}"
VENV_PATH="${VENV_PATH:-.venv}"
REQ_FILE="${REQ_FILE:-./requirements.txt}"
APP_IMPORT="${APP_IMPORT:-app.main:app}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
ENV_FILE="${ENV_FILE:-}"
PGPASSWORD="${PGPASSWORD:-postgres}"
DATABASE_URL="${DATABASE_URL:-postgresql://$PG_USER:$PGPASSWORD@localhost:5432/$PG_DB}"

info(){ echo -e "$1"; }
fail(){ echo "ERROR: $1" >&2; exit 1; }

command -v docker >/dev/null || fail "Docker not found."

PG_CONT_ID=""
if [[ "${PG_CONTAINER:-}" =~ ^compose:(.+)$ ]]; then
  SVC="${BASH_REMATCH[1]}"
  info "🧩 Bringing up docker compose service '$SVC'…"
  docker compose up -d "$SVC"
  PG_CONT_ID="$(docker compose ps -q "$SVC")"
  [[ -n "$PG_CONT_ID" ]] || fail "Could not get container id for compose service '$SVC'."
else
  PG_CONT_ID="${PG_CONTAINER:-}"
  [[ -n "$PG_CONT_ID" ]] || fail "PG_CONTAINER not set."
  docker ps --format '{{.Names}}' | grep -Fxq "$PG_CONT_ID" || fail "Container '$PG_CONT_ID' not running."
fi

[[ -f "$SCHEMA_FILE" ]] || fail "Schema file not found: $SCHEMA_FILE"
[[ -f "$SEED_FILE"   ]] || fail "Seed file not found:   $SEED_FILE"

end=$((SECONDS+PG_READY_TIMEOUT))
info "⏳ Waiting for Postgres in '$PG_CONT_ID'…"
until docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONT_ID" \
  psql -U "$PG_USER" -d postgres -t -q -c "select 1" >/dev/null 2>&1; do
  [[ $SECONDS -ge $end ]] && fail "Postgres not ready in time."
  sleep 2
done

info "🗃️ Ensuring database '$PG_DB' exists…"
EXISTS=$(docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONT_ID" \
  psql -U "$PG_USER" -d postgres -t -q -c "SELECT 1 FROM pg_database WHERE datname='${PG_DB}';" | tr -d '[:space:]')
if [[ -z "$EXISTS" ]]; then
  docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONT_ID" \
    psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE \"$PG_DB\";"
fi

# Reset public (optional) — safe heredoc prevents $$ expansion, and we use CURRENT_USER instead of $PG_USER
if [[ "$RESET_PUBLIC" == "1" ]]; then
  info "♻️ Resetting schema 'public'…"
  docker exec -i -e "PGPASSWORD=$PGPASSWORD" "$PG_CONT_ID" \
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
fi

info "📜 Applying schema…"
docker cp "$SCHEMA_FILE" "$PG_CONT_ID:/tmp/schema.sql"
docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONT_ID" \
  psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f /tmp/schema.sql

info "🌱 Seeding data…"
docker cp "$SEED_FILE" "$PG_CONT_ID:/tmp/seed.sql"
docker exec -e "PGPASSWORD=$PGPASSWORD" "$PG_CONT_ID" \
  psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -f /tmp/seed.sql

command -v "$PY_EXE" >/dev/null || fail "Python not found: $PY_EXE"

if [[ ! -d "$VENV_PATH" ]]; then
  info "🐍 Creating venv at $VENV_PATH …"
  "$PY_EXE" -m venv "$VENV_PATH" || fail "venv creation failed"
fi

if [[ -x "$VENV_PATH/bin/pip" ]]; then
  PIP="$VENV_PATH/bin/pip"; PY="$VENV_PATH/bin/python"
else
  PIP="$VENV_PATH/Scripts/pip.exe"; PY="$VENV_PATH/Scripts/python.exe"
fi
[[ -x "$PIP" && -x "$PY" ]] || fail "venv incomplete at '$VENV_PATH'"

if [[ -f "$REQ_FILE" ]]; then
  info "📦 Installing requirements …"
  "$PIP" install -r "$REQ_FILE"
fi

if [[ "$RUN_TESTS" == "1" && -d "tests" ]]; then
  info "🧪 Running tests …"
  "$PIP" install pytest >/dev/null 2>&1 || true
  "$PY" -m pytest -q
fi

export DATABASE_URL
ARGS=( -m uvicorn "$APP_IMPORT" --reload --host "$HOST" --port "$PORT" )
[[ -n "${ENV_FILE}" && -f "$ENV_FILE" ]] && ARGS+=( --env-file "$ENV_FILE" )

info "🚀 Starting uvicorn → http://$HOST:$PORT"
exec "$PY" "${ARGS[@]}"
