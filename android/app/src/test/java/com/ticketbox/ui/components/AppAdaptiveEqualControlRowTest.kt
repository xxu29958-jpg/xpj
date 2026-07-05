package com.ticketbox.ui.components

import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import kotlin.test.Test
import kotlin.test.assertEquals

class AppAdaptiveEqualControlRowTest {
    @Test
    fun equalControlRowsStackBelowInlineBreakpoint() {
        assertEquals(
            AppAdaptiveEqualControlMode.Stacked,
            resolveAppAdaptiveEqualControlMode(
                maxWidth = AppAdaptiveBreakpoints.contentActionInlineMinWidth - 1.dp,
            ),
        )
    }

    @Test
    fun equalControlRowsStayInlineAtInlineBreakpoint() {
        assertEquals(
            AppAdaptiveEqualControlMode.Inline,
            resolveAppAdaptiveEqualControlMode(
                maxWidth = AppAdaptiveBreakpoints.contentActionInlineMinWidth,
            ),
        )
    }
}
