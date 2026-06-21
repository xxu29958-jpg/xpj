package com.ticketbox.macrobenchmark

import androidx.benchmark.macro.junit4.BaselineProfileRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Generates the Baseline Profile (issue #64 A1). Device/emulator only — run with:
 *   ./gradlew :app:generateGrayReleaseBaselineProfile
 * which drives this generator on the managed AVD (or a connected device) and copies
 * the resulting baseline-prof.txt into app/src/gray/generated/baselineProfiles/, from
 * where it is compiled into the gray release APK.
 *
 * The profileBlock walks the cold-start + first-scroll core path the acceptance
 * criteria target: launch → wait for the first screen → scroll the primary list once.
 */
@RunWith(AndroidJUnit4::class)
class BaselineProfileGenerator {
    @get:Rule
    val rule = BaselineProfileRule()

    @Test
    fun generate() = rule.collect(
        packageName = TARGET_PACKAGE,
        includeInStartupProfile = true,
    ) {
        pressHome()
        startActivityAndWait()

        // Best-effort first-screen scroll. Selecting the first scrollable container
        // keeps this resilient to the concrete screen the app opens on; if none is
        // present the cold-start path is still captured.
        device.findObject(By.scrollable(true))?.let { list ->
            list.setGestureMargin(device.displayWidth / GESTURE_MARGIN_DIVISOR)
            list.fling(Direction.DOWN)
            device.waitForIdle()
        }
    }
}

private const val GESTURE_MARGIN_DIVISOR = 5
