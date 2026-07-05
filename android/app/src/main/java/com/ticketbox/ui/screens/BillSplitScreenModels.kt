package com.ticketbox.ui.screens

import com.ticketbox.viewmodel.BillSplitListLoadState
import com.ticketbox.viewmodel.BillSplitUiState

internal data class BillSplitScreenBodyStates(
    val inbox: ReadableListBodyState,
    val sent: ReadableListBodyState,
    val selected: ReadableListBodyState,
)

internal fun billSplitScreenBodyStates(
    state: BillSplitUiState,
    selectedTab: Int,
): BillSplitScreenBodyStates {
    val inbox = billSplitListBodyState(
        hasRows = state.inbox.isNotEmpty(),
        loadState = state.inboxLoadState,
    )
    val sent = billSplitListBodyState(
        hasRows = state.sent.isNotEmpty(),
        loadState = state.sentLoadState,
    )
    return BillSplitScreenBodyStates(
        inbox = inbox,
        sent = sent,
        selected = if (selectedTab == 0) inbox else sent,
    )
}

internal fun billSplitListBodyState(
    hasRows: Boolean,
    loadState: BillSplitListLoadState,
): ReadableListBodyState = when {
    hasRows -> ReadableListBodyState.Content
    loadState == BillSplitListLoadState.Loaded -> ReadableListBodyState.Empty
    loadState == BillSplitListLoadState.Failed -> ReadableListBodyState.LoadFailed
    else -> ReadableListBodyState.Loading
}
