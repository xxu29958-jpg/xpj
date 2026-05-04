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
                DiagnosticCheck("Token 校验", DiagnosticStatus.Pass, "APP_TOKEN 有效", 12),
                DiagnosticCheck("服务器状态", DiagnosticStatus.Pass, "状态接口可用", 20),
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
                DiagnosticCheck("受保护图片", DiagnosticStatus.Warn, "暂无待确认截图", 0),
            ),
        )

        assertTrue(diagnostics.isHealthy)
        assertEquals(1, diagnostics.warningCount)
    }

    @Test
    fun failuresMakeDiagnosticsUnhealthy() {
        val diagnostics = ConnectionDiagnostics(
            checks = listOf(
                DiagnosticCheck("Token 校验", DiagnosticStatus.Fail, "Token 无效", 18),
            ),
        )

        assertFalse(diagnostics.isHealthy)
        assertEquals(1, diagnostics.failedCount)
    }
}
