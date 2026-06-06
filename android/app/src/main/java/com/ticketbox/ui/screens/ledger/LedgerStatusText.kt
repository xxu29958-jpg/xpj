package com.ticketbox.ui.screens.ledger

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun ledgerCombinedStatusLine(state: LedgerUiState): String {
    val summary = state.summary
    val syncText = when {
        summary.syncing -> stringResource(R.string.ledger_status_syncing)
        summary.lastSyncAt != null -> stringResource(
            R.string.ledger_status_synced_at,
            ledgerSyncClock(summary.lastSyncAt),
        )
        else -> stringResource(R.string.ledger_status_offline)
    }
    return stringResource(R.string.ledger_status_line, syncText, ledgerFilterSummary(state))
}

@Composable
internal fun ledgerFilterSummary(state: LedgerUiState): String {
    val filter = state.filter
    val month = filter.monthFilter.takeIf { it.isNotBlank() }?.let(::displayMonthLabel)
        ?: stringResource(R.string.ledger_filter_summary_month_all)
    val category = filter.categoryFilter.takeIf { it.isNotBlank() }
        ?: stringResource(R.string.ledger_filter_summary_category_all)
    val tag = filter.tagFilter.takeIf { it.isNotBlank() }
        ?.let { stringResource(R.string.ledger_filter_summary_tag, it) }.orEmpty()
    val query = filter.query.takeIf { it.isNotBlank() }
        ?.let { stringResource(R.string.ledger_filter_summary_query, it) }.orEmpty()
    return stringResource(R.string.ledger_filter_summary_template, month, category, tag, query)
}

internal fun ledgerSyncClock(value: String): String {
    val label = displayTime(value)
    return label.substringAfterLast(" ").takeIf { it.isNotBlank() } ?: label
}
