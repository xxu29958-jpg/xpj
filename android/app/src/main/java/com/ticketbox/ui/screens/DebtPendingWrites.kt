package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingDebtWrite
import com.ticketbox.data.repository.DebtAmountIntent
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.timeInputLabel
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.ui.screens.settings.isExpiredFailure

@Composable
internal fun DebtWriteIntentSummary(pending: PendingDebtWrite) {
    DebtWriteRecoveryContext(pending)
    val intent = pending.intent
    if (intent == null) {
        Text(stringResource(if (pending.row.status == PendingMutationStatus.Abandoned) {
            R.string.debt_write_stopped_unreadable
        } else R.string.debt_write_unsupported))
        return
    }
    Text(intent.subject.label ?: stringResource(R.string.debt_detail_title))
    (intent as? DebtAmountIntent)?.let { amount ->
        Text(stringResource(if (pending.repayment != null) R.string.debt_repayment_pending_amount else R.string.debt_adjustment_original_amount,
            formatDisplayAmount(amount.amountCents, CurrencyDisplay.forRecord(intent.subject.homeCurrencyCode))))
    }
    pending.adjustment?.let { Text(it.request.reason) }
    pending.repayment?.let { Text(stringResource(R.string.debt_repayment_original_date,
        timeInputLabel(it.request.timeInput, it.request.paidAt).asString())) }
    RepaymentReviewIntentSummary(intent)
    pending.debtVoid?.let { Text(stringResource(R.string.debt_action_void_title)); Text(it.request.reason) }
    pending.kind?.let { Text(stringResource(R.string.debt_kind_pending_value, stringResource(debtKindLabelRes(it.request.debtKind)))) }
    pending.repaymentVoid?.let {
        Text(stringResource(R.string.debt_action_repayment_void_title))
        Text(stringResource(R.string.debt_void_original_repayment, it.request.repaymentPublicId))
        Text(it.request.reason)
    }
    if (pending.reductionRejected) Text(stringResource(R.string.debt_adjustment_reduction_rejected))
    if (pending.requiresReview) Text(stringResource(if (pending.legacyKindAccepted) R.string.debt_kind_original_requires_review
        else R.string.debt_void_original_requires_review))
}

@Composable
private fun RepaymentReviewIntentSummary(intent: com.ticketbox.data.repository.DebtWriteIntent) {
    val review = intent as? com.ticketbox.data.repository.RepaymentReviewPayload ?: return
    Text(stringResource(R.string.repayment_review_confirm))
    Text("${review.reviewedCurrency} ${review.reviewedAmount}")
}

@Composable
private fun DebtWriteRecoveryContext(pending: PendingDebtWrite) {
    if (pending.row.status == PendingMutationStatus.Abandoned) {
        Text(stringResource(when {
            pending.legacyVoidAccepted -> R.string.debt_void_accepted_locally_stopped
            pending.legacyKindAccepted -> R.string.debt_kind_accepted_locally_stopped
            else -> R.string.debt_write_stopped_body
        }))
    }
    if (pending.originalBindingChanged && !pending.isTerminal) Text(stringResource(R.string.debt_write_original_binding_changed))
}

/** Original commands remain readable even when the canonical detail cannot be fetched. */
@Composable
internal fun DebtPendingWrites(state: DebtDetailUiState, originalRepayment: PendingDebtWrite?, onResume: () -> Unit,
    recover: (PendingDebtWrite, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (originalRepayment != null) TextButton(onClick = onResume) {
            Text(stringResource(R.string.debt_repayment_resume_original))
        }
        state.pendingWrites.filter {
            it.row.id != originalRepayment?.row?.id && (it.isVoid || it.kind != null || it.row.status != PendingMutationStatus.Done ||
                (state.debt?.rowVersion ?: 0) <= (it.row.expectedRowVersion ?: Long.MAX_VALUE))
        }.forEach { row -> DebtPendingWrite(row, state.canModify, recover) }
    }
}

@Composable
private fun DebtPendingWrite(pending: PendingDebtWrite, canModify: Boolean, recover: (PendingDebtWrite, Boolean) -> Unit) {
    HorizontalDivider()
    Text(stringResource(debtPendingWriteTitle(pending)))
    DebtWriteIntentSummary(pending)
    DebtPendingWriteFailure(pending)
    if (pending.canRetry) {
        TextButton(enabled = canModify, onClick = { recover(pending, false) }) { Text(stringResource(R.string.debt_write_retry)) }
    }
    DebtWriteStopAction(pending, recover)
}

@Composable
private fun DebtWriteStopAction(pending: PendingDebtWrite, recover: (PendingDebtWrite, Boolean) -> Unit) {
    if (!pending.canStop) return
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.debt_write_drop)) }
    if (confirmDrop) AlertDialog(
        onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.debt_write_drop)) },
        text = { Text(stringResource(debtWriteStopExplanation(pending))) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(stringResource(R.string.debt_write_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
}

@androidx.annotation.StringRes
private fun debtPendingWriteTitle(pending: PendingDebtWrite): Int = when {
    pending.requiresReview -> if (pending.legacyKindAccepted) R.string.debt_kind_review_title else R.string.debt_void_review_title
    pending.row.status == PendingMutationStatus.Done -> when {
        pending.kind != null -> R.string.debt_kind_confirmed
        pending.isVoid -> R.string.debt_void_confirmed
        else -> R.string.debt_repayment_confirmed
    }
    pending.row.status == PendingMutationStatus.Abandoned -> R.string.debt_write_stopped
    pending.canStop -> R.string.debt_write_attention
    else -> R.string.debt_write_waiting
}

@androidx.annotation.StringRes
internal fun debtWriteStopExplanation(pending: PendingDebtWrite?): Int = when {
    pending?.legacyKindAccepted == true -> R.string.debt_kind_review_stop_explanation
    pending?.requiresReview == true -> R.string.debt_void_review_stop_explanation
    else -> R.string.debt_write_drop_explanation
}

@Composable
private fun DebtPendingWriteFailure(pending: PendingDebtWrite) {
    val status = pending.row.status
    val expired = isExpiredFailure(pending.row.lastError)
    when {
        status == PendingMutationStatus.Abandoned -> Unit
        expired -> Text(stringResource(R.string.debt_write_expired))
        status == PendingMutationStatus.Conflict -> Text(stringResource(R.string.debt_write_conflict))
        pending.row.lastError in setOf("runtime_version_mismatch", "client_upgrade_required") ->
            Text(stringResource(R.string.sync_status_error_protocol_mismatch))
    }
}

/** The original Outbox command is sufficient to read and resume this task, even without the latest debt. */
@Composable
internal fun DebtRepaymentOriginalSubmission(detail: DebtDetailUiState, pending: PendingDebtWrite,
    callbacks: DebtDetailScreenCallbacks, onOpenDebt: () -> Unit) {
    val original = pending.repayment ?: return
    val palette = if (pending.row.status == PendingMutationStatus.Conflict) LocalStateTokens.current.danger else LocalStateTokens.current.warn
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(role = AppPageRole.Stats,
            title = stringResource(R.string.debt_repayment_result_title), subtitle = original.subject.label,
            backText = stringResource(R.string.debt_proposal_back_keep_draft), onBack = callbacks.onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)),
        refresh = AppSecondaryRefreshState(detail.isLoading, callbacks.onRefresh),
        slots = AppSecondaryPageSlots(bottomBar = {
            AppFloatingActionBar {
                if (pending.canRetry) AppPrimaryButton(text = stringResource(R.string.debt_write_retry),
                    enabled = detail.canModify, onClick = { callbacks.onRecoverDebtWrite(pending, false) }, modifier = Modifier.fillMaxWidth())
                TextButton(onClick = callbacks.onBack, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.debt_proposal_back_keep_draft))
                }
            }
        }),
    ) {
        item {
            AppPaperCard(containerColor = palette.bg) {
                Text(stringResource(debtPendingWriteTitle(pending)), color = palette.fg,
                    style = MaterialTheme.typography.bodyMedium, modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding))
            }
        }
        item {
            AppPaperCard {
                Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                    Text(stringResource(R.string.debt_payment_original_amount), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    AppAmountText(formatDisplayAmount(original.amountCents, CurrencyDisplay.forRecord(original.subject.homeCurrencyCode)), role = AppAmountRole.Hero)
                    Text(original.subject.homeCurrencyCode, style = MaterialTheme.typography.bodyMedium)
                    Text(stringResource(R.string.debt_repayment_original_date, timeInputLabel(original.request.timeInput, original.request.paidAt).asString()))
                }
            }
        }
        item {
            DebtWriteRecoveryContext(pending)
            DebtPendingWriteFailure(pending)
            if (!detail.canModify) AppStatusBanner(UiText.res(R.string.debt_proposal_readonly_note), MessageTone.Info)
            if (pending.canRetry) Text(stringResource(R.string.debt_repayment_original_retry_hint), style = MaterialTheme.typography.bodyMedium)
            TextButton(onClick = onOpenDebt) { Text(stringResource(R.string.debt_repayment_open_original_debt)) }
            DebtWriteStopAction(pending, callbacks.onRecoverDebtWrite)
        }
    }
}
