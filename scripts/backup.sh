#!/usr/bin/env bash
#
# backup.sh — timestamped tar.gz backup of a directory with retention.
#
# usage: backup.sh --source DIR --dest DIR [--keep N]

set -euo pipefail

SOURCE=""
DEST=""
KEEP=7

usage() {
  cat <<'EOF'
usage: backup.sh --source DIR --dest DIR [--keep N]

  --source DIR   directory to back up (required)
  --dest DIR     directory to store backup archives (required)
  --keep N       retain the N most recent archives (default: 7)
  -h, --help     show this help and exit
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="${2:?--source needs a value}"; shift 2 ;;
    --dest)   DEST="${2:?--dest needs a value}";     shift 2 ;;
    --keep)   KEEP="${2:?--keep needs a value}";     shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$SOURCE" ]] || { echo "error: --source is required" >&2; usage >&2; exit 2; }
[[ -n "$DEST"   ]] || { echo "error: --dest is required"   >&2; usage >&2; exit 2; }
[[ -d "$SOURCE" ]] || { echo "error: source is not a directory: $SOURCE" >&2; exit 2; }
[[ "$KEEP" =~ ^[0-9]+$ ]] || { echo "error: --keep must be a non-negative integer" >&2; exit 2; }

mkdir -p "$DEST"

stamp="$(date +%Y%m%d-%H%M%S)"
archive="$DEST/backup-$stamp.tgz"
tar -czf "$archive" -C "$(dirname "$SOURCE")" "$(basename "$SOURCE")"
echo "created $archive"

# retention: keep the newest $KEEP archives, prune the rest
mapfile -t old < <(ls -1t "$DEST"/backup-*.tgz 2>/dev/null | tail -n +"$((KEEP + 1))" || true)
if [[ "${#old[@]}" -gt 0 ]]; then
  for f in "${old[@]}"; do
    rm -f "$f"
    echo "pruned $f"
  done
fi
