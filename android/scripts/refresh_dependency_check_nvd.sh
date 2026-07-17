#!/usr/bin/env bash
set -euo pipefail

if [ -z "${NVD_API_KEY:-}" ]; then
  echo "::error::Trusted NVD refresh requires the repository NVD_API_KEY secret."
  exit 78
fi

dependency_data_dir="${DEPENDENCY_CHECK_DATA_DIR:-${GRADLE_USER_HOME:-$HOME/.gradle}/dependency-check-data}"
refresh_marker="$dependency_data_dir/xpj-nvd-refresh-epoch"
report_path="build/reports/dependency-check-report.json"

./gradlew --no-daemon --max-workers=2 \
  dependencyCheckUpdate -PdependencyCheckNvdValidForHours=0

rm -f "$report_path"
(
  unset NVD_API_KEY
  ./gradlew --no-daemon --max-workers=2 \
    dependencyCheckAggregate -PdependencyCheckAutoUpdate=false
)
"${PYTHON_BIN:-python3}" \
  scripts/verify_dependency_check_report.py "$report_path"

mkdir -p "$dependency_data_dir"
marker_temp="${refresh_marker}.tmp.$$"
trap 'rm -f "$marker_temp"' EXIT
date -u +%s > "$marker_temp"
mv -f "$marker_temp" "$refresh_marker"
trap - EXIT
