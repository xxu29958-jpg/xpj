package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.DebtCreationPendingState
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum

/** Read-only intent projection. These rows never participate in canonical Debt groups or totals. */
@Composable
internal fun DebtPendingCreations(
    intents: List<PendingDebtCreation>,
    onOpenSyncStatus: () -> Unit,
) {
    if (intents.isEmpty()) return
    AppSectionGroup(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.debt_create_pending_title), style = MaterialTheme.typography.titleSmall)
        Text(
            stringResource(R.string.debt_create_pending_body),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        intents.forEachIndexed { index, intent ->
            AppListRow(onClick = onOpenSyncStatus, showDivider = index < intents.lastIndex) {
                PendingCreationContent(intent)
            }
        }
        TextButton(onClick = onOpenSyncStatus) {
            Text(stringResource(R.string.debt_create_pending_manage))
        }
    }
}

@Composable
private fun PendingCreationContent(intent: PendingDebtCreation) {
    val draft = intent.draft
    val currency = intent.homeCurrency
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
            Text(
                draft?.counterpartyLabel ?: stringResource(R.string.debt_create_pending_unreadable),
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.titleSmall,
            )
            if (draft != null && currency != null) {
                Text(
                    formatDisplayAmount(draft.principalAmountCents, CurrencyDisplay.forRecord(currency.storageKey)),
                    style = MaterialTheme.typography.titleSmall.tabularNum(),
                )
            }
        }
        val direction = draft?.let { stringResource(debtDirectionLabelRes(it.direction)) }
        val status = stringResource(intent.state.labelRes())
        Text(
            listOfNotNull(direction, status).joinToString(" · "),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        draft?.note?.takeIf { it.isNotBlank() }?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun DebtCreationPendingState.labelRes(): Int = when (this) {
    DebtCreationPendingState.Waiting -> R.string.debt_create_pending_waiting
    DebtCreationPendingState.Sending -> R.string.debt_create_pending_sending
    DebtCreationPendingState.NeedsAttention -> R.string.debt_create_pending_attention
    DebtCreationPendingState.Unsupported -> R.string.debt_create_pending_unsupported
}
