package com.ticketbox.ui.components

import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import kotlin.test.Test
import kotlin.test.assertEquals

class AppAdaptiveRowsTest {
    @Test
    fun editActionsStackThreeActionsBelowInlineBreakpoint() {
        assertEquals(
            AppAdaptiveEditActionMode.Stacked,
            resolveAppAdaptiveEditActionMode(
                maxWidth = AppAdaptiveBreakpoints.editActionInlineMinWidth - 1.dp,
                actionCount = 3,
                compact = false,
            ),
        )
    }

    @Test
    fun editActionsKeepTwoActionsInlineBelowInlineBreakpoint() {
        assertEquals(
            AppAdaptiveEditActionMode.Inline,
            resolveAppAdaptiveEditActionMode(
                maxWidth = AppAdaptiveBreakpoints.editActionInlineMinWidth - 1.dp,
                actionCount = 2,
                compact = false,
            ),
        )
    }

    @Test
    fun compactModeWinsWhenActionsDoNotNeedStacking() {
        assertEquals(
            AppAdaptiveEditActionMode.Compact,
            resolveAppAdaptiveEditActionMode(
                maxWidth = AppAdaptiveBreakpoints.editActionInlineMinWidth,
                actionCount = 3,
                compact = true,
            ),
        )
    }
}
