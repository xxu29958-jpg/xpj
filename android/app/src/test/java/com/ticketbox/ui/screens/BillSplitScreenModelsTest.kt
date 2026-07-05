package com.ticketbox.ui.screens

import com.ticketbox.viewmodel.BillSplitListLoadState
import kotlin.test.Test
import kotlin.test.assertEquals

class BillSplitScreenModelsTest {

    @Test
    fun bodyStateSeparatesUnknownLoadingFailureEmptyAndContent() {
        assertEquals(
            ReadableListBodyState.Loading,
            billSplitListBodyState(hasRows = false, loadState = BillSplitListLoadState.Unknown),
        )
        assertEquals(
            ReadableListBodyState.Loading,
            billSplitListBodyState(hasRows = false, loadState = BillSplitListLoadState.Loading),
        )
        assertEquals(
            ReadableListBodyState.LoadFailed,
            billSplitListBodyState(hasRows = false, loadState = BillSplitListLoadState.Failed),
        )
        assertEquals(
            ReadableListBodyState.Empty,
            billSplitListBodyState(hasRows = false, loadState = BillSplitListLoadState.Loaded),
        )
        assertEquals(
            ReadableListBodyState.Content,
            billSplitListBodyState(hasRows = true, loadState = BillSplitListLoadState.Failed),
        )
    }
}
