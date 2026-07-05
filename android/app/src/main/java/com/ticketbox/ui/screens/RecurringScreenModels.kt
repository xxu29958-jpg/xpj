package com.ticketbox.ui.screens

import com.ticketbox.viewmodel.RecurringListLoadState

internal data class RecurringListSectionModel<T>(
    val rows: List<T>,
    val bodyState: ReadableListBodyState,
)

internal fun recurringListBodyState(
    hasRows: Boolean,
    loadState: RecurringListLoadState,
): ReadableListBodyState = when {
    hasRows -> ReadableListBodyState.Content
    loadState == RecurringListLoadState.Loaded -> ReadableListBodyState.Empty
    loadState == RecurringListLoadState.Failed -> ReadableListBodyState.LoadFailed
    else -> ReadableListBodyState.Loading
}
