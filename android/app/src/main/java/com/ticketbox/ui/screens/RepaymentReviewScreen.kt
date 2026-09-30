package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.RepaymentDraftInboxUiState
import com.ticketbox.viewmodel.RepaymentDraftInboxViewModel

@Composable
internal fun RepaymentReviewScreen(state: RepaymentDraftInboxUiState, model: RepaymentDraftInboxViewModel,
    onOpenDebt: (String) -> Unit) {
    BackHandler { model.reviewEditor.closeReview() }
    var choosingDebt by rememberSaveable { mutableStateOf(false) }
    AppSecondaryScrollableContent(chrome = AppSecondaryPageChrome(role = AppPageRole.Stats,
        title = stringResource(R.string.repayment_review_title),
        subtitle = stringResource(R.string.repayment_review_saved),
        backText = stringResource(R.string.repayment_draft_topbar_back), onBack = model.reviewEditor::closeReview,
        hasBottomBar = false, verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)),
        refresh = AppSecondaryRefreshState(state.isLoading, model::refresh)) {
        item {
            state.drafts.find { it.publicId == state.reviewId }?.let { capture ->
                Text(stringResource(R.string.repayment_draft_original_money), style = MaterialTheme.typography.labelMedium)
                Text("${capture.originalCurrencyCode} ${com.ticketbox.ui.components.formatMinorAmount(capture.originalAmountMinor,
                    CurrencyCode.fromStorageKey(capture.originalCurrencyCode))}", style = MaterialTheme.typography.headlineMedium)
                Text(capture.merchantLabel.orEmpty())
                Text(stringResource(R.string.repayment_draft_captured_at, capture.capturedAt.take(10)))
            }
        }
        state.error?.let { item { AppStatusBanner(it, tone = MessageTone.Danger) } }
        item { RepaymentReviewInputs(state, model) { choosingDebt = true } }
        item { RepaymentReviewDelivery(state, model) }
        state.drafts.find { it.publicId == state.reviewId && !it.isPending }?.let { capture ->
            item {
                if (state.review.input != null && state.review.input.submittedAction == null) {
                    Text(stringResource(R.string.repayment_review_unsubmitted_history))
                }
                RepaymentDraftResolved(capture) { capture.committedDebtPublicId?.let(onOpenDebt) }
            }
        }
    }
    if (choosingDebt) RepaymentDraftTargetSheet(state, state.reviewId,
        onPick = { _, debt -> model.reviewEditor.selectReviewDebt(debt); choosingDebt = false },
        onClose = { choosingDebt = false })
}

@Composable
private fun RepaymentReviewInputs(state: RepaymentDraftInboxUiState, model: RepaymentDraftInboxViewModel, chooseDebt: () -> Unit) {
    val input = state.review.input ?: return
    val pending = state.drafts.any { it.publicId == input.draftPublicId && it.isPending }
    val unsubmitted = pending && input.submittedAction == null
    val editable = unsubmitted && !state.review.bindingChanged && state.canModify && state.pendingActionDraftId == null
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        RepaymentReviewMoney(input.currency, input.amountText, editable, model.reviewEditor::updateReviewMoney)
        Text(input.debtLabel ?: stringResource(R.string.repayment_review_no_target), style = MaterialTheme.typography.titleMedium)
        if (editable) TextButton(onClick = chooseDebt) { Text(stringResource(R.string.repayment_review_select)) }
        Text(stringResource(R.string.repayment_review_money_note), style = MaterialTheme.typography.bodySmall)
        if (unsubmitted && state.review.bindingChanged) {
            RepaymentReviewReopenUnsubmitted(state.canModify, model.reviewEditor::reviewAgain)
        }
        if (unsubmitted) {
            Button(onClick = model.reviewEditor::submitReview, enabled = editable && !state.isLoading,
                modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.repayment_review_confirm)) }
            TextButton(onClick = { model.dismiss(input.draftPublicId) }, enabled = editable) {
                Text(stringResource(R.string.repayment_draft_dismiss))
            }
        }
    }
}

@Composable
private fun RepaymentReviewMoney(currency: String, amount: String, editable: Boolean, onChange: (String, String) -> Unit) {
    var choosingCurrency by rememberSaveable { mutableStateOf(false) }
    if (editable) {
        AppAmountInput(AppAmountInputState(stringResource(R.string.repayment_review_amount),
            CurrencyCode.fromStorageKey(currency), amount, "0"),
            AppAmountInputActions(onValueChange = { onChange(currency, it) },
                onCurrencyClick = { choosingCurrency = true }))
    } else {
        Text(stringResource(R.string.repayment_review_stored_amount), style = MaterialTheme.typography.labelMedium)
        AppAmountText("$currency $amount")
    }
    if (choosingCurrency) RepaymentReviewCurrencyDialog(onClose = { choosingCurrency = false }) { selected ->
        onChange(selected.storageKey, amount)
        choosingCurrency = false
    }
}

@Composable
private fun RepaymentReviewCurrencyDialog(onClose: () -> Unit, onPick: (CurrencyCode) -> Unit) {
    AlertDialog(onDismissRequest = onClose, title = { Text(stringResource(R.string.repayment_review_currency)) },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) { CurrencyCode.entries.forEach { currency ->
            TextButton(onClick = { onPick(currency) }) { Text("${currency.storageKey} ${currency.displayName}") }
        } } }, confirmButton = {})
}

@Composable
private fun RepaymentReviewReopenUnsubmitted(canModify: Boolean, onReopen: () -> Unit) {
    var confirmReopen by rememberSaveable { mutableStateOf(false) }
    Text(stringResource(R.string.debt_write_original_binding_changed))
    TextButton(onClick = { confirmReopen = true }, enabled = canModify) { Text(stringResource(R.string.repayment_review_again)) }
    if (confirmReopen) AlertDialog(onDismissRequest = { confirmReopen = false },
        title = { Text(stringResource(R.string.repayment_review_again)) },
        text = { Text(stringResource(R.string.repayment_review_reopen_unsubmitted)) },
        confirmButton = { TextButton(onClick = { confirmReopen = false; onReopen() }) {
            Text(stringResource(R.string.repayment_review_again))
        } }, dismissButton = { TextButton(onClick = { confirmReopen = false }) { Text(stringResource(R.string.common_cancel)) } })
}

@Composable
private fun RepaymentReviewDelivery(state: RepaymentDraftInboxUiState, model: RepaymentDraftInboxViewModel) {
    if (state.review.input?.submittedAction == null) return
    val row = state.review.original
    var confirmStop by rememberSaveable(row?.id) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(stringResource(R.string.repayment_review_original), style = MaterialTheme.typography.titleMedium)
        Text(stringResource(when (row?.status) {
            PendingMutationStatus.Done -> R.string.repayment_review_done
            PendingMutationStatus.Abandoned -> R.string.repayment_review_stopped
            null -> R.string.repayment_review_receipt_missing
            else -> R.string.repayment_review_waiting
        }))
        if (state.review.bindingChanged) Text(stringResource(R.string.debt_write_original_binding_changed))
        row?.lastError?.let { Text(repaymentReviewError(it), style = MaterialTheme.typography.bodySmall) }
        if (state.review.canRetry) TextButton(onClick = { model.reviewEditor.recoverReview(false) }, enabled = state.canModify) {
            Text(stringResource(R.string.repayment_review_retry))
        }
        if (state.review.canStop) TextButton(onClick = { confirmStop = true }) {
            Text(stringResource(R.string.debt_write_drop))
        }
        if (row?.status == PendingMutationStatus.Abandoned) TextButton(onClick = model.reviewEditor::reviewAgain, enabled = state.canModify) {
            Text(stringResource(R.string.repayment_review_again))
        }
    }
    if (confirmStop) AlertDialog(onDismissRequest = { confirmStop = false },
        title = { Text(stringResource(R.string.debt_write_drop)) }, text = { Text(stringResource(R.string.repayment_review_stopped)) },
        confirmButton = { TextButton(onClick = { confirmStop = false; model.reviewEditor.recoverReview(true) }) { Text(stringResource(R.string.debt_write_drop)) } },
        dismissButton = { TextButton(onClick = { confirmStop = false }) { Text(stringResource(R.string.common_cancel)) } })
}

@Composable
private fun repaymentReviewError(error: String): String = when (error) {
    "repayment_review_connection_interrupted" -> stringResource(R.string.repayment_review_interrupted)
    "repayment_review_binding_changed" -> stringResource(R.string.debt_write_original_binding_changed)
    "repayment_review_payload_unsupported", "repayment_review_response_unverified" -> stringResource(R.string.repayment_review_unverified)
    else -> if (error.startsWith("outbox_row_expired")) stringResource(R.string.debt_write_expired) else error
}
