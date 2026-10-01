package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.LedgerUiState

/** The visible stream owns the totals; unresolved dates stay next to those totals. */
@Composable
internal fun LedgerHeader(
    state: LedgerUiState,
) {
    val summary = state.summary
    val statusText = ledgerHeaderStatusText(state, ledgerSyncEvidence(state))
    Column(
        modifier = Modifier.fillMaxWidth().padding(vertical = AppSpacing.miniGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = stringResource(R.string.ledger_header_total_current_list),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
        LedgerAmounts(
            amounts = summary.amountsByCurrency,
            modifier = Modifier.fillMaxWidth(),
            role = AppAmountRole.Hero,
        )
        if (state.undatedExpenseCount > 0) com.ticketbox.ui.components.AccountingDateNotice(state.undatedExpenseCount)
        Text(
            text = stringResource(R.string.ledger_header_count_value, summary.itemCount) + " · " + statusText,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ledgerHeaderStatusText(
    state: LedgerUiState,
    evidence: LedgerSyncEvidence,
): String = when (evidence) {
    LedgerSyncEvidence.Refreshing -> stringResource(R.string.ledger_header_status_syncing)
    LedgerSyncEvidence.BackendSynced -> state.lastSyncAt?.let {
        stringResource(R.string.ledger_header_status_synced, ledgerSyncClock(it))
    } ?: stringResource(R.string.components_data_authority_backend_title)
    LedgerSyncEvidence.LocalCache -> stringResource(R.string.ledger_header_status_offline)
}
