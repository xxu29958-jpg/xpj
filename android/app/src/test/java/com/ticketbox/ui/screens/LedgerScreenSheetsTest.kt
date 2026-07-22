package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.MonthPickerListState
import com.ticketbox.viewmodel.LedgerDataQualityFilter
import com.ticketbox.viewmodel.LedgerMonthsLoadState
import com.ticketbox.viewmodel.LedgerUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class LedgerScreenSheetsTest {
    @Test
    fun monthPickerListStateFollowsLedgerMonthsLoadState() {
        assertEquals(
            MonthPickerListState.Unknown,
            ledgerMonthPickerListState(LedgerMonthsLoadState.Unknown),
        )
        assertEquals(
            MonthPickerListState.Loading,
            ledgerMonthPickerListState(LedgerMonthsLoadState.Loading),
        )
        assertEquals(
            MonthPickerListState.Loaded,
            ledgerMonthPickerListState(LedgerMonthsLoadState.Loaded),
        )
        assertEquals(
            MonthPickerListState.Failed,
            ledgerMonthPickerListState(LedgerMonthsLoadState.Failed),
        )
    }

    @Test
    fun exportUnavailableWhileDataQualityFilterActive() {
        // The CSV endpoint only scopes by month/category/tag; exporting under
        // the client-side data-quality filter would silently widen the scope.
        val state = LedgerUiState(
            items = listOf(exportFixtureExpense),
            dataQualityFilter = LedgerDataQualityFilter.MissingCategory,
        )
        assertFalse(ledgerExportAvailable(state))
        assertTrue(ledgerExportAvailable(state.copy(dataQualityFilter = null)))
    }

    @Test
    fun exportUnavailableWhenEmptyOrExporting() {
        assertFalse(ledgerExportAvailable(LedgerUiState(items = emptyList())))
        assertFalse(
            ledgerExportAvailable(
                LedgerUiState(items = listOf(exportFixtureExpense), exporting = true),
            ),
        )
    }
}

private val exportFixtureExpense = Expense(
    id = 1,
    publicId = "exp-1",
    amountCents = 1200,
    merchant = "商家1",
    category = "餐饮",
    note = null,
    source = "manual",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = "2026-05-17T08:00:00Z",
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = "2026-05-17T08:01:00Z",
    rejectedAt = null,
)
