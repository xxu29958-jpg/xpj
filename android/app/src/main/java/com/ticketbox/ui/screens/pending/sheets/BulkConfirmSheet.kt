package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BulkConfirmSheetContent(
    state: BulkConfirmSheetState,
    actions: BulkConfirmSheetActions,
) {
    ReviewSheetScaffold(
        title = stringResource(R.string.pending_bulk_sheet_title),
        subtitle = stringResource(R.string.pending_bulk_sheet_hint),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
        ) {
            StatLine(
                label = stringResource(R.string.pending_bulk_sheet_stat_will_confirm),
                value = stringResource(R.string.pending_bulk_sheet_stat_count, state.readyCount),
            )
            if (state.missingAmountSkipCount > 0) {
                StatLine(
                    label = stringResource(R.string.pending_bulk_sheet_stat_skip_missing_amount),
                    value = stringResource(R.string.pending_bulk_sheet_stat_count, state.missingAmountSkipCount),
                )
            }
            if (state.duplicateSkipCount > 0) {
                StatLine(
                    label = stringResource(R.string.pending_bulk_sheet_stat_skip_duplicate),
                    value = stringResource(R.string.pending_bulk_sheet_stat_skip_duplicate_count, state.duplicateSkipCount),
                )
            }
        }

        AppSheetActionRow(
            primary = AppSheetAction(
                text = confirmButtonLabel(state),
                enabled = !state.inProgress && state.readyCount > 0,
                onClick = actions.onConfirmReady,
            ),
            secondary = AppSheetAction(
                text = stringResource(R.string.common_cancel),
                enabled = !state.inProgress,
                onClick = actions.onDismiss,
            ),
        )
    }
}

internal data class BulkConfirmSheetState(
    val readyCount: Int,
    val missingAmountSkipCount: Int,
    val duplicateSkipCount: Int,
    val inProgress: Boolean,
    val confirmedCount: Int,
    val totalCount: Int,
)

internal data class BulkConfirmSheetActions(
    val onConfirmReady: () -> Unit,
    val onDismiss: () -> Unit,
)

/** Confirm-button label: live "已确认 N/M" progress over the run total, else the count CTA. */
@Composable
private fun confirmButtonLabel(
    state: BulkConfirmSheetState,
): String = when {
    state.inProgress && state.totalCount > 0 ->
        stringResource(R.string.pending_bulk_sheet_progress, state.confirmedCount, state.totalCount)
    state.inProgress -> stringResource(R.string.pending_bulk_sheet_in_progress)
    else -> stringResource(R.string.pending_bulk_sheet_confirm_button, state.readyCount)
}

@Composable
private fun StatLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        Text(value, fontWeight = AppTextHierarchy.body.weight, style = MaterialTheme.typography.bodyMedium)
    }
}
