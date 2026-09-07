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
import com.ticketbox.data.repository.parseExpenseTargetRef
import com.ticketbox.ui.components.AppAdaptiveEditActionLayout
import com.ticketbox.ui.components.AppAdaptiveEditActionMode
import com.ticketbox.ui.components.AppAdaptiveTrailingActionRow
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.DebtCreationIntentSummary
import com.ticketbox.ui.screens.expense.fact.CorrectionSubmissionOptions
import com.ticketbox.ui.screens.expense.fact.CorrectionSubmissionActions
import com.ticketbox.viewmodel.OutboxStatusUiState
import com.ticketbox.viewmodel.OutboxStatusViewModel

@Composable
fun SyncStatusScreen(
    viewModel: OutboxStatusViewModel,
    onBack: () -> Unit,
    onOpenExpense: (Long) -> Unit,
    onOpenInbox: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val actions = remember(viewModel, onOpenExpense) {
        SyncStatusActions(
            onOpenExpense = onOpenExpense,
            onKeepMine = viewModel::keepMine,
            onDropMine = viewModel::dropMine,
            onRetry = viewModel::retry,
            onDropFailed = viewModel::dropFailed,
            onClearQuarantined = viewModel::clearQuarantined,
        )
    }
    SyncStatusScreenContent(state = state, actions = actions, onBack = onBack, onOpenInbox = onOpenInbox)
}

/** Row callbacks grouped to keep the content API small and testable. */
internal data class SyncStatusActions(
    val onOpenExpense: (Long) -> Unit,
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
    onOpenInbox: () -> Unit,
) {
    // Dropping an offline edit is irreversible, so both paths require confirmation.
    var confirmingDrop by remember(state.binding) { mutableStateOf<SyncStatusDropSelection?>(null) }
    var confirmingClearQuarantined by remember(state.binding) { mutableStateOf(false) }

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
            onOpenInbox = onOpenInbox,
            actions = actions.copy(
                onDropMine = { confirmingDrop = SyncStatusDropSelection(it, failed = false, debtCreation = null,
                    recurringOccurrence = state.recurringOccurrences[it.id], incomeEdit = state.incomeEdits[it.id], debtAdjustment = state.debtAdjustments[it.id]) },
                onDropFailed = { row ->
                    if (row.type == PendingMutationType.CorrectExpense) actions.onDropFailed(row)
                    else confirmingDrop = SyncStatusDropSelection(row, failed = true, debtCreation = state.failedDebtCreations[row.id],
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
    onOpenInbox: () -> Unit,
) {
    if (!state.bindingReady) {
        Text(stringResource(if (state.binding == null) R.string.sync_status_binding_unavailable else R.string.sync_status_binding_loading))
        return
    }
    val status = state.status
    SyncStatusOverviewSection(status, state.correctionObservation.corrections, state.debtAdjustments.values.toList())
    SyncStatusCorrectionSection(state, actions)
    SyncStatusUploadSection(state, actions, onOpenInbox)

    SyncStatusQuarantineSection(
        count = status.quarantinedCount,
        clearEnabled = !state.isClearingQuarantine && state.busyRowId == null,
        onClear = actions.onClearQuarantined,
    )

    SyncStatusDebtSections(state)

    val conflicts = status.conflicts.filter { it.type !in SEPARATE_RECOVERY_TYPES }
    if (conflicts.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_needs_action), icon = Icons.Filled.SyncProblem) {
            conflicts.forEach { row ->
                SyncStatusOriginalIntentSummary(row, state)
                ConflictCard(
                    row = row,
                    busy = state.busyRowId == row.id,
                    actions = actions,
                )
            }
        }
    }

    val failures = status.failed.filter { it.type !in SEPARATE_RECOVERY_TYPES }
    if (failures.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_failed), icon = Icons.Filled.ErrorOutline) {
            failures.forEach { row ->
                SyncStatusOriginalIntentSummary(row, state)
                FailedCard(
                    row = row,
                    debtCreation = state.failedDebtCreations[row.id],
                    busy = state.busyRowId == row.id,
                    onRetry = { actions.onRetry(row) }.takeIf {
                        (row.type != PendingMutationType.UpdateIncomePlan || state.incomeEdits[row.id]?.hasSupportedIntent == true) &&
                            (row.type != PendingMutationType.RecordDebtAdjustment || state.debtAdjustments[row.id]?.canRetry == true) &&
                            (row.type != PendingMutationType.CreateExpenseOffset || row.id in state.retryableOffsetIds)
                    },
                    actions = actions,
                )
            }
        }
    }
}

private val SEPARATE_RECOVERY_TYPES = setOf(PendingMutationType.CorrectExpense, PendingMutationType.UploadScreenshot)

@Composable
private fun SyncStatusUploadSection(state: OutboxStatusUiState, actions: SyncStatusActions, onOpenInbox: () -> Unit) {
    val rows = (state.status.conflicts + state.status.failed).filter { it.type == PendingMutationType.UploadScreenshot }
    if (rows.isEmpty()) return
    SettingsSection(title = stringResource(R.string.sync_status_mutation_upload_screenshot), icon = Icons.Filled.CloudUpload) {
        Text(stringResource(R.string.sync_status_upload_recovery_body), style = MaterialTheme.typography.bodyMedium)
        AppPrimaryButton(text = stringResource(R.string.sync_status_open_uploads), icon = Icons.Filled.CloudUpload,
            onClick = onOpenInbox)
        rows.forEach { row ->
            FailedCard(row, null, state.busyRowId == row.id, onRetry = null, actions = actions.copy(onDropFailed = {
                if (row in state.status.conflicts) actions.onDropMine(row) else actions.onDropFailed(row)
            }))
        }
    }
}

@Composable
private fun SyncStatusCorrectionSection(state: OutboxStatusUiState, actions: SyncStatusActions) {
    state.correctionObservation.corrections.filter { !it.delivered || it.refreshRequired }.forEach { pending ->
        com.ticketbox.ui.screens.expense.fact.ExpenseCorrectionSubmissionCard(
            pending = pending,
            options = CorrectionSubmissionOptions(state.correctionObservation.access?.canModify == true, state.busyRowId != null, false),
            actions = CorrectionSubmissionActions(
                recover = { drop -> if (drop) actions.onDropFailed(pending.row) else actions.onRetry(pending.row) },
                reviewFact = pending.expenseId?.let { id -> { actions.onOpenExpense(id) } }),
        )
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
    actions: SyncStatusActions,
) {
    // Only expense mutations can refresh state and retry as "keep mine".
    val originalOffset = row.type == PendingMutationType.CreateExpenseOffset
    val canKeep = !originalOffset && row.type != PendingMutationType.CorrectExpense && row.targetId.startsWith("expense:")
    SettingsOpenPanel(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Text(
                text = stringResource(R.string.sync_status_conflict_offline_prefix, stringResource(syncStatusMutationLabelResources.getValue(row.type))),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = if (originalOffset) stringResource(R.string.expense_offset_original_requires_review)
                    else friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_conflict_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            SyncStatusRecoveryActions(
                primary = if (originalOffset) offsetReviewAction(row, busy, actions) else if (canKeep) {
                    SyncStatusActionButton(
                        text = stringResource(R.string.sync_status_conflict_button_keep_mine),
                        icon = Icons.Filled.CloudUpload,
                        enabled = !busy,
                        onClick = { actions.onKeepMine(row) },
                    )
                } else {
                    null
                },
                danger = SyncStatusActionButton(
                    text = stringResource(R.string.sync_status_conflict_button_drop_mine),
                    enabled = !busy,
                    onClick = { actions.onDropMine(row) },
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
    actions: SyncStatusActions,
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
                text = if (row.type == PendingMutationType.CreateDebt) stringResource(syncStatusMutationLabelResources.getValue(row.type))
                else stringResource(R.string.sync_status_failed_offline_prefix, stringResource(syncStatusMutationLabelResources.getValue(row.type))),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            debtCreation?.let { DebtCreationIntentSummary(it) }
            Text(
                text = if (row.type == PendingMutationType.CreateExpenseOffset && onRetry == null)
                    stringResource(R.string.expense_offset_original_requires_review)
                    else friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_failed_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            SyncStatusRecoveryActions(
                primary = if (row.type == PendingMutationType.CreateExpenseOffset && onRetry == null) {
                    offsetReviewAction(row, busy, actions)
                } else if (expired || onRetry == null) {
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
                    onClick = { actions.onDropFailed(row) },
                ),
            )
        }
    }
}

@Composable
private fun offsetReviewAction(row: OutboxRow, busy: Boolean, actions: SyncStatusActions): SyncStatusActionButton? {
    val id = parseExpenseTargetRef(row.targetId)?.toLongOrNull()?.takeIf { it > 0 } ?: return null
    return SyncStatusActionButton(text = stringResource(R.string.expense_offset_review_current), enabled = !busy,
        onClick = { actions.onOpenExpense(id) })
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

@StringRes
internal val syncStatusMutationLabelResources = mapOf(
    PendingMutationType.UploadScreenshot to R.string.sync_status_mutation_upload_screenshot,
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
