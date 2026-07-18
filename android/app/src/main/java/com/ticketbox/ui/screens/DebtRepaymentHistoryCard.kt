package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DebtRepaymentHistory
import com.ticketbox.domain.model.DebtRepaymentRecord
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.tabularNum

internal data class DebtRepaymentHistoryCardState(
    val history: DebtRepaymentHistory?,
    val isLoading: Boolean,
    val error: UiText?,
    val isLoadingMore: Boolean,
    val loadMoreError: UiText?,
    val undoablePublicIds: Set<String>,
)

/**
 * Canonical repayment history inside the new 往来 → 欠款详情 task path.
 *
 * Both effective and voided facts remain visible. A correction is rendered beside its original
 * repayment instead of replacing it, preserving the append-only audit meaning after app restart.
 */
@Composable
internal fun DebtRepaymentHistoryCard(
    state: DebtRepaymentHistoryCardState,
    currency: CurrencyDisplay,
    onUndo: (String) -> Unit,
    onLoadMore: () -> Unit,
) {
    val items = state.history?.items.orEmpty()
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.contentGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        DebtRepaymentHistoryHeader(state.history)
        if (state.isLoading) {
            Text(
                stringResource(R.string.debt_repayment_history_loading),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        state.error?.let { error ->
            AppStatusBanner(message = error, tone = MessageTone.Info)
        }
        if (!state.isLoading && state.error == null && items.isEmpty()) {
            Text(
                stringResource(R.string.debt_repayment_history_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        items.forEachIndexed { index, repayment ->
            if (index > 0) HorizontalDivider()
            DebtRepaymentHistoryRow(
                repayment = repayment,
                currency = currency,
                canUndo = repayment.publicId in state.undoablePublicIds,
                onUndo = onUndo,
            )
        }
        DebtRepaymentHistoryPagination(state = state, onLoadMore = onLoadMore)
    }
}

@Composable
private fun DebtRepaymentHistoryHeader(history: DebtRepaymentHistory?) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            stringResource(R.string.debt_repayment_history_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        history?.let {
            Text(
                stringResource(R.string.debt_repayment_history_count, it.items.size, it.total),
                style = MaterialTheme.typography.labelMedium.tabularNum(),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun DebtRepaymentHistoryPagination(
    state: DebtRepaymentHistoryCardState,
    onLoadMore: () -> Unit,
) {
    state.loadMoreError?.let { error ->
        AppStatusBanner(message = error, tone = MessageTone.Info)
    }
    if (state.history?.hasMore == true) {
        QuietOutlinedButton(
            text = stringResource(
                when {
                    state.isLoadingMore -> R.string.debt_repayment_history_loading_more
                    state.loadMoreError != null -> R.string.debt_repayment_history_retry_load_more
                    else -> R.string.debt_repayment_history_load_more
                },
            ),
            enabled = !state.isLoadingMore,
            onClick = onLoadMore,
        )
    }
}

@Composable
private fun DebtRepaymentHistoryRow(
    repayment: DebtRepaymentRecord,
    currency: CurrencyDisplay,
    canUndo: Boolean,
    onUndo: (String) -> Unit,
) {
    val stateTokens = LocalStateTokens.current
    AppSectionGroup(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(vertical = AppSpacing.miniGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        showTopDivider = false,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                formatDisplayAmount(repayment.amountCents, currency),
                style = MaterialTheme.typography.titleMedium.tabularNum(),
                fontWeight = FontWeight.SemiBold,
            )
            DebtStatusBadge(
                text = stringResource(
                    when {
                        repayment.isActive -> R.string.debt_repayment_history_active
                        repayment.isVoided -> R.string.debt_repayment_history_voided
                        else -> R.string.debt_repayment_history_unknown
                    },
                ),
                tone = if (repayment.isActive) stateTokens.success else stateTokens.neutral,
            )
        }
        Text(
            stringResource(
                R.string.debt_repayment_history_paid_at,
                displayDateTime(repayment.paidAt),
            ),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        repayment.voidFact?.let { voidFact ->
            Text(
                stringResource(R.string.debt_repayment_history_void_reason, voidFact.reason),
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                stringResource(
                    R.string.debt_repayment_history_voided_at,
                    displayDateTime(voidFact.createdAt),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (canUndo) {
            QuietOutlinedButton(
                text = stringResource(R.string.debt_repayment_history_undo),
                onClick = { onUndo(repayment.publicId) },
            )
        }
    }
}
