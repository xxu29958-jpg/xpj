package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.repository.ManualExpenseCreateAdmission
import com.ticketbox.data.repository.ManualExpenseCreationProjection
import com.ticketbox.data.repository.RecurringPaymentAdmissionBlock
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginAdopt
import com.ticketbox.data.repository.admittedClientRef
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.design.AppSpacing

internal data class RecurringPaymentReviewModel(
    val candidates: List<ManualExpenseCreationProjection>,
    val saving: Boolean,
    val error: String?,
) {
    val open: Boolean get() = candidates.isNotEmpty() || error != null
}

internal data class RecurringPaymentReviewEvents(
    val onAdopt: (String) -> Unit,
    val onConfirmUnrelated: () -> Unit,
    val onDismiss: () -> Unit,
    val onOpenExpense: (Long) -> Unit = {},
)

@Composable
internal fun RecurringPaymentReviewDialog(
    model: RecurringPaymentReviewModel,
    events: RecurringPaymentReviewEvents,
) {
    if (!model.open) return
    AlertDialog(
        onDismissRequest = { if (!model.saving) events.onDismiss() },
        title = {
            Text(
                stringResource(R.string.recurring_payment_review_required),
                modifier = Modifier.testTag("recurring-payment-review"),
            )
        },
        text = {
            Column {
                if (model.error != null) {
                    Text(model.error, modifier = Modifier.testTag("recurring-payment-review-error"))
                }
                model.candidates.forEach { candidate ->
                    val ref = candidate.admittedClientRef().orEmpty()
                    key(ref) {
                        RecurringPaymentReviewCandidate(candidate, model.saving, events)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { if (!model.saving && model.candidates.isNotEmpty()) events.onConfirmUnrelated() },
                enabled = !model.saving && model.candidates.isNotEmpty(),
                modifier = Modifier.testTag("recurring-payment-review-not-this-period"),
            ) {
                Text(stringResource(R.string.recurring_payment_review_not_this_period))
            }
        },
        dismissButton = {
            TextButton(
                onClick = { if (!model.saving) events.onDismiss() },
                enabled = !model.saving,
                modifier = Modifier.testTag("recurring-payment-review-dismiss"),
            ) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}

@Composable
private fun RecurringPaymentReviewCandidate(
    candidate: ManualExpenseCreationProjection,
    saving: Boolean,
    events: RecurringPaymentReviewEvents,
) {
    val ref = candidate.admittedClientRef().orEmpty()
    val request = candidate.request
    Text(
        stringResource(R.string.recurring_payment_review_original),
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier.padding(top = AppSpacing.smallGap),
    )
    RecurringPaymentReviewOriginalFacts(request)
    RecurringPaymentReviewStatus(candidate, events.onOpenExpense)
    TextButton(
        onClick = { if (!saving && ref.isNotBlank() && request != null) events.onAdopt(ref) },
        enabled = !saving && ref.isNotBlank() && request != null,
        modifier = Modifier.testTag("recurring-payment-review-adopt:$ref"),
    ) {
        Text(stringResource(R.string.recurring_payment_review_adopt))
    }
}

@Composable
private fun RecurringPaymentReviewOriginalFacts(request: ExpenseManualCreateRequestDto?) {
    if (request == null) {
        Text(stringResource(R.string.manual_submission_unknown))
        return
    }
    Text(
        originalSubmissionAmount(request) ?: stringResource(R.string.manual_submission_unknown),
        style = MaterialTheme.typography.titleLarge,
    )
    request.merchant?.takeIf { it.isNotBlank() }?.let { Text(it) }
    (request.timeInput?.let { com.ticketbox.ui.components.timeInputLabel(it) } ?: request.spentAt ?: request.expenseTime)?.let {
        Text(it, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun RecurringPaymentReviewStatus(
    candidate: ManualExpenseCreationProjection,
    onOpenExpense: (Long) -> Unit,
) {
    Text(stringResource(recurringPaymentReviewStatusRes(candidate.row.status)))
    candidate.acceptedExpenseId?.let { id ->
        TextButton(
            onClick = { onOpenExpense(id) },
            modifier = Modifier.testTag("recurring-payment-review-open:$id"),
        ) {
            Text(stringResource(R.string.manual_submission_open))
        }
    }
}

internal fun recurringPaymentReviewStatusRes(status: PendingMutationStatus): Int = when (status) {
    PendingMutationStatus.Pending -> R.string.manual_submission_waiting
    PendingMutationStatus.InFlight -> R.string.manual_submission_sending
    PendingMutationStatus.Done -> R.string.manual_submission_done
    PendingMutationStatus.Conflict -> R.string.sync_status_conflict_fallback
    PendingMutationStatus.Failed -> R.string.sync_status_failed_fallback
    PendingMutationStatus.Abandoned -> R.string.recurring_payment_review_abandoned
    PendingMutationStatus.Unknown -> R.string.manual_submission_unknown
}

private fun originalSubmissionAmount(request: ExpenseManualCreateRequestDto): String? {
    val currency = request.originalCurrency?.takeIf { it.isNotBlank() }
    val amount = request.originalAmount?.takeIf { it.isNotBlank() }
    return if (currency != null && amount != null) "$currency $amount" else null
}

internal data class RecurringPaymentAdmissionCopy(
    val missing: String,
    val conflict: String,
    val generationChanged: String,
)

internal suspend fun applyPeriodPaymentAdmission(
    ctx: RecurringPaymentEntryContext,
    draft: ExpenseDraft,
    acknowledged: Collection<String>,
    generationChanged: String,
    onDone: (List<ManualExpenseCreationProjection>, ExpenseDraft?) -> Unit,
) {
    when (
        val admission = ctx.factory.repository.manualCreation.create(
            draft,
            ctx.task.binding,
            ctx.task.clientRef,
            RecurringPaymentOrigin(ctx.task.seriesPublicId, ctx.task.period, ctx.task.occurrenceRowVersion),
            acknowledged,
        ).getOrElse { failure -> throw failure }
    ) {
        is ManualExpenseCreateAdmission.Accepted -> onDone(emptyList(), null)
        is ManualExpenseCreateAdmission.ReviewRequired -> onDone(admission.candidates, draft)
        is ManualExpenseCreateAdmission.Blocked -> when (admission.reason) {
            RecurringPaymentAdmissionBlock.MissingGeneration,
            RecurringPaymentAdmissionBlock.DifferentGeneration,
            -> error(generationChanged)
        }
    }
}

internal suspend fun applyAdoptedOrigin(
    ctx: RecurringPaymentEntryContext,
    candidate: String,
    copy: RecurringPaymentAdmissionCopy,
    onDone: (List<ManualExpenseCreationProjection>, String?, Boolean) -> Unit,
) {
    when (
        ctx.factory.repository.manualCreation.adoptOrigin(
            ctx.task.binding,
            candidate,
            ctx.task.seriesPublicId,
            ctx.task.period,
            ctx.task.occurrenceRowVersion,
        )
    ) {
        RecurringPaymentOriginAdopt.Bound -> onDone(emptyList(), null, true)
        RecurringPaymentOriginAdopt.Missing -> onDone(refreshReviewCandidates(ctx), copy.missing, false)
        RecurringPaymentOriginAdopt.Conflict -> onDone(refreshReviewCandidates(ctx), copy.conflict, false)
        is RecurringPaymentOriginAdopt.Blocked -> onDone(
            refreshReviewCandidates(ctx),
            copy.generationChanged,
            false,
        )
    }
}

private suspend fun refreshReviewCandidates(
    ctx: RecurringPaymentEntryContext,
): List<ManualExpenseCreationProjection> =
    ctx.factory.repository.manualCreation.readReviewCandidates(ctx.task.binding).getOrDefault(emptyList())
