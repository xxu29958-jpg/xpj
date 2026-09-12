package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxWriteBlock
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.data.repository.PendingDebtWrite
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.OutboxStatusUiState

@Composable
internal fun SyncStatusOriginalIntentSummary(row: OutboxRow, state: OutboxStatusUiState, actions: SyncStatusActions) {
    state.manualRates[row.id]?.let { original ->
        com.ticketbox.ui.screens.plan.ManualRateSubmissionSummary(original)
        TextButton(onClick = { actions.onOpenRateSubmission(row.id) }) { Text(stringResource(R.string.advice_rate_submission_open)) }
    }
    state.categoryRules[row.id]?.let { original ->
        com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleSubmissionSummary(original)
        TextButton(onClick = { actions.onOpenRuleSubmission(row.id) }) {
            Text(stringResource(R.string.category_rule_submission_open))
        }
    }
    state.goalEdits[row.id]?.let { original ->
        original.request?.let { request ->
            com.ticketbox.ui.screens.plan.SpendingGoalOriginalSummary(request.name, request.month,
                request.targetAmountCents, request.homeCurrencyCode)
        }
        row.targetId.takeIf { it.startsWith("goal:") && it.length > 5 }?.removePrefix("goal:")?.let { publicId ->
            TextButton(onClick = { actions.onOpenGoalEdit(publicId) }) { Text(stringResource(R.string.goal_submission_open)) }
        }
    }
    state.goalCreations[row.id]?.let { original ->
        com.ticketbox.ui.screens.GoalCreationIntentSummary(original)
        TextButton(onClick = { actions.onOpenGoalCreation(row.id) }) { Text(stringResource(R.string.goal_creation_open)) }
    }
    state.recurringItems[row.id]?.let { original ->
        com.ticketbox.ui.screens.recurring.RecurringManualIntentSummary(original)
        TextButton(onClick = actions.onOpenRecurring) { Text(stringResource(R.string.recurring_original_open)) }
    }
    state.recurringOccurrences[row.id]?.let {
        com.ticketbox.ui.screens.recurring.RecurringOccurrenceIntentSummary(it)
        TextButton(onClick = actions.onOpenRecurring) { Text(stringResource(R.string.recurring_original_open)) }
    }
    state.incomeSubmissions[row.id]?.let { original ->
        com.ticketbox.ui.screens.IncomePlanIntentSummary(original)
        TextButton(onClick = { actions.onOpenIncomeSubmission(row.id) }) {
            Text(stringResource(R.string.income_plan_submission_open))
        }
    }
    state.debtWrites[row.id]?.let { com.ticketbox.ui.screens.DebtWriteIntentSummary(it) }
    state.budgetSaves[row.id]?.let { pending ->
        com.ticketbox.ui.screens.budget.BudgetSaveIntentSummary(pending)
        if (pending.hasSupportedIntent) {
            TextButton(onClick = { actions.onOpenBudget(requireNotNull(pending.intent).month) }) {
                Text(stringResource(R.string.budget_save_open_month))
            }
        }
    }
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
    writes: List<PendingDebtWrite>,
    incomeSubmissions: List<PendingIncomePlanSubmission> = emptyList(),
    manualRates: List<com.ticketbox.data.repository.PendingManualRateSubmission> = emptyList(),
): SyncStatusOverview =
    SyncStatusOverview(
        queuedCount = status.queueDepth.coerceAtLeast(0),
        conflictCount = status.conflicts.size,
        failedCount = status.failed.size,
        quarantinedCount = status.quarantinedCount.coerceAtLeast(0),
        reviewRequiredCount = corrections.count { !it.delivered && it.row.status == PendingMutationStatus.Done } +
            incomeSubmissions.count { it.requiresReview } + manualRates.count { it.row.status == PendingMutationStatus.Done && !it.isConfirmed },
        refreshRequiredCount = corrections.count { it.refreshRequired },
        stoppedCount = writes.count { it.row.status == PendingMutationStatus.Abandoned },
        writeBlock = status.writeBlock,
    )

@Composable
internal fun SyncStatusOverviewSection(status: OutboxStatus, corrections: List<PendingExpenseCorrection>,
    writes: List<PendingDebtWrite>, incomeSubmissions: List<PendingIncomePlanSubmission>,
    manualRates: List<com.ticketbox.data.repository.PendingManualRateSubmission>) {
    val overview = syncStatusOverview(status, corrections, writes, incomeSubmissions, manualRates)
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
internal fun SyncStatusIncomeReviews(state: OutboxStatusUiState, actions: SyncStatusActions) {
    val reviews = state.incomeSubmissions.values.filter { it.requiresReview }
    if (reviews.isEmpty()) return
    SettingsSection(title = stringResource(R.string.sync_status_section_needs_action), icon = Icons.Filled.Sync) {
        reviews.forEach { original ->
            Text(stringResource(R.string.income_plan_submission_review))
            SyncStatusOriginalIntentSummary(original.row, state, actions)
            TextButton(enabled = state.busyRowId == null, onClick = { actions.onDropFailed(original.row) }) {
                Text(stringResource(R.string.income_plan_submission_stop_record))
            }
        }
    }
}

@Composable
internal fun SyncStatusRateReviews(state: OutboxStatusUiState, actions: SyncStatusActions) {
    state.manualRates.values.filter { it.row.status == PendingMutationStatus.Done && !it.isConfirmed }.forEach { original ->
        SyncStatusOriginalIntentSummary(original.row, state, actions)
        TextButton(onClick = { actions.onDropFailed(original.row) }, enabled = state.busyRowId == null) {
            Text(stringResource(R.string.advice_rate_stop))
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
    if (state.waitingDebtWrites.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.debt_write_waiting), icon = Icons.Filled.CloudUpload) {
            state.waitingDebtWrites.forEach { com.ticketbox.ui.screens.DebtWriteIntentSummary(it) }
        }
    }
    val stopped = state.debtWrites.values.filter { it.row.status == PendingMutationStatus.Abandoned }
    if (stopped.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.debt_write_stopped), icon = Icons.Filled.Sync) {
            stopped.forEach { com.ticketbox.ui.screens.DebtWriteIntentSummary(it) }
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
        text.substringBefore(':') == com.ticketbox.data.repository.MANUAL_CREATE_RECEIPT_REVIEW ->
            stringResource(R.string.error_manual_create_original_requires_review)
        text.startsWith("max_attempts_exceeded") -> stringResource(R.string.sync_status_error_max_attempts)
        text.startsWith("no_dispatcher_registered") -> stringResource(R.string.sync_status_error_no_dispatcher)
        text.startsWith("outbox_row_expired") -> stringResource(R.string.sync_status_error_expired)
        text in syncStatusExactErrorMessageResources ->
            stringResource(syncStatusExactErrorMessageResources.getValue(text))
        else -> fallback
    }
}

internal val syncStatusExactErrorMessageResources = mapOf(
    "manual_create_original_unverified" to R.string.ledger_manual_original_unverified,
    "budget_currency_conflict" to R.string.budget_save_currency_conflict,
    "budget_save_unsupported" to R.string.budget_save_unsupported,
    "budget_save_unverified" to R.string.budget_save_unverified,
    "runtime_version_mismatch" to R.string.sync_status_error_protocol_mismatch,
    "offset_create_requires_review" to R.string.expense_offset_original_requires_review,
    "client_upgrade_required" to R.string.sync_status_error_protocol_mismatch,
    "rule_category_deleted" to R.string.sync_status_error_rule_category_deleted,
    "debt_repayment_payload_unsupported" to R.string.debt_write_unsupported,
    "debt_repayment_response_unverified" to R.string.debt_write_attention,
    "debt_repayment_binding_changed" to R.string.debt_write_attention,
    "debt_repayment_connection_interrupted" to R.string.debt_write_attention,
    "debt_adjustment_payload_unsupported" to R.string.debt_write_unsupported,
    "debt_adjustment_negative_remaining" to R.string.debt_adjustment_reduction_rejected,
    "debt_adjustment_response_unverified" to R.string.debt_write_attention,
    "debt_adjustment_binding_changed" to R.string.debt_write_attention,
    "debt_adjustment_connection_interrupted" to R.string.debt_write_attention,
    "debt_create_payload_unsupported" to R.string.debt_create_pending_unsupported,
    "debt_create_intent_invalid" to R.string.debt_create_sync_rejected,
    "debt_create_binding_changed" to R.string.debt_create_sync_rejected,
    "debt_create_rejected" to R.string.debt_create_sync_rejected,
    "debt_create_response_unverified" to R.string.debt_create_sync_uncertain,
    "debt_create_response_pending" to R.string.debt_create_sync_uncertain,
    "debt_create_connection_interrupted" to R.string.debt_create_sync_uncertain,
)

@Composable
internal fun SyncStatusBillSplitSection(state: com.ticketbox.viewmodel.OutboxStatusUiState, actions: SyncStatusActions) {
    state.billSplitCreations.values.forEach { pending ->
        com.ticketbox.ui.screens.expense.fact.BillSplitSubmissionCard(pending, state.correctionObservation.access?.canModify == true,
            state.busyRowId == pending.row.id, recover = { drop ->
                if (drop) actions.onDropFailed(pending.row) else actions.onRetry(pending.row)
            })
    }
}
