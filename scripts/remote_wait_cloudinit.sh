#!/bin/bash
# First remote-exec: proves SSH works when this line appears in terraform apply log.
# If you never see it, the problem is before this script (SSH, NSG, key, or wrong IP).
set -euo pipefail
echo "== TERRAFORM remote-exec #1: cloud-init wait script running $(date -u +%Y-%m-%dT%H:%M:%SZ) =="
echo "host=$(hostname) user=$(id -un) uptime=$(cat /proc/uptime 2>/dev/null | cut -d. -f1 || echo n/a)s"
echo "==== /var/log/cloud-init-output.log (last 200 lines) ===="
tail -n 200 /var/log/cloud-init-output.log 2>&1 || true
echo "==== end cloud-init log ===="
echo "==== waiting for cloud-init (poll every 20s; 3–10+ min is normal) ===="
n=0
while true; do
  n=$((n + 1))
  set +e
  st=$(cloud-init status --long 2>&1)
  rc=$?
  set -e
  if [ "$rc" -ne 0 ] && ! echo "$st" | grep -qE 'status: error'; then
    st="${st} (cloud-init status exit=$rc)"
  fi
  st_oneline=${st//$'\n'/ }
  echo "[$(date -u +%H:%M:%S) poll#${n}] ${st_oneline}"
  if echo "$st" | grep -qE 'status: done'; then
    break
  fi
  if echo "$st" | grep -qE 'status: error'; then
    echo "cloud-init failed (status: error). Full output:" >&2
    echo "$st" >&2
    exit 1
  fi
  sleep 20
done
echo "==== cloud-init complete $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
