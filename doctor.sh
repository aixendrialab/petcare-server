#!/usr/bin/env bash
# save as doctor.sh, then: bash doctor.sh
set -euo pipefail

echo "=== SHELL & OS ==="
echo "whoami: $(whoami)"
uname -a || true
cat /etc/os-release 2>/dev/null || true

echo "=== PATH & tools ==="
echo "which bash: $(command -v bash || echo NA)"
echo "which make: $(command -v make || echo NA)"; make --version | head -n1 || true
echo "which python3: $(command -v python3 || echo NA)"; python3 --version || true
echo "which pip3: $(command -v pip3 || echo NA)"; pip3 --version || true
echo "which docker: $(command -v docker || echo NA)"; docker version --format '{{.Server.Version}}' || true
echo "which docker-compose: $(command -v docker-compose || echo NA)"; docker compose version || true

echo "=== Docker socket & context ==="
ls -l /var/run/docker.sock || true
docker context ls || true
echo "Groups: $(id -nG)"

echo "=== WSL (if on Windows) ==="
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo "Looks like WSL. Ensure Docker Desktop → Settings → Resources → WSL Integration has this distro enabled."
fi

echo "=== Line endings check ==="
if command -v file >/dev/null 2>&1; then
  file -b run-stack.sh 2>/dev/null || true
  file -b makefile 2>/dev/null || true
fi

echo "=== Venv layout ==="
echo "VENV_PATH: ${VENV_PATH:-.venv}"
test -x .venv/bin/python && echo "Found .venv/bin/python"
test -x .venv/Scripts/python.exe && echo "Found .venv/Scripts/python.exe"

echo "=== Compose services (if any) ==="
docker compose ps 2>/dev/null || true

echo "=== DONE ==="
