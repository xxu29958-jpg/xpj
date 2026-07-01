package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.mascot.MascotEmptyIllustration
import com.ticketbox.viewmodel.LedgerUiState
import com.valentinilk.shimmer.shimmer

@Composable
internal fun EmptyLedgerState(
    state: LedgerUiState,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onManualAdd: () -> Unit,
) {
    val hasMonth = state.monthFilter.isNotBlank()
    val hasCategory = state.categoryFilter.isNotBlank()
    val hasTag = state.tagFilter.isNotBlank()
    val hasActiveFilters = state.filter.hasFilters
    val title = when {
        hasTag -> stringResource(R.string.ledger_empty_title_tag, state.tagFilter)
        hasMonth && hasCategory -> stringResource(
            R.string.ledger_empty_title_month_category,
            displayMonthLabel(state.monthFilter),
            state.categoryFilter,
        )
        hasMonth -> stringResource(R.string.ledger_empty_title_month, displayMonthLabel(state.monthFilter))
        hasCategory -> stringResource(R.string.ledger_empty_title_category, state.categoryFilter)
        else -> stringResource(R.string.ledger_empty_title_default)
    }
    val body = when {
        hasMonth || hasCategory || hasTag -> stringResource(R.string.ledger_empty_body_filtered)
        state.readOnly -> stringResource(R.string.ledger_empty_body_readonly)
        else -> stringResource(R.string.ledger_empty_body_default)
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.compactGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.20f))
        MascotEmptyIllustration()
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = ledgerFilterSummary(state),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            if (hasActiveFilters) {
                Button(
                    modifier = Modifier.weight(1f),
                    onClick = onClearFilters,
                ) {
                    Text(stringResource(R.string.ledger_empty_reset_filters))
                }
                QuietOutlinedButton(
                    text = stringResource(R.string.ledger_empty_update_ledger),
                    modifier = Modifier.weight(1f),
                    enabled = !state.syncing,
                    onClick = onSync,
                )
            } else if (!state.readOnly) {
                Button(
                    modifier = Modifier.weight(1f),
                    onClick = onManualAdd,
                ) {
                    Text(stringResource(R.string.ledger_empty_manual_add))
                }
                QuietOutlinedButton(
                    text = stringResource(R.string.ledger_empty_update_ledger),
                    modifier = Modifier.weight(1f),
                    enabled = !state.syncing,
                    onClick = onSync,
                )
            } else {
                QuietOutlinedButton(
                    text = stringResource(R.string.ledger_empty_update_ledger),
                    modifier = Modifier.weight(1f),
                    enabled = !state.syncing,
                    onClick = onSync,
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.20f))
    }
}

/**
 * 8.4: chooses between the first-sync skeleton and the genuine empty state.
 * Extracted from LedgerScreen's ``item {}`` so that screen's lambda body stays
 * shallow (NestedBlockDepth gate) — the branch + skeleton blocks live here.
 */
@Composable
internal fun LedgerEmptyOrFirstSync(
    state: LedgerUiState,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onManualAdd: () -> Unit,
) {
    if (state.isFirstSync) {
        LedgerFirstSyncSkeleton()
    } else {
        EmptyLedgerState(
            state = state,
            onClearFilters = onClearFilters,
            onSync = onSync,
            onManualAdd = onManualAdd,
        )
    }
}

/** First-ever-sync placeholder list (shimmer skeleton rows). Mirrors PendingScreen. */
@Composable
private fun LedgerFirstSyncSkeleton() {
    Column(modifier = Modifier.shimmer()) {
        repeat(6) { ListItemSkeleton(horizontalPadding = 0.dp) }
    }
}
