#!/usr/bin/env bash
set -euo pipefail

dependency_data_dir="${DEPENDENCY_CHECK_DATA_DIR:-${GRADLE_USER_HOME:-$HOME/.gradle}/dependency-check-data}"
manifest_script="scripts/dependency_check_nvd_manifest.py"
report_script="scripts/verify_dependency_check_report.py"
report_path="build/reports/dependency-check-report.json"
inventory_path="build/reports/dependency-check-runtime-inventory.json"

if [ -n "${NVD_API_KEY:-}" ]; then
  echo "::error::NVD credential reached the read-only certification stage."
  exit 78
fi

python3 "$manifest_script" verify "$dependency_data_dir"
rm -f "$report_path" "$inventory_path"
./gradlew --no-daemon --max-workers=2 \
  dependencyCheckValidateNvd \
  -PdependencyCheckAutoUpdate=false \
  -PdependencyCheckNvdValidForHours=0
python3 "$report_script" "$report_path" --inventory "$inventory_path"
