#!/bin/sh
set -eu

: "${ANDROID_HOME:?ANDROID_HOME is required}"
: "${TICKETBOX_SERVER_URL:?TICKETBOX_SERVER_URL is required}"

printf 'sdk.dir=%s\n' "$ANDROID_HOME" > local.properties
printf 'ticketbox.serverUrl=%s\n' "$TICKETBOX_SERVER_URL" >> local.properties

timeout --signal=INT --kill-after=30s 14m \
  ./gradlew --no-daemon :app:connectedGrayDebugAndroidTest
