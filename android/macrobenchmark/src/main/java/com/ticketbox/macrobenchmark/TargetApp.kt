package com.ticketbox.macrobenchmark

/**
 * The gray flavor's application id — the release variant A1 profiles and measures
 * (the build gray users actually run; the internal flavor adds a `.internal` suffix).
 */
internal const val TARGET_PACKAGE = "com.ticketbox"

/** Macrobenchmark startup iterations — enough samples for a stable median. */
internal const val STARTUP_ITERATIONS = 10
