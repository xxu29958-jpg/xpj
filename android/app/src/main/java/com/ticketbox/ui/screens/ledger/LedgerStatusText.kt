package com.ticketbox.ui.screens.ledger

import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.viewmodel.LedgerUiState

internal fun ledgerCombinedStatusLine(state: LedgerUiState): String {
    val syncText = when {
        state.syncing -> "更新中"
        state.lastSyncAt != null -> "更新完成 · ${ledgerSyncClock(state.lastSyncAt)}"
        else -> "离线可用"
    }
    val month = state.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份"
    val category = state.categoryFilter.takeIf { it.isNotBlank() } ?: "全部分类"
    val tag = state.tagFilter.takeIf { it.isNotBlank() }?.let { " · 标签“$it”" }.orEmpty()
    val query = state.query.takeIf { it.isNotBlank() }?.let { " · 搜索“$it”" }.orEmpty()
    return "$syncText · 当前查看：$month · $category$tag$query"
}

internal fun ledgerFilterSummary(state: LedgerUiState): String {
    val month = state.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份"
    val category = state.categoryFilter.takeIf { it.isNotBlank() } ?: "全部分类"
    val tag = state.tagFilter.takeIf { it.isNotBlank() }?.let { " · 标签“$it”" }.orEmpty()
    val query = state.query.takeIf { it.isNotBlank() }?.let { " · 搜索“$it”" }.orEmpty()
    return "当前查看：$month · $category$tag$query"
}

internal fun ledgerSyncClock(value: String): String {
    val label = displayTime(value)
    return label.substringAfterLast(" ").takeIf { it.isNotBlank() } ?: label
}
