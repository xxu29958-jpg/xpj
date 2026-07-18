#!/usr/bin/env bash
set -euo pipefail

if [ -z "${NVD_API_KEY:-}" ]; then
  echo "::error::Trusted NVD refresh requires its protected environment credential."
  exit 78
fi

dependency_data_dir="${DEPENDENCY_CHECK_DATA_DIR:-${GRADLE_USER_HOME:-$HOME/.gradle}/dependency-check-data}"
payload_manifest="$dependency_data_dir/xpj-nvd-payload-manifest.json"
legacy_refresh_marker="$dependency_data_dir/xpj-nvd-refresh-epoch"
manifest_script="scripts/dependency_check_nvd_manifest.py"
report_path="build/reports/dependency-check-report.json"
inventory_path="build/reports/dependency-check-runtime-inventory.json"

rm -f \
  "$payload_manifest" \
  "$legacy_refresh_marker" \
  "$report_path" \
  "$inventory_path"
refresh_started_epoch="$(date -u +%s)"

./gradlew --no-daemon --max-workers=2 \
  dependencyCheckUpdate -PdependencyCheckNvdValidForHours=0

(
  unset NVD_API_KEY
  ./gradlew --no-daemon --max-workers=2 \
    dependencyCheckValidateNvd \
    -PdependencyCheckAutoUpdate=false \
    -PdependencyCheckNvdValidForHours=0
  python3 "$manifest_script" create "$dependency_data_dir" \
    --report "$report_path" \
    --inventory "$inventory_path" \
    --nvd-checked-after-epoch "$refresh_started_epoch"
)
