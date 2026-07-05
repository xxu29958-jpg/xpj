package com.ticketbox.ui.components

import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import kotlin.test.Test
import kotlin.test.assertEquals

class AppAdaptiveRowsTest {
    @Test
    fun contentActionRowsStackBelowInlineBreakpoint() {
        assertEquals(
            AppAdaptiveContentActionMode.Stacked,
            resolveAppAdaptiveContentActionMode(
                maxWidth = AppAdaptiveBreakpoints.contentActionInlineMinWidth - 1.dp,
            ),
        )
    }

    @Test
    fun contentActionRowsStayInlineAtInlineBreakpoint() {
        assertEquals(
            AppAdaptiveContentActionMode.Inline,
            resolveAppAdaptiveContentActionMode(
                maxWidth = AppAdaptiveBreakpoints.contentActionInlineMinWidth,
            ),
        )
    }

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
    fun editActionsCanStackTwoLongActionsBelowInlineBreakpoint() {
        assertEquals(
            AppAdaptiveEditActionMode.Stacked,
            resolveAppAdaptiveEditActionMode(
                maxWidth = AppAdaptiveBreakpoints.editActionInlineMinWidth - 1.dp,
                actionCount = 2,
                compact = false,
                stackTwoActionsOnNarrow = true,
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

    @Test
    fun amountRowsStackBelowInlineBreakpoint() {
        assertEquals(
            AppAdaptiveAmountRowMode.Stacked,
            resolveAppAdaptiveAmountRowMode(
                maxWidth = AppAdaptiveBreakpoints.amountRowInlineMinWidth - 1.dp,
            ),
        )
    }

    @Test
    fun amountRowsStayInlineAtInlineBreakpoint() {
        assertEquals(
            AppAdaptiveAmountRowMode.Inline,
            resolveAppAdaptiveAmountRowMode(
                maxWidth = AppAdaptiveBreakpoints.amountRowInlineMinWidth,
            ),
        )
    }

    @Test
    fun amountRowsExposeSharedDefaultsWithoutChangingCurrentValues() {
        assertEquals(AppAdaptiveBreakpoints.editActionInlineMinWidth, AppAdaptiveBreakpoints.amountRowInlineMinWidth)
        assertEquals(0.44f, AppAdaptiveAmountRowDefaults.trailingWeight)
        assertEquals(0.62f, AppAdaptiveAmountRowDefaults.reviewTrailingWeight)
        assertEquals(0.68f, AppAdaptiveAmountRowDefaults.listTrailingWeight)
        assertEquals(0.42f, AppAdaptiveAmountRowDefaults.groupHeaderTrailingWeight)
        assertEquals(0.72f, AppAdaptiveAmountRowDefaults.reconciliationTrailingWeight)
        assertEquals(118.dp, AppAdaptiveAmountRowDefaults.statusMinWidth)
        assertEquals(132.dp, AppAdaptiveAmountRowDefaults.secondaryMetaInlineMaxWidth)
    }
}
