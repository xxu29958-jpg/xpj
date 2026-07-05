package com.ticketbox.ui.screens

import com.ticketbox.domain.model.UiText

internal enum class ReadableListBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun readableListBodyState(
    hasRows: Boolean,
    isLoading: Boolean,
    error: UiText?,
): ReadableListBodyState = when {
    hasRows -> ReadableListBodyState.Content
    isLoading -> ReadableListBodyState.Loading
    error != null -> ReadableListBodyState.LoadFailed
    else -> ReadableListBodyState.Empty
}

internal fun readableListInlineError(
    hasRows: Boolean,
    error: UiText?,
): UiText? = error?.takeIf { hasRows }
