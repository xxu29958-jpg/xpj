#!/bin/sh
set -eu

: "${ANDROID_HOME:?ANDROID_HOME is required}"
: "${TICKETBOX_SERVER_URL:?TICKETBOX_SERVER_URL is required}"

printf 'sdk.dir=%s\n' "$ANDROID_HOME" > local.properties
printf 'ticketbox.serverUrl=%s\n' "$TICKETBOX_SERVER_URL" >> local.properties

capture_connected_failure() {
  connected_status=$?
  trap - 0
  if [ "$connected_status" -ne 0 ]; then
    printf 'Connected Gradle invocation failed with status %s.\n' \
      "$connected_status" >&2
    timeout --signal=INT --kill-after=15s 45s \
      ./gradlew --no-daemon :app:captureGrayConnectedTestCrashLog || true
  fi
  exit "$connected_status"
}

trap capture_connected_failure 0
timeout --signal=INT --kill-after=30s 14m \
  ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest
