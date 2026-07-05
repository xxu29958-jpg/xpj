package com.ticketbox.ui.screens

import com.ticketbox.ui.components.MonthPickerListState
import com.ticketbox.viewmodel.LedgerMonthsLoadState
import kotlin.test.Test
import kotlin.test.assertEquals

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
}
