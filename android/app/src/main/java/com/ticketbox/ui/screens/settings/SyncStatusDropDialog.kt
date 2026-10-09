package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.DebtCreationIntentSummary
import com.ticketbox.ui.screens.debtWriteStopExplanation

/** Immutable user selection; a queue refresh cannot relabel an open discard confirmation. */
internal data class SyncStatusDropSelection(
    val row: OutboxRow,
    val failed: Boolean,
    val debtCreation: PendingDebtCreation?,
    val recurringOccurrence: com.ticketbox.data.repository.PendingOccurrencePayment? = null,
    val incomeSubmission: com.ticketbox.data.repository.PendingIncomePlanSubmission? = null,
    val debtWrite: com.ticketbox.data.repository.PendingDebtWrite? = null,
    val budgetSave: com.ticketbox.data.repository.PendingBudgetSave? = null,
    val recurringOriginal: com.ticketbox.data.repository.RecurringPendingIntent? = null,
    val goalCreation: com.ticketbox.data.repository.PendingGoalCreation? = null,
    val goalEdit: com.ticketbox.data.repository.PendingGoalEdit? = null,
    val categoryRule: com.ticketbox.data.repository.PendingCategoryRuleSubmission? = null,
    val ruleApplication: com.ticketbox.data.repository.PendingRuleApplication? = null,
    val arrangement: com.ticketbox.data.repository.PendingMonthlyArrangement? = null,
)

private data class DropConfirmationText(val title: String, val text: String, val confirmWord: String)

@Composable
internal fun SyncStatusDropDialog(
    selection: SyncStatusDropSelection,
    busy: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val copy = dropConfirmationText(selection)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(copy.title) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                selection.debtCreation?.let { DebtCreationIntentSummary(it) }
                selection.recurringOccurrence?.let { com.ticketbox.ui.screens.recurring.RecurringOccurrenceIntentSummary(it) }
                selection.incomeSubmission?.let { com.ticketbox.ui.screens.IncomePlanIntentSummary(it) }
                selection.debtWrite?.let { com.ticketbox.ui.screens.DebtWriteIntentSummary(it) }
                selection.goalEdit?.request?.let { request ->
                    com.ticketbox.ui.screens.plan.SpendingGoalOriginalSummary(request.name, request.month,
                        request.targetAmountCents, request.homeCurrencyCode)
                }
                selection.goalCreation?.let { com.ticketbox.ui.screens.GoalCreationIntentSummary(it) }
                selection.categoryRule?.let { com.ticketbox.ui.screens.settings.categoryrules.CategoryRuleSubmissionSummary(it) }
                selection.ruleApplication?.let { com.ticketbox.ui.screens.settings.categoryrules.RuleApplicationSubmissionSummary(it) }
                selection.recurringOriginal?.let { com.ticketbox.ui.screens.recurring.RecurringManualIntentSummary(it) }
                selection.budgetSave?.let { com.ticketbox.ui.screens.budget.BudgetSaveIntentSummary(it) }
                selection.arrangement?.let { com.ticketbox.ui.screens.plan.MonthlyArrangementIntentSummary(it) }
                Text(copy.text)
            }
        },
        confirmButton = {
            TextButton(enabled = !busy, onClick = onConfirm) {
                Text(copy.confirmWord, color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun dropConfirmationText(selection: SyncStatusDropSelection): DropConfirmationText {
    val row = selection.row
    return when {
        row.type in originalCreationStopLabels -> originalCreationStopLabels.getValue(row.type).let { (title, body) ->
            DropConfirmationText(stringResource(title), stringResource(body), stringResource(title))
        }
        row.type in com.ticketbox.viewmodel.categoryRuleSubmissionTypes -> DropConfirmationText(
            stringResource(R.string.category_rule_submission_stop), stringResource(R.string.category_rule_submission_stop_body),
            stringResource(R.string.category_rule_submission_stop),
        )
        row.type == PendingMutationType.CreateGoal || row.type == PendingMutationType.UpdateGoal -> DropConfirmationText(
            stringResource(R.string.goal_creation_drop), stringResource(R.string.goal_submission_stop_body),
            stringResource(R.string.goal_creation_drop),
        )
        row.type in setOf(PendingMutationType.CreateRecurringItem, PendingMutationType.UpdateRecurringItem) -> DropConfirmationText(
            stringResource(R.string.recurring_original_drop), stringResource(R.string.recurring_original_drop_explanation),
            stringResource(R.string.recurring_original_drop),
        )
        row.type == PendingMutationType.SaveMonthlyArrangement -> DropConfirmationText(
            stringResource(R.string.arrangement_stop), stringResource(R.string.arrangement_stop_body), stringResource(R.string.arrangement_stop),
        )
        row.type == PendingMutationType.SaveMonthlyBudget -> DropConfirmationText(
            stringResource(R.string.budget_save_drop), stringResource(R.string.budget_save_drop_explanation),
            stringResource(R.string.budget_save_drop),
        )
        row.type in com.ticketbox.data.repository.DEBT_WRITE_TYPES -> debtWriteDropConfirmationText(selection)
        selection.incomeSubmission?.requiresReview == true -> DropConfirmationText(
            stringResource(R.string.income_plan_submission_stop_record),
            stringResource(R.string.income_plan_submission_stop_record_explanation),
            stringResource(R.string.income_plan_submission_stop_record),
        )
        row.type in com.ticketbox.viewmodel.incomePlanSubmissionTypes -> DropConfirmationText(
            stringResource(R.string.income_plan_edit_drop),
            stringResource(R.string.income_plan_edit_drop_explanation),
            stringResource(R.string.income_plan_edit_drop),
        )
        row.type == PendingMutationType.SetRecurringOccurrencePayment -> DropConfirmationText(
            stringResource(R.string.occurrence_drop),
            stringResource(R.string.occurrence_drop_explanation),
            stringResource(R.string.occurrence_drop),
        )
        else -> legacyDropConfirmationText(selection)
    }
}

private val originalCreationStopLabels = mapOf(
    PendingMutationType.ApplyConfirmedRules to (R.string.rule_application_stop to R.string.rule_application_stop_body),
    PendingMutationType.SaveManualExchangeRate to (R.string.advice_rate_stop to R.string.advice_rate_stop_body),
    PendingMutationType.CreateExpense to (R.string.manual_submission_stop to R.string.manual_submission_stop_body),
    PendingMutationType.CapturePaymentNotification to (R.string.notification_capture_stop to R.string.notification_capture_stop_explanation),
    PendingMutationType.DismissRepaymentDraft to (R.string.debt_write_drop to R.string.repayment_review_stopped),
)

@Composable
private fun legacyDropConfirmationText(selection: SyncStatusDropSelection): DropConfirmationText {
    val row = selection.row
    val label = stringResource(syncStatusMutationLabelResources.getValue(row.type))
    val expired = selection.failed && isExpiredFailure(row.lastError)
    val debtCreation = row.type == PendingMutationType.CreateDebt
    return when {
    row.lastError in com.ticketbox.data.repository.EXPENSE_ORIGINAL_REVIEW_ERRORS -> DropConfirmationText(
        stringResource(R.string.sync_status_accepted_stop_title), stringResource(R.string.sync_status_accepted_stop_body),
        stringResource(R.string.sync_status_accepted_stop))
    !selection.failed -> DropConfirmationText(
        stringResource(R.string.sync_status_conflict_drop_dialog_title),
        stringResource(R.string.sync_status_conflict_drop_dialog_text, label),
        stringResource(R.string.sync_status_drop_dialog_confirm),
    )
    expired -> DropConfirmationText(
        stringResource(R.string.sync_status_failed_drop_dialog_title_expired),
        if (debtCreation) stringResource(R.string.debt_create_expired_drop_dialog_text)
        else stringResource(R.string.sync_status_failed_drop_dialog_text_expired, label),
        stringResource(R.string.sync_status_drop_dialog_confirm_remove),
    )
    else -> DropConfirmationText(
        if (debtCreation) stringResource(R.string.debt_create_drop_dialog_title)
        else stringResource(R.string.sync_status_failed_drop_dialog_title),
        if (debtCreation) stringResource(R.string.debt_create_drop_dialog_text)
        else stringResource(R.string.sync_status_failed_drop_dialog_text, label),
        stringResource(R.string.sync_status_drop_dialog_confirm),
    )
    }
}

@Composable
private fun debtWriteDropConfirmationText(selection: SyncStatusDropSelection): DropConfirmationText = DropConfirmationText(
    stringResource(R.string.debt_write_drop), stringResource(debtWriteStopExplanation(selection.debtWrite)),
    stringResource(R.string.debt_write_drop),
)
