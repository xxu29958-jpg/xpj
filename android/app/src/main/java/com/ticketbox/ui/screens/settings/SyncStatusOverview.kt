package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxWriteBlock
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.data.repository.PendingDebtAdjustment
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.OutboxStatusUiState

@Composable
internal fun SyncStatusOriginalIntentSummary(row: OutboxRow, state: OutboxStatusUiState) {
    state.recurringOccurrences[row.id]?.let { com.ticketbox.ui.screens.recurring.RecurringOccurrenceIntentSummary(it) }
    state.incomeEdits[row.id]?.let { com.ticketbox.ui.screens.IncomePlanIntentSummary(it) }
    state.debtAdjustments[row.id]?.let { com.ticketbox.ui.screens.DebtAdjustmentIntentSummary(it) }
}

internal data class SyncStatusOverview(
    val queuedCount: Int,
    val conflictCount: Int,
    val failedCount: Int,
    val quarantinedCount: Int,
    val reviewRequiredCount: Int,
    val refreshRequiredCount: Int,
    val stoppedCount: Int,
    val writeBlock: OutboxWriteBlock?,
) {
    val needsActionCount: Int = conflictCount + failedCount + quarantinedCount + reviewRequiredCount + refreshRequiredCount
    val isSettled: Boolean = queuedCount == 0 && needsActionCount == 0 && stoppedCount == 0
}

internal fun syncStatusOverview(
    status: OutboxStatus,
    corrections: List<PendingExpenseCorrection>,
    adjustments: List<PendingDebtAdjustment>,
): SyncStatusOverview =
    SyncStatusOverview(
        queuedCount = status.queueDepth.coerceAtLeast(0),
        conflictCount = status.conflicts.size,
        failedCount = status.failed.size,
        quarantinedCount = status.quarantinedCount.coerceAtLeast(0),
        reviewRequiredCount = corrections.count { !it.delivered && it.row.status == PendingMutationStatus.Done },
        refreshRequiredCount = corrections.count { it.refreshRequired },
        stoppedCount = adjustments.count { it.row.status == PendingMutationStatus.Abandoned },
        writeBlock = status.writeBlock,
    )

@Composable
internal fun SyncStatusOverviewSection(status: OutboxStatus, corrections: List<PendingExpenseCorrection>, adjustments: List<PendingDebtAdjustment>) {
    val overview = syncStatusOverview(status, corrections, adjustments)
    SettingsSection(
        title = stringResource(R.string.sync_status_overview_title),
        icon = Icons.Filled.Sync,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_queued_label),
                        value = overview.queuedCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_queued_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_conflicts_label),
                        value = overview.conflictCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_conflicts_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_failed_label),
                        value = overview.failedCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_failed_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.sync_status_overview_quarantined_label),
                        value = overview.quarantinedCount.toString(),
                        caption = stringResource(R.string.sync_status_overview_quarantined_caption),
                    ),
                ),
            )
            Text(
                text = overviewCaption(overview),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun overviewCaption(overview: SyncStatusOverview): String = when {
    overview.refreshRequiredCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_refresh_required, overview.refreshRequiredCount,
    )
    overview.reviewRequiredCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_review_required,
        overview.reviewRequiredCount,
    )
    overview.quarantinedCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_quarantined,
        overview.quarantinedCount,
    )
    overview.needsActionCount > 0 -> stringResource(
        R.string.sync_status_overview_caption_needs_action,
        overview.needsActionCount,
    )
    overview.queuedCount > 0 -> stringResource(overviewCaptionResource(overview))
    overview.stoppedCount > 0 -> stringResource(R.string.sync_status_overview_caption_stopped, overview.stoppedCount)
    else -> stringResource(R.string.sync_status_overview_caption_settled)
}

/** Both Sync entrances share the pending and explicit local-stop descriptions. */
@Composable
internal fun SyncStatusDebtSections(state: OutboxStatusUiState) {
    if (state.waitingDebtAdjustments.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.debt_adjustment_waiting), icon = Icons.Filled.CloudUpload) {
            state.waitingDebtAdjustments.forEach { com.ticketbox.ui.screens.DebtAdjustmentIntentSummary(it) }
        }
    }
    val stopped = state.debtAdjustments.values.filter { it.row.status == PendingMutationStatus.Abandoned }
    if (stopped.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.debt_adjustment_stopped), icon = Icons.Filled.Sync) {
            stopped.forEach { com.ticketbox.ui.screens.DebtAdjustmentIntentSummary(it) }
        }
    }
}

internal fun overviewCaptionResource(overview: SyncStatusOverview): Int =
    if (overview.writeBlock == OutboxWriteBlock.CURRENCY_ADOPTION_REQUIRED) {
        R.string.error_currency_adoption_required
    } else {
        R.string.sync_status_overview_caption_queued
    }

/** Translate known outbox error markers; never expose raw transport or engine errors to users. */
@Composable
internal fun friendlyLastError(raw: String?, fallback: String): String {
    val text = raw?.trim().orEmpty()
    if (text.isEmpty()) return fallback
    return when {
        text.startsWith("max_attempts_exceeded") -> stringResource(R.string.sync_status_error_max_attempts)
        text.startsWith("no_dispatcher_registered") -> stringResource(R.string.sync_status_error_no_dispatcher)
        text.startsWith("outbox_row_expired") -> stringResource(R.string.sync_status_error_expired)
        text in syncStatusExactErrorMessageResources ->
            stringResource(syncStatusExactErrorMessageResources.getValue(text))
        else -> fallback
    }
}

internal val syncStatusExactErrorMessageResources = mapOf(
    "runtime_version_mismatch" to R.string.sync_status_error_protocol_mismatch,
    "client_upgrade_required" to R.string.sync_status_error_protocol_mismatch,
    "rule_category_deleted" to R.string.sync_status_error_rule_category_deleted,
    "debt_adjustment_payload_unsupported" to R.string.debt_adjustment_unsupported,
    "debt_adjustment_negative_remaining" to R.string.debt_adjustment_reduction_rejected,
    "debt_adjustment_response_unverified" to R.string.debt_adjustment_attention,
    "debt_adjustment_binding_changed" to R.string.debt_adjustment_attention,
    "debt_adjustment_connection_interrupted" to R.string.debt_adjustment_attention,
    "debt_create_payload_unsupported" to R.string.debt_create_pending_unsupported,
    "debt_create_intent_invalid" to R.string.debt_create_sync_rejected,
    "debt_create_binding_changed" to R.string.debt_create_sync_rejected,
    "debt_create_rejected" to R.string.debt_create_sync_rejected,
    "debt_create_response_unverified" to R.string.debt_create_sync_uncertain,
    "debt_create_response_pending" to R.string.debt_create_sync_uncertain,
    "debt_create_connection_interrupted" to R.string.debt_create_sync_uncertain,
)
