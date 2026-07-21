package com.ticketbox.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppAdaptiveBreakpoints
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppAdaptivePageMode
import com.ticketbox.ui.design.AppSpacing
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

class AppPageScaffoldTest {
    @Test
    fun pageRolesUseExpectedDensity() {
        assertEquals(PageDensity.Comfortable, PageRole.Pending.density)
        assertEquals(PageDensity.Comfortable, PageRole.Stats.density)
        assertEquals(PageDensity.Compact, PageRole.Settings.density)
        assertEquals(PageDensity.Compact, PageRole.Ledger.density)
        assertEquals(PageDensity.Compact, PageRole.Edit.density)
    }

    @Test
    fun compactPagesStartTighterThanComfortablePages() {
        assertTrue(
            AppPageDefaults.topContentPadding(PageDensity.Compact) <
                AppPageDefaults.topContentPadding(PageDensity.Comfortable),
        )
        assertTrue(
            AppPageDefaults.headerToContentGap(PageDensity.Compact) <
                AppPageDefaults.headerToContentGap(PageDensity.Comfortable),
        )
        assertTrue(
            AppPageDefaults.sectionGap(PageDensity.Compact) <
                AppPageDefaults.sectionGap(PageDensity.Comfortable),
        )
    }

    @Test
    fun pageBottomPaddingContainsOnlyContentBreathingRoom() {
        assertEquals(
            AppSpacing.bottomContentPadding + AppSpacing.sectionGap + AppSpacing.cardGap,
            AppPageDefaults.BottomContentExtraPadding,
        )
    }

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
    fun scaffoldSpacingMatchesPageGateDefaults() {
        assertEquals(24f, AppPageDefaults.HorizontalPadding.value)
        assertEquals(14f, AppPageDefaults.topContentPadding(PageDensity.Compact).value)
        assertEquals(18f, AppPageDefaults.topContentPadding(PageDensity.Comfortable).value)
        assertEquals(12f, AppPageDefaults.headerToContentGap(PageDensity.Compact).value)
        assertEquals(16f, AppPageDefaults.headerToContentGap(PageDensity.Comfortable).value)
        assertEquals(12f, AppPageDefaults.sectionGap(PageDensity.Compact).value)
        assertEquals(16f, AppPageDefaults.sectionGap(PageDensity.Comfortable).value)
        assertEquals(16f, AppPageDefaults.CardGap.value)
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
    }

    @Test
    fun secondaryPagesDefaultToSharedAdaptiveContentPolicy() {
        val chrome = AppSecondaryPageChrome(
            role = AppPageRole.Settings,
            title = "Tags",
            subtitle = null,
            backText = "Back",
            onBack = {},
        )

        assertEquals(AppAdaptiveContentWidth.Secondary, chrome.contentWidth)
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
