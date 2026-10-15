package com.ticketbox.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppAdaptivePageMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertSame

class AppPageScaffoldTest {
    @Test
    fun globalDomainBarOwnsPrimaryStatusInsetWithoutAffectingSecondaryPages() {
        assertEquals(
            0.dp,
            resolveStatusPadding(
                includeStatusBarPadding = true,
                shellInsetHandled = true,
                measuredStatusPadding = 24.dp,
            ),
        )
        assertEquals(
            24.dp,
            resolveStatusPadding(
                includeStatusBarPadding = true,
                shellInsetHandled = false,
                measuredStatusPadding = 24.dp,
            ),
        )
    }

    @Test
    fun adaptivePageModesUseSharedBreakpoints() {
        assertEquals(
            AppAdaptivePageMode.SingleColumn,
            AppAdaptiveBreakpoints.pageModeFor(AppAdaptiveBreakpoints.mediumWidthMin - 1.dp),
        )
        assertEquals(
            AppAdaptivePageMode.WideContent,
            AppAdaptiveBreakpoints.pageModeFor(AppAdaptiveBreakpoints.mediumWidthMin),
        )
        assertEquals(
            AppAdaptivePageMode.TwoPane,
            AppAdaptiveBreakpoints.pageModeFor(AppAdaptiveBreakpoints.expandedWidthMin),
        )
    }

    @Test
    fun adaptiveContentWidthPoliciesResolveFromPageMode() {
        assertEquals(
            null,
            AppAdaptiveBreakpoints.contentMaxWidthFor(
                policy = AppAdaptiveContentWidth.Secondary,
                maxWidth = AppAdaptiveBreakpoints.mediumWidthMin - 1.dp,
            ),
        )
        assertEquals(
            AppAdaptiveBreakpoints.secondaryContentMaxWidth,
            AppAdaptiveBreakpoints.contentMaxWidthFor(
                policy = AppAdaptiveContentWidth.Secondary,
                maxWidth = AppAdaptiveBreakpoints.mediumWidthMin,
            ),
        )
        assertEquals(
            AppAdaptiveBreakpoints.twoPaneContentMaxWidth,
            AppAdaptiveBreakpoints.contentMaxWidthFor(
                policy = AppAdaptiveContentWidth.TwoPane,
                maxWidth = AppAdaptiveBreakpoints.expandedWidthMin,
            ),
        )
        assertEquals(
            AppAdaptiveBreakpoints.focusContentMaxWidth,
            AppAdaptiveBreakpoints.contentMaxWidthFor(
                policy = AppAdaptiveContentWidth.Focus,
                maxWidth = AppAdaptiveBreakpoints.mediumWidthMin,
            ),
        )
        assertEquals(
            null,
            AppAdaptiveBreakpoints.contentMaxWidthFor(
                policy = AppAdaptiveContentWidth.Focus,
                maxWidth = AppAdaptiveBreakpoints.mediumWidthMin - 1.dp,
            ),
        )
    }

    @Test
    fun secondaryBottomBarSlotUsesSharedResolutionRule() {
        val slotBottomBar: @Composable () -> Unit = {}
        val explicitBottomBar: @Composable () -> Unit = {}

        assertNull(AppSecondaryPageSlots().resolveBottomBar())
        assertSame(
            slotBottomBar,
            AppSecondaryPageSlots(bottomBar = slotBottomBar).resolveBottomBar(),
        )
        assertSame(
            explicitBottomBar,
            AppSecondaryPageSlots(bottomBar = slotBottomBar).resolveBottomBar(explicitBottomBar),
        )
    }
}
