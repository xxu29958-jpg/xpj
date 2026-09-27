package com.ticketbox.ui.screens.settings

import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.ui.screens.plan.MonthlyArrangementIntentSummary
import com.ticketbox.viewmodel.OutboxStatusUiState

@Composable
internal fun ArrangementOriginalRecovery(row: OutboxRow, state: OutboxStatusUiState, actions: SyncStatusActions) {
    val pending = state.arrangements[row.id] ?: return
    MonthlyArrangementIntentSummary(pending)
    val intent = pending.intent?.takeIf { it.supports(row) } ?: return
    TextButton(onClick = { actions.onOpenArrangement(intent.month) }, enabled = state.busyRowId == null) {
        Text(stringResource(R.string.arrangement_open_month))
    }
}
