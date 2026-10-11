#!/usr/bin/env bash
# Default: validate only. --apply explicitly installs the IVS candidate.
set -Eeuo pipefail
package_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
config_dir=${DAHUA_CONFIG_DIR:-/config}
target="$config_dir/custom_components/dahua"
action=${1:---check}

case "$action" in
  --check|--apply) ;;
  *) echo "Usage: bash install_ivs.sh [--check|--apply]"; exit 2 ;;
esac

command -v sha256sum >/dev/null
test -d "$target"
grep -Eq '"version"[[:space:]]*:[[:space:]]*"0\.9\.84\.1"' "$target/manifest.json" || {
  echo "STOP: restore the working hybrid 0.9.84.1 and its camera configuration first."
  exit 1
}
(cd "$target" && sha256sum -c "$package_dir/baseline_checksums.sha256") || {
  echo "STOP: installed files differ from the original hybrid. No changes made."
  exit 1
}
(cd "$package_dir/dahua" && sha256sum -c "$package_dir/candidate_checksums.sha256")
echo "Checks passed: exact hybrid baseline and IVS candidate integrity."
if [ "$action" = --check ]; then
  echo "Check only. To install: bash $package_dir/install_ivs.sh --apply"
  exit 0
fi

command -v ha >/dev/null
mkdir -p "$config_dir/dahua_backups"
backup=$(mktemp -d "$config_dir/dahua_backups/ivs_candidate_XXXXXX")
cp -a "$target" "$backup/stage"
for file in __init__.py binary_sensor.py client.py manifest.json ivs.py; do
  cp -a "$package_dir/dahua/$file" "$backup/stage/$file"
done
(cd "$backup/stage" && sha256sum -c "$package_dir/candidate_checksums.sha256")

# A rollback restores only integration code. This candidate never changes the
# config-entry format or manually writes the Home Assistant registries.
cp "$package_dir/rollback_ivs.sh" "$backup/rollback_ivs.sh"
stopped=0
moved=0
recover() {
  result=$?
  trap - ERR
  set +e
  if [ "$moved" = 1 ]; then
    if [ -d "$target" ]; then mv "$target" "$backup/failed_candidate"; fi
    mv "$backup/dahua_original" "$target"
  fi
  if [ "$stopped" = 1 ]; then ha core start; fi
  echo "Installation failed. Recovery attempted. Backup: $backup"
  exit "$result"
}
trap recover ERR

ha core stop
stopped=1
(cd "$target" && sha256sum -c "$package_dir/baseline_checksums.sha256")
if [ -d "$config_dir/.storage" ]; then
  cp -a "$config_dir/.storage" "$backup/storage_before"
fi
mv "$target" "$backup/dahua_original"
moved=1
mv "$backup/stage" "$target"
trap - ERR
ha core start

echo "Installed IVS candidate 0.9.84.2. Hardware validation is still required."
echo "Original integration and registry snapshot: $backup"
echo "Rollback: bash $backup/rollback_ivs.sh"
