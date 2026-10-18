package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import com.ticketbox.data.repository.manualCreateReviewExpenseId
import com.ticketbox.data.repository.canReviewFunding
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.key
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.data.repository.parseExpenseTargetRef
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppIconSize
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.DebtCreationIntentSummary
import com.ticketbox.data.repository.EXPENSE_ORIGINAL_REVIEW_ERRORS
import com.ticketbox.viewmodel.OutboxStatusUiState
import com.ticketbox.viewmodel.OutboxStatusViewModel

@Composable
fun SyncStatusScreen(
    viewModel: OutboxStatusViewModel,
    onBack: () -> Unit,
    navigation: SyncStatusNavigation,
    manualClientRef: String? = null,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val actions = remember(viewModel, navigation) {
        SyncStatusActions(
            onOpenExpense = navigation.onOpenExpense,
            onRefreshAcceptedResult = viewModel::refreshAcceptedResult,
            onKeepMine = viewModel::keepMine,
            onDropMine = viewModel::dropMine,
            onRetry = viewModel::retry,
            onDropFailed = viewModel::dropFailed,
            onClearQuarantined = viewModel::clearQuarantined,
            onOpenBudget = navigation.onOpenBudget,
            onOpenRecurring = navigation.onOpenRecurring,
            onOpenGoalCreation = navigation.onOpenGoalCreation,
            onOpenGoalEdit = navigation.onOpenGoalEdit,
            onOpenRuleSubmission = navigation.onOpenRuleSubmission,
            onOpenIncomeSubmission = navigation.onOpenIncomeSubmission,
            onOpenRateSubmission = navigation.onOpenRateSubmission,
            onRepairCorrectionRate = navigation.onRepairCorrectionRate,
            onOpenArrangement = navigation.onOpenArrangement,
            onOpenFunds = navigation.onOpenFunds,
        )
    }
    SyncStatusScreenContent(state = state, actions = actions, onBack = onBack, onOpenInbox = navigation.onOpenInbox,
        manualClientRef = manualClientRef)
}

data class SyncStatusNavigation(
    val onOpenExpense: (Long) -> Unit,
    val onOpenInbox: () -> Unit,
    val onOpenBudget: (String) -> Unit,
    val onOpenRecurring: () -> Unit,
    val onOpenGoalCreation: (com.ticketbox.data.repository.PendingGoalCreation) -> Unit,
    val onOpenGoalEdit: (com.ticketbox.data.repository.PendingGoalEdit) -> Unit,
    val onOpenRuleSubmission: (Long) -> Unit,
    val onOpenIncomeSubmission: (Long) -> Unit,
    val onOpenRateSubmission: (Long) -> Unit,
    val onRepairCorrectionRate: com.ticketbox.ui.screens.expense.fact.CorrectionRateAction,
    val onOpenArrangement: (String) -> Unit = {},
    val onOpenFunds: () -> Unit = {},
)

/** Row callbacks grouped to keep the content API small and testable. */
internal data class SyncStatusActions(
    val onOpenExpense: (Long) -> Unit,
    val onRefreshAcceptedResult: (OutboxRow) -> Unit,
    val onKeepMine: (OutboxRow) -> Unit,
    val onDropMine: (OutboxRow) -> Unit,
    val onRetry: (OutboxRow) -> Unit,
    val onDropFailed: (OutboxRow) -> Unit,
    val onClearQuarantined: () -> Unit,
    val onOpenBudget: (String) -> Unit,
    val onOpenRecurring: () -> Unit,
    val onOpenGoalCreation: (com.ticketbox.data.repository.PendingGoalCreation) -> Unit,
    val onOpenGoalEdit: (com.ticketbox.data.repository.PendingGoalEdit) -> Unit,
    val onOpenRuleSubmission: (Long) -> Unit,
    val onOpenIncomeSubmission: (Long) -> Unit,
    val onOpenRateSubmission: (Long) -> Unit,
    val onRepairCorrectionRate: com.ticketbox.ui.screens.expense.fact.CorrectionRateAction,
    val onOpenArrangement: (String) -> Unit = {},
    val onOpenFunds: () -> Unit = {},
)

internal data class SyncStatusActionButton(
    val text: String,
    val icon: ImageVector? = null,
    val enabled: Boolean,
    val danger: Boolean = false,
    val onClick: () -> Unit,
)

@Composable
internal fun SyncStatusScreenContent(
    state: OutboxStatusUiState,
    actions: SyncStatusActions,
    onBack: () -> Unit,
    onOpenInbox: () -> Unit,
    manualClientRef: String? = null,
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
        onBack = onBack,
        heading = { SettingsPageHeading(
            title = stringResource(R.string.sync_status_page_title),
            subtitle = stringResource(R.string.sync_status_page_subtitle),
            onBack = onBack,
            backLabel = stringResource(R.string.sync_status_back),
        ) },
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        SyncStatusPageBody(
            state = state,
            manualClientRef = manualClientRef,
            onOpenInbox = onOpenInbox,
            actions = actions.copy(
                onDropMine = { confirmingDrop = SyncStatusDropSelection(it, failed = false, debtCreation = null,
                    recurringOccurrence = state.recurringOccurrences[it.id], incomeSubmission = state.incomeSubmissions[it.id], debtWrite = state.debtWrites[it.id], budgetSave = state.budgetSaves[it.id], recurringOriginal = state.recurringItems[it.id], goalCreation = state.goalCreations[it.id], goalEdit = state.goalEdits[it.id], categoryRule = state.categoryRules[it.id], ruleApplication = state.ruleApplications[it.id], arrangement = state.arrangements[it.id]) },
                onDropFailed = { row ->
                    if (row.type in setOf(PendingMutationType.CorrectExpense, PendingMutationType.CreateBillSplitInvitation, PendingMutationType.AcceptBillSplitInvitation)) actions.onDropFailed(row)
                    else confirmingDrop = SyncStatusDropSelection(row, failed = true, debtCreation = state.failedDebtCreations[row.id],
                        recurringOccurrence = state.recurringOccurrences[row.id], incomeSubmission = state.incomeSubmissions[row.id], debtWrite = state.debtWrites[row.id], budgetSave = state.budgetSaves[row.id], recurringOriginal = state.recurringItems[row.id], goalCreation = state.goalCreations[row.id], goalEdit = state.goalEdits[row.id], categoryRule = state.categoryRules[row.id], ruleApplication = state.ruleApplications[row.id], arrangement = state.arrangements[row.id])
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
    manualClientRef: String?,
) {
    if (!state.bindingReady) {
        Text(stringResource(if (state.binding == null) R.string.sync_status_binding_unavailable else R.string.sync_status_binding_loading))
        return
    }
    val status = state.status
    ManualCreationSubmissionSection(state, actions, manualClientRef)
    if (manualClientRef != null) return
    SyncStatusIncomeReviews(state, actions)
    SyncStatusRateReviews(state, actions)
    SyncStatusBillSplitSection(state, actions)
    SyncStatusExpenseReviewSection(state, actions)
    SyncStatusUploadSection(state, onOpenInbox)
    if ((status.conflicts + status.failed).any { it.type == PendingMutationType.FinancialAccountCommand }) {
        SettingsSection(title = stringResource(R.string.sync_status_mutation_funds_command)) {
            Text(stringResource(R.string.funds_sync_note))
            TextButton(onClick = actions.onOpenFunds) { Text(stringResource(R.string.funds_continue_task)) }
        }
    }

    SyncStatusDebtSections(state, actions)

    val conflicts = status.conflicts.filter { it.type !in SEPARATE_RECOVERY_TYPES }
    if (conflicts.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_needs_action)) {
            conflicts.forEach { row ->
                key(state.binding, row.id) {
                    SettingsDetailRow(
                        title = stringResource(syncStatusMutationLabelResources.getValue(row.type)),
                        subtitle = stringResource(R.string.sync_status_review_entry_hint),
                        icon = R.drawable.ic_lucide_git_branch,
                    ) {
                        SyncStatusOriginalIntentSummary(row, state, actions)
                        ConflictCard(row = row, busy = state.busyRowId == row.id, actions = actions)
                    }
                }
            }
        }
    }

    val failures = status.failed.filter { it.type !in SEPARATE_RECOVERY_TYPES && it.lastError !in EXPENSE_ORIGINAL_REVIEW_ERRORS }
    if (failures.isNotEmpty()) {
        SettingsSection(title = stringResource(R.string.sync_status_section_failed)) {
            failures.forEach { row ->
                SyncStatusOriginalIntentSummary(row, state, actions)
                FailedCard(
                    row = row,
                    debtCreation = state.failedDebtCreations[row.id],
                    busy = state.busyRowId == row.id,
                    onRetry = { actions.onRetry(row) }.takeIf { state.offersRetry(row) },
                    actions = actions,
                )
            }
        }
    }
    SyncStatusExpenseRefreshSection(state, actions)
    SyncStatusQuarantineSection(
        count = status.quarantinedCount,
        clearEnabled = !state.isClearingQuarantine && state.busyRowId == null,
        onClear = actions.onClearQuarantined,
    )
    SyncStatusOverviewSection(status, state.correctionObservation.corrections, state.debtWrites.values.toList(), state.incomeSubmissions.values.toList(), state.manualRates.values.toList())
}

private val SEPARATE_RECOVERY_TYPES = setOf(PendingMutationType.CreateExpense, PendingMutationType.CreateBillSplitInvitation, PendingMutationType.AcceptBillSplitInvitation,
    PendingMutationType.CorrectExpense, PendingMutationType.UploadScreenshot, PendingMutationType.OriginalAttachment, PendingMutationType.FinancialAccountCommand)

@Composable
private fun SyncStatusUploadSection(state: OutboxStatusUiState, onOpenInbox: () -> Unit) {
    val rows = (state.status.conflicts + state.status.failed).filter { it.type == PendingMutationType.UploadScreenshot }
    if (rows.isEmpty()) return
    SettingsSection(title = stringResource(R.string.sync_status_mutation_upload_screenshot)) {
        Text(stringResource(R.string.sync_status_upload_recovery_body), style = MaterialTheme.typography.bodyMedium)
        SyncStatusItemActions(next = SyncStatusActionButton(text = stringResource(R.string.sync_status_open_uploads),
            icon = Icons.Filled.CloudUpload, enabled = true, onClick = onOpenInbox))
    }
}

@Composable
private fun SyncStatusQuarantineSection(count: Int, clearEnabled: Boolean, onClear: () -> Unit) {
    if (count > 0) {
        SettingsSection(
            title = stringResource(R.string.sync_status_section_quarantined),
        ) {
            SettingsDetailRow(
                title = stringResource(R.string.sync_status_quarantine_entry_title),
                subtitle = stringResource(R.string.sync_status_quarantine_entry_hint, count),
                icon = R.drawable.ic_lucide_user_round_x,
            ) {
                Text(
                    text = stringResource(
                        R.string.sync_status_quarantined_body,
                        count,
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                SyncStatusItemActions(
                    next = null,
                    other = SyncStatusActionButton(
                        text = stringResource(R.string.sync_status_quarantined_remove_button),
                        enabled = clearEnabled,
                        danger = true,
                        onClick = onClear,
                    ),
                )
            }
        }
    }
}

@Composable
internal fun ConflictCard(
    row: OutboxRow,
    busy: Boolean,
    actions: SyncStatusActions,
) {
    // Only expense mutations can refresh state and retry as "keep mine".
    val originalOffset = row.type == PendingMutationType.CreateExpenseOffset
    val reviewOriginal = row.type == PendingMutationType.UndoExpense || row.lastError in EXPENSE_ORIGINAL_REVIEW_ERRORS || row.canReviewFunding()
    val canKeep = !reviewOriginal && row.type !in com.ticketbox.viewmodel.incomePlanSubmissionTypes && !originalOffset && row.type !in com.ticketbox.viewmodel.categoryRuleSubmissionTypes &&
        row.type !in setOf(PendingMutationType.CreateExpense, PendingMutationType.CorrectExpense, PendingMutationType.CreateBillSplitInvitation) && row.targetId.startsWith("expense:")
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
            SyncStatusItemActions(
                next = if (originalOffset || reviewOriginal) expenseReviewAction(row, busy, actions) else if (canKeep) {
                    SyncStatusActionButton(
                        text = stringResource(R.string.sync_status_conflict_button_keep_mine),
                        icon = Icons.Filled.CloudUpload,
                        enabled = !busy,
                        onClick = { actions.onKeepMine(row) },
                    )
                } else {
                    null
                },
                other = SyncStatusActionButton(
                    text = stringResource(R.string.sync_status_conflict_button_drop_mine),
                    enabled = !busy,
                    danger = true,
                    onClick = { actions.onDropMine(row) },
                ),
            )
        }
    }
}

@Composable
internal fun FailedCard(
    row: OutboxRow,
    debtCreation: PendingDebtCreation?,
    busy: Boolean,
    onRetry: (() -> Unit)?,
    actions: SyncStatusActions,
) {
    val expired = isExpiredFailure(row.lastError)
    val reviewMessage = when {
        row.type == PendingMutationType.UndoExpense && row.lastError == "expense_not_found" ->
            R.string.sync_status_undo_unavailable
        row.type == PendingMutationType.CreateExpenseOffset && onRetry == null ->
            R.string.expense_offset_original_requires_review
        else -> null
    }
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
                text = if (reviewMessage != null) stringResource(reviewMessage)
                    else friendlyLastError(row.lastError, fallback = stringResource(R.string.sync_status_failed_fallback)),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            SyncStatusItemActions(
                next = if (reviewMessage != null) {
                    expenseReviewAction(row, busy, actions)
                } else if (row.manualCreateReviewExpenseId() != null) {
                    SyncStatusActionButton(text = stringResource(R.string.ledger_manual_review_existing), enabled = !busy,
                        onClick = { row.manualCreateReviewExpenseId()?.let(actions.onOpenExpense) })
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
                other = SyncStatusActionButton(
                    text = stringResource(failedCardDangerLabels.getValue(expired)),
                    enabled = !busy,
                    danger = true,
                    onClick = { actions.onDropFailed(row) },
                ),
            )
        }
    }
}

@Composable
private fun expenseReviewAction(row: OutboxRow, busy: Boolean, actions: SyncStatusActions): SyncStatusActionButton? {
    val id = com.ticketbox.data.repository.expenseRefreshTargetId(row.targetId, row.receiptJson) ?: return null
    return SyncStatusActionButton(text = stringResource(R.string.expense_offset_review_current),
        icon = Icons.AutoMirrored.Filled.OpenInNew, enabled = !busy,
        onClick = { actions.onOpenExpense(id) })
}

/**
 * One action row per to-do item: the next step is the only bordered control, and stop or view
 * links sit beside it as text. Items on this page never compete with full-width primaries.
 */
@Composable
internal fun SyncStatusItemActions(next: SyncStatusActionButton?, other: SyncStatusActionButton? = null) {
    if (next == null && other == null) return
    SyncStatusActionLayout(
        modifier = Modifier.fillMaxWidth(),
        gap = AppSpacing.smallGap,
    ) {
        next?.let { action ->
            AppOutlinedButton(onClick = action.onClick, options = AppOutlinedButtonOptions(enabled = action.enabled)) {
                action.icon?.let {
                    Icon(it, contentDescription = null, modifier = Modifier.size(AppIconSize.compact))
                    Spacer(Modifier.width(AppSpacing.smallGap))
                }
                Text(action.text)
            }
        }
        other?.let { action ->
            TextButton(
                onClick = action.onClick,
                enabled = action.enabled,
                modifier = Modifier.heightIn(min = AppSpacing.controlMinHeight),
                colors = if (action.danger) {
                    ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
                } else {
                    ButtonDefaults.textButtonColors()
                },
            ) {
                Text(action.text)
            }
        }
    }
}

/**
 * End-aligned: on one line the next step sits last (rightmost); when large text forces a wrap the
 * next step stays on top so it is still read first, with the stop or view link below it.
 */
@Composable
private fun SyncStatusActionLayout(modifier: Modifier, gap: Dp, content: @Composable () -> Unit) {
    Layout(content = content, modifier = modifier) { measurables, constraints ->
        val loose = constraints.copy(minWidth = 0, minHeight = 0)
        val placeables = measurables.map { it.measure(loose) }
        val gapPx = gap.roundToPx()
        val inline = placeables.sumOf { it.width } + gapPx * (placeables.size - 1) <= constraints.maxWidth
        val width = constraints.maxWidth
        if (inline) {
            val height = placeables.maxOf { it.height }
            layout(width, height) {
                var x = width
                placeables.forEach { placeable ->
                    x -= placeable.width
                    placeable.placeRelative(x, (height - placeable.height) / 2)
                    x -= gapPx
                }
            }
        } else {
            val height = placeables.sumOf { it.height } + gapPx * (placeables.size - 1)
            layout(width, height) {
                var y = 0
                placeables.forEach { placeable ->
                    placeable.placeRelative(width - placeable.width, y)
                    y += placeable.height + gapPx
                }
            }
        }
    }
}

/** A reaper age-cap expiry is terminal; retry cannot help. */
internal fun isExpiredFailure(lastError: String?): Boolean =
    lastError?.startsWith("outbox_row_expired") == true

private val failedCardDangerLabels = mapOf(
    true to R.string.sync_status_failed_button_remove,
    false to R.string.sync_status_failed_button_drop,
)

internal val syncStatusMutationLabelResources = mapOf(
    PendingMutationType.FinancialAccountCommand to R.string.sync_status_mutation_funds_command,
    PendingMutationType.UploadScreenshot to R.string.sync_status_mutation_upload_screenshot,
    PendingMutationType.OriginalAttachment to R.string.original_title,
    PendingMutationType.PatchExpense to R.string.sync_status_mutation_patch_expense,
    PendingMutationType.CorrectExpense to R.string.sync_status_mutation_correct_expense,
    PendingMutationType.CreateExpense to R.string.sync_status_mutation_create_expense,
    PendingMutationType.CapturePaymentNotification to R.string.notification_capture_payment,
    PendingMutationType.ResolvePaymentCapture to R.string.payment_capture_submit,
    PendingMutationType.CreateBillSplitInvitation to R.string.sync_status_mutation_create_bill_split,
    PendingMutationType.AcceptBillSplitInvitation to R.string.bill_split_accept_recovery,
    PendingMutationType.CreateDebt to R.string.sync_status_mutation_create_debt,
    PendingMutationType.RecordDebtAdjustment to R.string.debt_action_adjustment_title,
    PendingMutationType.SplitAgreement to R.string.split_agreement_submission,
    PendingMutationType.RecordDebtRepayment to R.string.debt_action_repayment_title,
    PendingMutationType.ConfirmRepaymentDraft to R.string.repayment_review_confirm,
    PendingMutationType.DismissRepaymentDraft to R.string.repayment_review_dismiss_command,
    PendingMutationType.VoidDebt to R.string.debt_action_void_title,
    PendingMutationType.VoidDebtRepayment to R.string.debt_action_repayment_void_title,
    PendingMutationType.SetDebtKind to R.string.debt_kind_sheet_title,
    PendingMutationType.ConfirmExpense to R.string.sync_status_mutation_confirm_expense,
    PendingMutationType.RejectExpense to R.string.sync_status_mutation_reject_expense,
    PendingMutationType.UndoExpense to R.string.sync_status_mutation_undo_expense,
    PendingMutationType.MarkNotDuplicate to R.string.sync_status_mutation_mark_not_duplicate,
    PendingMutationType.RetryOcr to R.string.sync_status_mutation_retry_ocr,
    PendingMutationType.RecognizeText to R.string.sync_status_mutation_recognize_text,
    PendingMutationType.ReplaceItems to R.string.sync_status_mutation_replace_items,
    PendingMutationType.ReplaceSplits to R.string.sync_status_mutation_replace_splits,
    PendingMutationType.AcknowledgeItemsMismatch to R.string.sync_status_mutation_acknowledge_items_mismatch,
    PendingMutationType.UpdateCategoryRule to R.string.sync_status_mutation_update_category_rule,
    PendingMutationType.CreateCategoryRule to R.string.category_rule_submission_create,
    PendingMutationType.ApplyConfirmedRules to R.string.rule_application_original,
    PendingMutationType.DeleteCategoryRule to R.string.sync_status_mutation_delete_category_rule,
    PendingMutationType.UpdateMerchantAlias to R.string.sync_status_mutation_update_merchant_alias,
    PendingMutationType.DeleteMerchantAlias to R.string.sync_status_mutation_delete_merchant_alias,
    PendingMutationType.UpdateGoal to R.string.sync_status_mutation_update_goal,
    PendingMutationType.ReplaceGoalDebtLinks to R.string.debt_goal_links_action,
    PendingMutationType.SetGoalTargetDate to R.string.debt_goal_date_title,
    PendingMutationType.CreateGoal to R.string.goal_creation_label,
    PendingMutationType.CreateIncomePlan to R.string.income_plan_submission_create,
    PendingMutationType.UpdateIncomePlan to R.string.sync_status_mutation_update_income_plan,
    PendingMutationType.SaveMonthlyBudget to R.string.budget_editor_save,
    PendingMutationType.SaveMonthlyArrangement to R.string.arrangement_save,
    PendingMutationType.SaveManualExchangeRate to R.string.advice_rate_submit,
    PendingMutationType.ConfirmRecurringCandidate to R.string.sync_status_mutation_confirm_recurring_candidate,
    PendingMutationType.CreateRecurringItem to R.string.sync_status_mutation_create_recurring_item,
    PendingMutationType.UpdateRecurringItem to R.string.sync_status_mutation_update_recurring_item,
    PendingMutationType.SetRecurringOccurrencePayment to R.string.sync_status_mutation_recurring_occurrence,
    PendingMutationType.CreateExpenseOffset to R.string.sync_status_mutation_create_expense_offset,
    PendingMutationType.VoidExpenseOffset to R.string.sync_status_mutation_void_expense_offset,
    PendingMutationType.Unknown to R.string.sync_status_mutation_unknown,
)
