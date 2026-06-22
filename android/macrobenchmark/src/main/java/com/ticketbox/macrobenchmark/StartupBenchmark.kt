package com.ticketbox.macrobenchmark

import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.StartupTimingMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Cold-start TTID measurement (issue #64 A1 acceptance #1). Device/emulator only:
 *   ./gradlew :macrobenchmark:connectedGrayBenchmarkAndroidTest
 *
 * Run both tests and compare the StartupTimingMetric medians:
 *   - startupNoCompilation   → CompilationMode.None(), the "before" (no profile)
 *   - startupBaselineProfile → CompilationMode.Partial(), the "after" (profile applied)
 * A measurable drop in timeToInitialDisplayMs is the A1 win.
 */
@RunWith(AndroidJUnit4::class)
class StartupBenchmark {
    @get:Rule
    val rule = MacrobenchmarkRule()

    @Test
    fun startupNoCompilation() = measureStartup(CompilationMode.None())

    @Test
    fun startupBaselineProfile() = measureStartup(CompilationMode.Partial())

    private fun measureStartup(mode: CompilationMode) = rule.measureRepeated(
        packageName = TARGET_PACKAGE,
        metrics = listOf(StartupTimingMetric()),
        compilationMode = mode,
        startupMode = StartupMode.COLD,
        iterations = STARTUP_ITERATIONS,
    ) {
        pressHome()
        startActivityAndWait()
    }
}
