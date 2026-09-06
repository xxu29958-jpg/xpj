package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.SyncProblem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.DebtCreationIntentSummary
import com.ticketbox.viewmodel.OutboxStatusUiState
import com.ticketbox.viewmodel.OutboxStatusViewModel

@Composable
fun SyncStatusScreen(
    viewModel: OutboxStatusViewModel,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val actions = remember(viewModel) {
        SyncStatusActions(
            onKeepMine = viewModel::keepMine,
            onDropMine = viewModel::dropMine,
            onRetry = viewModel::retry,
            onDropFailed = viewModel::dropFailed,
            onClearQuarantined = viewModel::clearQuarantined,
        )
    }
    SyncStatusScreenContent(state = state, actions = actions, onBack = onBack)
}

/** Row callbacks grouped to keep the content API small and testable. */
internal data class SyncStatusActions(
    val onKeepMine: (OutboxRow) -> Unit,
    val onDropMine: (OutboxRow) -> Unit,
    val onRetry: (OutboxRow) -> Unit,
    val onDropFailed: (OutboxRow) -> Unit,
    val onClearQuarantined: () -> Unit,
)

private data class SyncStatusActionButton(
    val text: String,
    val icon: ImageVector? = null,
    val enabled: Boolean,
    val onClick: () -> Unit,
)

@Composable
internal fun SyncStatusScreenContent(
    state: OutboxStatusUiState,
    actions: SyncStatusActions,
    onBack: () -> Unit,
) {
    // Dropping an offline edit is irreversible, so both paths require confirmation.
    var confirmingDrop by remember { mutableStateOf<SyncStatusDropSelection?>(null) }
    var confirmingClearQuarantined by remember { mutableStateOf(false) }

    confirmingDrop?.let { selection ->
        SyncStatusDropDialog(
            selection = selection,
            busy = state.busyRowId != null,
            onConfirm = {
                confirmingDrop = null
                if (selection.failed) actions.onDropFailed(selection.row) else actions.onDropMine(selection.row)
            },
            onDismiss = { confirmingDrop = null },
        )
    }
    if (confirmingClearQuarantined) {
        ClearQuarantinedDialog(
            count = state.status.quarantinedCount,
            busy = state.isClearingQuarantine,
            onConfirm = {
                confirmingClearQuarantined = false
                actions.onClearQuarantined()
            },
            onDismiss = { confirmingClearQuarantined = false },
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.sync_status_page_title),
        subtitle = stringResource(R.string.sync_status_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        SyncStatusPageBody(
            state = state,
            actions = actions.copy(
                onDropMine = { confirmingDrop = SyncStatusDropSelection(it, failed = false, debtCreation = null,
                    recurringOccurrence = state.recurringOccurrences[it.id], incomeEdit = state.incomeEdits[it.id], debtAdjustment = state.debtAdjustments[it.id]) },
                onDropFailed = { row ->
                    confirmingDrop = SyncStatusDropSelection(row, failed = true, debtCreation = state.failedDebtCreations[row.id],
                        recurringOccurrence = state.recurringOccurrences[row.id], incomeEdit = state.incomeEdits[row.id], debtAdjustment = state.debtAdjustments[row.id])
                },
                onClearQuarantined = { confirmingClearQuarantined = true },
            ),
        )
    }
}

@Composable
private fun SyncStatusPageBody(
    state: OutboxStatusUiState,
    actions: SyncStatusActions,
) {
    val status = state.status
    SyncStatusOverviewSection(status)

    SyncStatusQuarantineSection(
        count = status.quarantinedCount,
        clearEnabled = !state.isClearingQuarantine && state.busyRowId == null,
        onClear = actions.onClearQuarantined,
    )

    if (state.waitingDebtAdjustments.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.debt_adjustment_waiting), icon = Icons.Filled.CloudUpload) {
            state.waitingDebtAdjustments.forEach { com.ticketbox.ui.screens.DebtAdjustmentIntentSummary(it) }
        }
    }

    if (status.conflicts.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_needs_action), icon = Icons.Filled.SyncProblem) {
            status.conflicts.forEach { row ->
                state.recurringOccurrences[row.id]?.let { com.ticketbox.ui.screens.recurring.RecurringOccurrenceIntentSummary(it) }
                state.incomeEdits[row.id]?.let { com.ticketbox.ui.screens.IncomePlanIntentSummary(it) }
                state.debtAdjustments[row.id]?.let { com.ticketbox.ui.screens.DebtAdjustmentIntentSummary(it) }
                ConflictCard(
                    row = row,
                    busy = state.busyRowId == row.id,
                    onKeepMine = { actions.onKeepMine(row) },
                    onDropMine = { actions.onDropMine(row) },
                )
            }
        }
    }

    if (status.failed.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_failed), icon = Icons.Filled.ErrorOutline) {
            status.failed.forEach { row ->
                state.recurringOccurrences[row.id]?.let { com.ticketbox.ui.screens.recurring.RecurringOccurrenceIntentSummary(it) }
                state.incomeEdits[row.id]?.let { com.ticketbox.ui.screens.IncomePlanIntentSummary(it) }
                state.debtAdjustments[row.id]?.let { com.ticketbox.ui.screens.DebtAdjustmentIntentSummary(it) }
                FailedCard(
                    row = row,
                    debtCreation = state.failedDebtCreations[row.id],
                    busy = state.busyRowId == row.id,
                    onRetry = { actions.onRetry(row) }.takeIf {
                        (row.type != PendingMutationType.UpdateIncomePlan || state.incomeEdits[row.id]?.hasSupportedIntent == true) &&
                            (row.type != PendingMutationType.RecordDebtAdjustment || state.debtAdjustments[row.id]?.hasSupportedIntent == true)
                    },
                    onDrop = { actions.onDropFailed(row) },
                )
            }
        }
    }
}

@Composable
private fun SyncStatusQuarantineSection(count: Int, clearEnabled: Boolean, onClear: () -> Unit) {
    if (count > 0) {
        SettingsSection(
            title = stringResource(R.string.sync_status_section_quarantined),
            icon = Icons.Filled.SyncProblem,
        ) {
            SettingsOpenPanel {
                Text(
                    text = stringResource(
                        R.string.sync_status_quarantined_body,
                        count,
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                AppAdaptiveTrailingActionRow {
                    AppOutlinedButton(
                        modifier = it,
                        onClick = onClear,
                        options = AppOutlinedButtonOptions(
                            enabled = clearEnabled,
                            danger = true,
                        ),
                    ) {
                        Text(stringResource(R.string.sync_status_quarantined_remove_button))
                    }
                }
            }
        }
    }
}

@Composable
private fun ConflictCard(
    row: OutboxRow,
    busy: Boolean,
    onKeepMine: () -> Unit,
    onDropMine: () -> Unit,
) {
    // Only expense mutations can refresh state and retry as "keep mine".
    val canKeep = row.targetId.startsWith("expense:")
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = stringResource(R.string.sync_status_conflict_offline_prefix, mutationLabel(row.type)),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_conflict_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            SyncStatusRecoveryActions(
                primary = if (canKeep) {
                    SyncStatusActionButton(
                        text = stringResource(R.string.sync_status_conflict_button_keep_mine),
                        icon = Icons.Filled.CloudUpload,
                        enabled = !busy,
                        onClick = onKeepMine,
                    )
                } else {
                    null
                },
                danger = SyncStatusActionButton(
                    text = stringResource(R.string.sync_status_conflict_button_drop_mine),
                    enabled = !busy,
                    onClick = onDropMine,
                ),
            )
        }
    }
}

@Composable
private fun FailedCard(
    row: OutboxRow,
    debtCreation: PendingDebtCreation?,
    busy: Boolean,
    onRetry: (() -> Unit)?,
    onDrop: () -> Unit,
) {
    // Expired rows cannot be retried because the server-side idempotency key may be gone.
    val expired = isExpiredFailure(row.lastError)
    SettingsOpenPanel(
        modifier = Modifier.semantics(mergeDescendants = true) {},
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = if (row.type == PendingMutationType.CreateDebt) mutationLabel(row.type)
                else stringResource(R.string.sync_status_failed_offline_prefix, mutationLabel(row.type)),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            debtCreation?.let { DebtCreationIntentSummary(it) }
            Text(
                text = friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_failed_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            SyncStatusRecoveryActions(
                primary = if (expired || onRetry == null) {
                    null
                } else {
                    SyncStatusActionButton(
                        text = stringResource(R.string.sync_status_failed_button_retry),
                        icon = Icons.Filled.RestartAlt,
                        enabled = !busy,
                        onClick = onRetry,
                    )
                },
                danger = SyncStatusActionButton(
                    text = if (expired) {
                        stringResource(R.string.sync_status_failed_button_remove)
                    } else {
                        stringResource(R.string.sync_status_failed_button_drop)
                    },
                    enabled = !busy,
                    onClick = onDrop,
                ),
            )
        }
    }
}

@Composable
private fun SyncStatusRecoveryActions(
    primary: SyncStatusActionButton?,
    danger: SyncStatusActionButton,
) {
    if (primary == null) {
        AppAdaptiveTrailingActionRow {
            AppOutlinedButton(
                modifier = it,
                onClick = danger.onClick,
                options = AppOutlinedButtonOptions(enabled = danger.enabled, danger = true),
            ) {
                Text(danger.text)
            }
        }
        return
    }
    AppAdaptiveEditActionLayout(actionCount = 2, compact = false, stackTwoActionsOnNarrow = true) { mode ->
        when (mode) {
            AppAdaptiveEditActionMode.Stacked -> Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ) {
                AppPrimaryButton(
                    text = primary.text,
                    icon = primary.icon ?: Icons.Filled.CloudUpload,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = primary.enabled,
                    onClick = primary.onClick,
                )
                AppOutlinedButton(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = danger.onClick,
                    options = AppOutlinedButtonOptions(enabled = danger.enabled, danger = true),
                ) {
                    Text(danger.text)
                }
            }
            AppAdaptiveEditActionMode.Compact,
            AppAdaptiveEditActionMode.Inline -> Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap, Alignment.End),
            ) {
                AppPrimaryButton(
                    text = primary.text,
                    icon = primary.icon ?: Icons.Filled.CloudUpload,
                    enabled = primary.enabled,
                    onClick = primary.onClick,
                )
                AppOutlinedButton(
                    onClick = danger.onClick,
                    options = AppOutlinedButtonOptions(enabled = danger.enabled, danger = true),
                ) {
                    Text(danger.text)
                }
            }
        }
    }
}

/** A reaper age-cap expiry is terminal; retry cannot help. */
internal fun isExpiredFailure(lastError: String?): Boolean =
    lastError?.startsWith("outbox_row_expired") == true

@Composable
private fun mutationLabel(type: PendingMutationType): String = stringResource(syncStatusMutationLabelRes(type))

@StringRes
internal fun syncStatusMutationLabelRes(type: PendingMutationType): Int =
    syncStatusMutationLabelResources.getValue(type)

internal val syncStatusMutationLabelResources = mapOf(
    PendingMutationType.PatchExpense to R.string.sync_status_mutation_patch_expense,
    PendingMutationType.CorrectExpense to R.string.sync_status_mutation_correct_expense,
    PendingMutationType.CreateExpense to R.string.sync_status_mutation_create_expense,
    PendingMutationType.CreateDebt to R.string.sync_status_mutation_create_debt,
    PendingMutationType.RecordDebtAdjustment to R.string.debt_action_adjustment_title,
    PendingMutationType.ConfirmExpense to R.string.sync_status_mutation_confirm_expense,
    PendingMutationType.RejectExpense to R.string.sync_status_mutation_reject_expense,
    PendingMutationType.MarkNotDuplicate to R.string.sync_status_mutation_mark_not_duplicate,
    PendingMutationType.RetryOcr to R.string.sync_status_mutation_retry_ocr,
    PendingMutationType.RecognizeText to R.string.sync_status_mutation_recognize_text,
    PendingMutationType.ReplaceItems to R.string.sync_status_mutation_replace_items,
    PendingMutationType.ReplaceSplits to R.string.sync_status_mutation_replace_splits,
    PendingMutationType.AcknowledgeItemsMismatch to R.string.sync_status_mutation_acknowledge_items_mismatch,
    PendingMutationType.UpdateCategoryRule to R.string.sync_status_mutation_update_category_rule,
    PendingMutationType.DeleteCategoryRule to R.string.sync_status_mutation_delete_category_rule,
    PendingMutationType.UpdateMerchantAlias to R.string.sync_status_mutation_update_merchant_alias,
    PendingMutationType.DeleteMerchantAlias to R.string.sync_status_mutation_delete_merchant_alias,
    PendingMutationType.UpdateGoal to R.string.sync_status_mutation_update_goal,
    PendingMutationType.UpdateIncomePlan to R.string.sync_status_mutation_update_income_plan,
    PendingMutationType.CreateRecurringItem to R.string.sync_status_mutation_create_recurring_item,
    PendingMutationType.UpdateRecurringItem to R.string.sync_status_mutation_update_recurring_item,
    PendingMutationType.SetRecurringOccurrencePayment to R.string.sync_status_mutation_recurring_occurrence,
    PendingMutationType.CreateExpenseOffset to R.string.sync_status_mutation_create_expense_offset,
    PendingMutationType.VoidExpenseOffset to R.string.sync_status_mutation_void_expense_offset,
    PendingMutationType.Unknown to R.string.sync_status_mutation_unknown,
)

/** Translate known outbox error markers; never expose raw transport or engine errors to users. */
@Composable
private fun friendlyLastError(raw: String?, fallback: String): String {
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
