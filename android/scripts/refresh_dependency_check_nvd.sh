#!/usr/bin/env bash
set -euo pipefail

if [ -z "${NVD_API_KEY:-}" ]; then
  echo "::error::Trusted NVD refresh requires the repository NVD_API_KEY secret."
  exit 78
fi

dependency_data_dir="${DEPENDENCY_CHECK_DATA_DIR:-${GRADLE_USER_HOME:-$HOME/.gradle}/dependency-check-data}"
refresh_marker="$dependency_data_dir/xpj-nvd-refresh-epoch"

./gradlew --no-daemon --max-workers=2 dependencyCheckUpdate

mkdir -p "$dependency_data_dir"
marker_temp="${refresh_marker}.tmp.$$"
trap 'rm -f "$marker_temp"' EXIT
date -u +%s > "$marker_temp"
mv -f "$marker_temp" "$refresh_marker"
trap - EXIT
