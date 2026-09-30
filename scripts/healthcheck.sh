#!/usr/bin/env bash
#
# healthcheck.sh — basic host health checks.
#
# Checks disk usage and load average, plus optionally a systemd service
# state and an HTTP endpoint. Exit 0 when all checks pass, 1 otherwise.
#
# usage: healthcheck.sh [--disk-warn PCT] [--service NAME] [--url URL]

set -euo pipefail

DISK_WARN=85
SERVICE=""
URL=""

usage() {
  cat <<'EOF'
usage: healthcheck.sh [options]

options:
  --disk-warn PCT   warn if any filesystem exceeds PCT% use (default: 85)
  --service NAME    require systemd service NAME to be active
  --url URL         require an HTTP 2xx response from URL (via curl)
  -h, --help        show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --disk-warn) DISK_WARN="${2:?--disk-warn needs a value}"; shift 2 ;;
    --service)   SERVICE="${2:?--service needs a value}";     shift 2 ;;
    --url)       URL="${2:?--url needs a value}";             shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! [[ "$DISK_WARN" =~ ^[0-9]+$ ]]; then
  echo "error: --disk-warn must be a number" >&2
  exit 2
fi

fail=0

# --- disk usage -----------------------------------------------------------
while read -r _source _size _used _avail usep mount; do
  pct="${usep%\%}"
  if [[ "$pct" -ge "$DISK_WARN" ]]; then
    echo "WARN: filesystem $mount at ${usep} (threshold ${DISK_WARN}%)"
    fail=1
  fi
done < <(df --output=source,size,used,avail,pcent,target | tail -n +2)

# --- load average ---------------------------------------------------------
if [[ -r /proc/loadavg ]]; then
  cpus="$(nproc 2>/dev/null || echo 1)"
  load="$(awk '{print $1}' /proc/loadavg)"
  if awk "BEGIN {exit !( $load > $cpus )}"; then
    echo "WARN: 1-min load average $load exceeds cpu count $cpus"
    fail=1
  fi
fi

# --- systemd service ------------------------------------------------------
if [[ -n "$SERVICE" ]]; then
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "WARN: systemctl not available, skipping service check"
    fail=1
  elif systemctl is-active --quiet "$SERVICE"; then
    echo "OK: service $SERVICE is active"
  else
    echo "CRITICAL: service $SERVICE is not active"
    fail=1
  fi
fi

# --- HTTP endpoint --------------------------------------------------------
if [[ -n "$URL" ]]; then
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL" || echo "000")"
  if [[ "$code" == 2* ]]; then
    echo "OK: $URL returned HTTP $code"
  else
    echo "CRITICAL: $URL returned HTTP $code"
    fail=1
  fi
fi

if [[ "$fail" -eq 0 ]]; then
  echo "OK: all checks passed"
fi
exit "$fail"
