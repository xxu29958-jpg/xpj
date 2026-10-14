package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.FlowRow
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.SettingsEntryRow

internal data class PendingToolsQueueActions(
    val onOpenCapture: () -> Unit,
    val onStartReview: (() -> Unit)?,
    val onOpenBulkConfirm: (() -> Unit)?,
)

internal data class PendingToolsState(val loading: Boolean, val displayMode: PendingDisplayMode)

internal enum class PendingDisplayMode {
    Compact,
    Comfortable,
}

@Composable
internal fun PendingToolsSheet(
    state: PendingToolsState,
    onDisplayModeChange: (PendingDisplayMode) -> Unit,
    actions: PendingScreenChromeActions,
    queue: PendingToolsQueueActions,
    onDismiss: () -> Unit,
) {
    AppSheetScaffold(
        title = stringResource(R.string.pending_tools_title),
        subtitle = stringResource(R.string.pending_tools_subtitle),
        actions = { PendingToolsFooter(state.loading, actions.onRefresh, onDismiss) },
    ) {
        SettingsEntryRow(
            title = stringResource(R.string.pending_tools_uploads),
            subtitle = stringResource(R.string.pending_tools_uploads_body),
            icon = R.drawable.ic_lucide_image_plus,
            onClick = { onDismiss(); queue.onOpenCapture() },
        )
        SettingsEntryRow(
            title = stringResource(R.string.pending_tools_review),
            subtitle = stringResource(if (queue.onStartReview != null) R.string.pending_tools_review_body else R.string.pending_tools_review_unavailable),
            icon = R.drawable.ic_lucide_receipt_text,
            onClick = queue.onStartReview?.let { action -> { onDismiss(); action() } },
        )
        SettingsEntryRow(
            title = stringResource(R.string.pending_tools_bulk),
            subtitle = stringResource(if (queue.onOpenBulkConfirm != null) R.string.pending_tools_bulk_body else R.string.pending_tools_bulk_unavailable),
            icon = R.drawable.ic_lucide_check,
            onClick = queue.onOpenBulkConfirm?.let { action -> { onDismiss(); action() } },
        )
        SettingsEntryRow(
            title = stringResource(R.string.relations_repayment_review),
            subtitle = stringResource(R.string.pending_tools_repayment_body),
            icon = R.drawable.ic_lucide_bell,
            onClick = { onDismiss(); actions.onOpenRepaymentReview() },
        )
        SettingsEntryRow(
            title = stringResource(R.string.stats_data_quality_entry_title),
            subtitle = stringResource(R.string.pending_tools_quality_body),
            icon = R.drawable.ic_lucide_shield_check,
            onClick = { onDismiss(); actions.onOpenDataQuality() },
        )
        Text(stringResource(R.string.pending_tools_density_title))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
            AppFilterChip(
                selected = state.displayMode == PendingDisplayMode.Compact,
                onClick = { onDisplayModeChange(PendingDisplayMode.Compact) },
                label = stringResource(R.string.pending_tools_density_compact),
            )
            AppFilterChip(
                selected = state.displayMode == PendingDisplayMode.Comfortable,
                onClick = { onDisplayModeChange(PendingDisplayMode.Comfortable) },
                label = stringResource(R.string.pending_tools_density_comfortable),
            )
        }
    }
}

@Composable
private fun PendingToolsFooter(loading: Boolean, onRefresh: () -> Unit, onDismiss: () -> Unit) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        AppSecondaryButton(
            text = if (loading) {
                stringResource(R.string.pending_tools_refresh_loading)
            } else {
                stringResource(R.string.pending_tools_refresh)
            },
            modifier = Modifier.weight(1f),
            enabled = !loading,
            onClick = onRefresh,
        )
        AppPrimaryButton(
            text = stringResource(R.string.pending_tools_done),
            modifier = Modifier.weight(1f),
            onClick = onDismiss,
        )
    }
}
