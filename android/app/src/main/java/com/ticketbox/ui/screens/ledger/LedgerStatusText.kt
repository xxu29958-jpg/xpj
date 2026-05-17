package com.ticketbox.ui.screens.ledger

import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.viewmodel.LedgerUiState

internal fun ledgerCombinedStatusLine(state: LedgerUiState): String {
    val summary = state.summary
    val syncText = when {
        summary.syncing -> "更新中"
        summary.lastSyncAt != null -> "更新完成 · ${ledgerSyncClock(summary.lastSyncAt)}"
        else -> "离线可用"
    }
    return "$syncText · ${ledgerFilterSummary(state)}"
}

internal fun ledgerFilterSummary(state: LedgerUiState): String {
    val filter = state.filter
    val month = filter.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份"
    val category = filter.categoryFilter.takeIf { it.isNotBlank() } ?: "全部分类"
    val tag = filter.tagFilter.takeIf { it.isNotBlank() }?.let { " · 标签“$it”" }.orEmpty()
    val query = filter.query.takeIf { it.isNotBlank() }?.let { " · 搜索“$it”" }.orEmpty()
    return "当前查看：$month · $category$tag$query"
}

internal fun ledgerSyncClock(value: String): String {
    val label = displayTime(value)
    return label.substringAfterLast(" ").takeIf { it.isNotBlank() } ?: label
}
