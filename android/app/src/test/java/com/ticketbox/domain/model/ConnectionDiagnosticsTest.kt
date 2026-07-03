package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ConnectionDiagnosticsTest {
    @Test
    fun summarizesHealthyDiagnostics() {
        val diagnostics = ConnectionDiagnostics(
            checks = listOf(
                DiagnosticCheck(DiagnosticCheckKind.Auth, DiagnosticStatus.Pass, elapsedMs = 12),
                DiagnosticCheck(DiagnosticCheckKind.ServerSettings, DiagnosticStatus.Pass, elapsedMs = 20),
            ),
        )

        assertTrue(diagnostics.isHealthy)
        assertEquals(2, diagnostics.passedCount)
        assertEquals(0, diagnostics.warningCount)
        assertEquals(0, diagnostics.failedCount)
    }

    @Test
    fun warningsDoNotMakeDiagnosticsUnhealthy() {
        val diagnostics = ConnectionDiagnostics(
            checks = listOf(
                DiagnosticCheck(DiagnosticCheckKind.ProtectedImage, DiagnosticStatus.Warn, elapsedMs = 0),
            ),
        )

        assertTrue(diagnostics.isHealthy)
        assertEquals(1, diagnostics.warningCount)
    }

    @Test
    fun failuresMakeDiagnosticsUnhealthy() {
        val diagnostics = ConnectionDiagnostics(
            checks = listOf(
                DiagnosticCheck(
                    kind = DiagnosticCheckKind.Auth,
                    status = DiagnosticStatus.Fail,
                    detail = "绑定已失效，请重新绑定账本。",
                    elapsedMs = 18,
                ),
            ),
        )

        assertFalse(diagnostics.isHealthy)
        assertEquals(1, diagnostics.failedCount)
    }
}
