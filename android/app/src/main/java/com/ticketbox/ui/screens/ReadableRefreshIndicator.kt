package com.ticketbox.ui.screens

internal object ReadableRefreshIndicator {
    fun isActive(loading: Boolean, hasReadableData: Boolean): Boolean = loading && !hasReadableData
}
