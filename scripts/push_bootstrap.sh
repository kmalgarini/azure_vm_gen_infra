#!/bin/bash
# Run the same two steps as Terraform null_resource: wait for cloud-init, then app bootstrap.
# Use when: run_remote_bootstrap=false, null_resource failed, or you need to re-run by hand.
set -euo pipefail
IP="${1:-}"
KEY="${2:-$HOME/.ssh/id_rsa}"
USER="${3:-azureuser}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TFDIR="${ROOT_DIR}/terraform"
WAIT="${ROOT_DIR}/scripts/remote_wait_cloudinit.sh"
RENDERED="${TFDIR}/remote_bootstrap.rendered.sh"
if [ -z "$IP" ]; then
  echo "usage: $0 <vm-public-ip> [ssh_private_key] [user]" >&2
  echo "  Or:  make bootstrap-ssh   (uses terraform output for IP)" >&2
  exit 1
fi
if [ ! -f "$RENDERED" ]; then
  echo "ERROR: $RENDERED missing. Run: cd terraform && terraform apply (creates local_file for rendered bootstrap)." >&2
  exit 1
fi
if [ ! -f "$WAIT" ]; then
  echo "ERROR: $WAIT missing" >&2
  exit 1
fi
if [ ! -f "$KEY" ]; then
  echo "ERROR: SSH key not found: $KEY" >&2
  exit 1
fi
set -x
scp -i "$KEY" -o "StrictHostKeyChecking=accept-new" "$WAIT" "$USER@$IP:/tmp/remote_wait_cloudinit.sh"
scp -i "$KEY" -o "StrictHostKeyChecking=accept-new" "$RENDERED" "$USER@$IP:/tmp/remote_bootstrap.sh"
ssh -i "$KEY" -o "StrictHostKeyChecking=accept-new" "$USER@$IP" \
  'chmod +x /tmp/remote_wait_cloudinit.sh /tmp/remote_bootstrap.sh && /tmp/remote_wait_cloudinit.sh && /tmp/remote_bootstrap.sh'
