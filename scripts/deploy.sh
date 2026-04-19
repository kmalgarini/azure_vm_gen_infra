#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# deploy.sh — code-only update helper (no infra change)
#
# Usage:
#   ./scripts/deploy.sh <public_ip> [admin_username] [ssh_key_path]
#
# Example:
#   ./scripts/deploy.sh 20.1.2.3
#   ./scripts/deploy.sh 20.1.2.3 azureuser ~/.ssh/id_rsa
# ---------------------------------------------------------------------------

set -euo pipefail

PUBLIC_IP="${1:?Usage: $0 <public_ip> [admin_username] [ssh_key_path]}"
ADMIN_USER="${2:-azureuser}"
SSH_KEY="${3:-$HOME/.ssh/id_rsa}"

SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=10"

echo "→ Connecting to ${ADMIN_USER}@${PUBLIC_IP} ..."

ssh $SSH_OPTS "${ADMIN_USER}@${PUBLIC_IP}" bash -s <<'REMOTE'
set -euo pipefail

echo "→ Pulling latest code ..."
cd /opt/app
sudo git pull

echo "→ Installing dependencies ..."
sudo /opt/app/.venv/bin/pip install --quiet -r requirements.txt

echo "→ Restarting app service ..."
sudo systemctl restart app

echo "→ Checking service status ..."
sleep 2
systemctl is-active --quiet app && echo "✓ app service is running"
journalctl -u app -n 10 --no-pager
REMOTE

echo "✓ Deployment complete — app updated at http://${PUBLIC_IP}"
