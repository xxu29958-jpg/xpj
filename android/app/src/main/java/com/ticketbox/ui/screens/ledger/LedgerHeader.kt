package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.LedgerUiState

/**
 * Compact ledger header: one product identity row and one factual summary row.
 * The transaction register remains the visual center of the screen.
 */
@Composable
internal fun LedgerHeader(
    state: LedgerUiState,
) {
    val summary = state.summary
    val statusText = ledgerHeaderStatusText(state, ledgerSyncEvidence(state))
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(R.string.ledger_header_title),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = statusText,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Column(
            horizontalAlignment = Alignment.End,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = formatAmount(summary.totalAmountCents, LocalCurrencyCode.current),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge.copy(
                    fontWeight = FontWeight.SemiBold,
                ).tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = stringResource(R.string.ledger_header_count_value, summary.itemCount),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall.tabularNum(),
            )
        }
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
