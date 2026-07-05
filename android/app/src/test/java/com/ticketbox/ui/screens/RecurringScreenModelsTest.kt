package com.ticketbox.ui.screens

import com.ticketbox.viewmodel.RecurringListLoadState
import kotlin.test.Test
import kotlin.test.assertEquals

class RecurringScreenModelsTest {

    @Test
    fun bodyStateSeparatesUnknownLoadingFailureEmptyAndContent() {
        assertEquals(
            ReadableListBodyState.Loading,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Unknown),
        )
        assertEquals(
            ReadableListBodyState.Loading,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Loading),
        )
        assertEquals(
            ReadableListBodyState.LoadFailed,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Failed),
        )
        assertEquals(
            ReadableListBodyState.Empty,
            recurringListBodyState(hasRows = false, loadState = RecurringListLoadState.Loaded),
        )
        assertEquals(
            ReadableListBodyState.Content,
            recurringListBodyState(hasRows = true, loadState = RecurringListLoadState.Failed),
        )
    }
}
