package com.ticketbox.ui.screens.pending

import com.ticketbox.viewmodel.PendingListLoadState
import kotlin.test.Test
import kotlin.test.assertEquals

class PendingScreenModelsTest {

    @Test
    fun listBodyStateSeparatesLoadingFailedEmptyAndContent() {
        assertEquals(
            PendingListBodyState.Loading,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Unknown),
        )
        assertEquals(
            PendingListBodyState.Loading,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Loading),
        )
        assertEquals(
            PendingListBodyState.LoadFailed,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Failed),
        )
        assertEquals(
            PendingListBodyState.Empty,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Loaded),
        )
        assertEquals(
            PendingListBodyState.Content,
            pendingListBodyState(hasRows = true, loadState = PendingListLoadState.Failed),
        )
    }
}
