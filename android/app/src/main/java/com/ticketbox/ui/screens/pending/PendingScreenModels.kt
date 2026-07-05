package com.ticketbox.ui.screens.pending

import com.ticketbox.viewmodel.PendingListLoadState

internal enum class PendingListBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun pendingListBodyState(
    hasRows: Boolean,
    loadState: PendingListLoadState,
): PendingListBodyState = when {
    hasRows -> PendingListBodyState.Content
    loadState == PendingListLoadState.Loaded -> PendingListBodyState.Empty
    loadState == PendingListLoadState.Failed -> PendingListBodyState.LoadFailed
    else -> PendingListBodyState.Loading
}
