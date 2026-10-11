#!/usr/bin/env bash
# This script is copied into the installer's exact backup directory.
set -Eeuo pipefail
backup=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config_dir=${DAHUA_CONFIG_DIR:-/config}
target="$config_dir/custom_components/dahua"
test -s "$backup/dahua_original/manifest.json"
test -d "$target"
grep -Eq '"version"[[:space:]]*:[[:space:]]*"0\.9\.84\.2"' "$target/manifest.json" || {
  echo "STOP: current version has changed. Inspect it before restoring this backup."
  exit 1
}
test ! -e "$backup/dahua_ivs_removed"
command -v ha >/dev/null
moved=0
recover() {
  result=$?
  trap - ERR
  set +e
  if [ "$moved" = 1 ] && [ ! -d "$target" ]; then
    mv "$backup/dahua_ivs_removed" "$target"
  fi
  ha core start
  echo "Rollback failed. Recovery attempted. Backup: $backup"
  exit "$result"
}
trap recover ERR
ha core stop
mv "$target" "$backup/dahua_ivs_removed"
moved=1
mv "$backup/dahua_original" "$target"
trap - ERR
ha core start
echo "Restored the original hybrid. Existing Home Assistant registries were retained."
