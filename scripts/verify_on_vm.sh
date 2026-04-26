#!/bin/bash
# Run on the VM after bootstrap (or when debugging). Checks app, nginx, venv, generators.
# Usage: sudo bash /path/to/verify_on_vm.sh   (or copy from repo: scripts/verify_on_vm.sh)
set -euo pipefail

if [ ! -f /opt/app/.env ]; then
  echo "FATAL: /opt/app/.env missing — run remote bootstrap (Terraform remote-exec) first." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a
. /opt/app/.env
set +a
PORT="${APP_PORT:-8000}"

echo "== verify_on_vm: $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
for f in /opt/app/app/main.py /opt/app/app/restocking_file_generator.py /opt/app/app/job_status_generator.py; do
  test -f "$f" || {
    echo "FATAL: missing $f" >&2
    exit 1
  }
done
test -x /opt/app/.venv/bin/python
test -x /opt/app/.venv/bin/uvicorn

echo "---- python: import app module ----"
# Works when run as root (bootstrap) or as a user with sudo; prefer runuser on root
if [ "$(id -u)" -eq 0 ]; then
  runuser -u appuser -- /bin/bash -c 'cd /opt/app/app && /opt/app/.venv/bin/python -c "from main import app; print(\"OK main:app\")"'
else
  sudo -u appuser bash -c 'cd /opt/app/app && /opt/app/.venv/bin/python -c "from main import app; print(\"OK main:app\")"'
fi

echo "---- systemd: active units / timers ----"
systemctl is-active app >/dev/null
systemctl is-active nginx >/dev/null
for u in app nginx restocking-generator.timer job-status-generator.timer dtr-cleanup.timer; do
  systemctl is-active --quiet "$u" && echo "  $u: active" || {
    echo "FATAL: $u not active" >&2
    systemctl --no-pager -l status "$u" || true
    exit 1
  }
done

echo "---- HTTP: app (port ${PORT}) and nginx:80 /health ----"
curl -fsS --connect-timeout 5 --max-time 15 "http://127.0.0.1:${PORT}/health"
echo ""
curl -fsS --connect-timeout 5 --max-time 15 "http://127.0.0.1/health"
echo ""

echo "verify_on_vm: all checks passed"
