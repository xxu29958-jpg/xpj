package com.ticketbox.ui.screens.ledger

import com.ticketbox.viewmodel.LedgerDataQualityFilter
import com.ticketbox.viewmodel.LedgerUiState
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LedgerToolsSheetTest {
    @Test
    fun dataQualityDrillAloneCountsAsUserVisibleFilter() {
        // Otherwise the footer hides 清除筛选 for a DQ-only view while the
        // export note in the same sheet says to clear the filter first.
        val dqOnly = LedgerUiState(dataQualityFilter = LedgerDataQualityFilter.MissingCategory)
        assertTrue(ledgerHasUserVisibleFilters(dqOnly))
        assertTrue(ledgerHasUserVisibleFilters(dqOnly.copy(dataQualityFilter = LedgerDataQualityFilter.ConfirmedWithoutImage)))
        assertFalse(ledgerHasUserVisibleFilters(dqOnly.copy(dataQualityFilter = null)))
    }

    @Test
    fun ordinaryFiltersStillCount() {
        assertTrue(ledgerHasUserVisibleFilters(LedgerUiState(categoryFilter = "餐饮")))
        assertTrue(ledgerHasUserVisibleFilters(LedgerUiState(tagFilter = "旅行")))
        assertTrue(ledgerHasUserVisibleFilters(LedgerUiState(query = "早餐")))
        assertFalse(ledgerHasUserVisibleFilters(LedgerUiState()))
    }
}
