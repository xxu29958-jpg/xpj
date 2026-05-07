package com.ticketbox.ui.components

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class AppPageScaffoldTest {
    @Test
    fun pageRolesUseExpectedDensity() {
        assertEquals(PageDensity.Comfortable, PageRole.Pending.density)
        assertEquals(PageDensity.Comfortable, PageRole.Stats.density)
        assertEquals(PageDensity.Comfortable, PageRole.Settings.density)
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
    fun bottomPaddingUsesNamedBottomBarConstant() {
        assertEquals(104f, AppPageDefaults.BottomBarHeight.value)
        assertEquals(24f, AppPageDefaults.BottomContentExtraPadding.value)
    }

    @Test
    fun scaffoldSpacingMatchesPageGateDefaults() {
        assertEquals(24f, AppPageDefaults.HorizontalPadding.value)
        assertEquals(10f, AppPageDefaults.topContentPadding(PageDensity.Compact).value)
        assertEquals(16f, AppPageDefaults.topContentPadding(PageDensity.Comfortable).value)
        assertEquals(16f, AppPageDefaults.headerToContentGap(PageDensity.Compact).value)
        assertEquals(22f, AppPageDefaults.headerToContentGap(PageDensity.Comfortable).value)
        assertEquals(18f, AppPageDefaults.sectionGap(PageDensity.Compact).value)
        assertEquals(24f, AppPageDefaults.sectionGap(PageDensity.Comfortable).value)
        assertEquals(16f, AppPageDefaults.CardGap.value)
    }
}
