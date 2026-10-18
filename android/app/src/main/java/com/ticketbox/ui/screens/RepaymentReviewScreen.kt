package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import com.ticketbox.ui.components.AppPrimaryButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.RepaymentDraftInboxUiState
import com.ticketbox.viewmodel.RepaymentDraftInboxViewModel

@Composable
internal fun RepaymentReviewScreen(state: RepaymentDraftInboxUiState, model: RepaymentDraftInboxViewModel,
    onOpenDebt: (String) -> Unit, onOpenExpense: (Long) -> Unit) {
    BackHandler { model.reviewEditor.closeReview() }
    var choosingDebt by rememberSaveable { mutableStateOf(false) }
    AppSecondaryScrollableContent(chrome = AppSecondaryPageChrome(role = AppPageRole.Stats,
        title = stringResource(R.string.repayment_review_title),
        subtitle = stringResource(R.string.repayment_review_saved),
        backText = stringResource(R.string.repayment_draft_topbar_back), onBack = model.reviewEditor::closeReview,
        hasBottomBar = false, verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)),
        refresh = AppSecondaryRefreshState(state.isLoading, model::refresh),
        slots = AppSecondaryPageSlots(bottomBar = { RepaymentReviewActions(state, model) })) {
        item {
            state.drafts.find { it.publicId == state.reviewId }?.let { capture -> RepaymentReviewSource(capture) }
        }
        state.error?.let { item { AppStatusBanner(it, tone = MessageTone.Danger) } }
        item { RepaymentReviewInputs(state, model) { choosingDebt = true } }
        item { RepaymentReviewDelivery(state, model) }
        state.drafts.find { it.publicId == state.reviewId && !it.isPending }?.let { capture ->
            item {
                if (state.review.input != null && state.review.input.submittedAction == null) {
                    Text(stringResource(R.string.repayment_review_unsubmitted_history), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (capture.correctionVersions != null && capture.correctedExpenseId == null) {
                    RepaymentAsExpenseAction(state.canModify && !state.isLoading && !state.review.bindingChanged,
                        model::correctAsExpense, confirmed = true)
                }
                if (capture.correctedExpenseId != null) {
                    Text(stringResource(R.string.payment_capture_corrected))
                    TextButton(onClick = { onOpenExpense(capture.correctedExpenseId) }) {
                        Text(stringResource(R.string.payment_capture_open_expense))
                    }
                } else RepaymentDraftResolved(capture) { capture.committedDebtPublicId?.let(onOpenDebt) }
            }
        }
    }
    if (choosingDebt) RepaymentDraftTargetSheet(state, state.reviewId,
        onPick = { _, debt -> model.reviewEditor.selectReviewDebt(debt); choosingDebt = false },
        onClose = { choosingDebt = false })
}

/** The capture as it arrived. It is evidence: shown on its own card and never edited on this page. */
@Composable
private fun RepaymentReviewSource(capture: RepaymentDraft) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    AppPaperCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(stringResource(R.string.repayment_draft_original_money), style = MaterialTheme.typography.labelMedium, color = muted)
            Text("${capture.originalCurrencyCode} ${com.ticketbox.ui.components.formatMinorAmount(capture.originalAmountMinor,
                CurrencyCode.fromStorageKey(capture.originalCurrencyCode))}",
                style = MaterialTheme.typography.titleMedium.tabularNum(), fontWeight = FontWeight.SemiBold)
            capture.merchantLabel?.takeIf { it.isNotBlank() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = muted)
            }
            Text(stringResource(R.string.repayment_draft_captured_at, capture.capturedAt.take(10)),
                style = MaterialTheme.typography.bodySmall, color = muted)
            if (capture.isPending && capture.sourceExpensePublicId != null) {
                Text(stringResource(if (capture.sourceExpenseRequiresReview) R.string.repayment_review_source_recheck
                    else R.string.repayment_review_source_reversal), style = MaterialTheme.typography.bodySmall, color = muted)
            }
        }
    }
}

@Composable
private fun RepaymentReviewInputs(state: RepaymentDraftInboxUiState, model: RepaymentDraftInboxViewModel, chooseDebt: () -> Unit) {
    val input = state.review.input ?: return
    val pending = state.drafts.any { it.publicId == input.draftPublicId && it.isPending }
    val unsubmitted = pending && input.submittedAction == null
    val editable = unsubmitted && !state.review.bindingChanged && state.canModify && state.pendingActionDraftId == null
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        if (unsubmitted) RepaymentAsExpenseAction(editable, model::correctAsExpense)
        RepaymentReviewMoney(input.currency, input.amountText, editable, model.reviewEditor::updateReviewMoney)
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            if (editable) {
                DebtDateField(input.paymentDate.orEmpty(), true, onChange = model.reviewEditor::updateReviewDate)
                Text(stringResource(R.string.repayment_review_date_hint), style = MaterialTheme.typography.bodySmall, color = muted)
            } else {
                Text(stringResource(R.string.debt_payment_date_label), style = MaterialTheme.typography.labelMedium, color = muted)
                Text(input.paymentDate?.takeIf { it.isNotEmpty() } ?: stringResource(R.string.repayment_review_original_time),
                    style = MaterialTheme.typography.titleMedium)
            }
        }
        RepaymentReviewTarget(input.debtLabel, editable, chooseDebt)
        Text(stringResource(R.string.repayment_review_money_note), style = MaterialTheme.typography.bodySmall, color = muted)
        if (unsubmitted && state.review.bindingChanged) {
            RepaymentReviewReopenUnsubmitted(state.canModify, model.reviewEditor::reviewAgain)
        }
        // 忽略是这页的低频出口：放在表单末尾居中，不夹在输入之间。
        if (unsubmitted) Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            TextButton(onClick = { model.dismiss(input.draftPublicId) }, enabled = editable) {
                Text(stringResource(R.string.repayment_draft_dismiss))
            }
        }
    }
}

@Composable
private fun RepaymentAsExpenseAction(enabled: Boolean, onSubmit: (String) -> Unit, confirmed: Boolean = false) {
    var open by rememberSaveable { mutableStateOf(false) }
    var reason by rememberSaveable { mutableStateOf("") }
    TextButton(onClick = { open = true }, enabled = enabled) { Text(stringResource(R.string.payment_capture_as_expense)) }
    if (open) AlertDialog(onDismissRequest = { open = false },
        title = { Text(stringResource(R.string.payment_capture_as_expense)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                Text(stringResource(if (confirmed) R.string.payment_capture_confirmed_correction_explanation else R.string.payment_capture_correction_explanation))
                com.ticketbox.ui.components.AppTextInput(com.ticketbox.ui.components.AppTextInputState(
                    stringResource(R.string.payment_capture_reason), reason),
                    com.ticketbox.ui.components.AppTextInputActions({ reason = it }))
            }
        }, confirmButton = { TextButton(onClick = { onSubmit(reason); open = false }, enabled = reason.isNotBlank()) {
            Text(stringResource(R.string.payment_capture_create_expense))
        } }, dismissButton = { TextButton(onClick = { open = false }) { Text(stringResource(android.R.string.cancel)) } })
}

/** Which debt this repayment goes to: the choice and the way to change it sit on one line. */
@Composable
private fun RepaymentReviewTarget(label: String?, editable: Boolean, chooseDebt: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(stringResource(R.string.repayment_review_target_label), style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        AppAdaptiveContentActionRow(
            style = AppAdaptiveContentActionStyle(compactAction = true),
            content = {
                Text(label ?: stringResource(R.string.repayment_review_no_target), style = MaterialTheme.typography.titleMedium,
                    color = if (label == null) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface)
            },
            action = { actionModifier ->
                if (editable) TextButton(onClick = chooseDebt, modifier = actionModifier) {
                    Text(stringResource(R.string.repayment_review_select))
                }
            },
        )
    }
}

@Composable
private fun RepaymentReviewActions(state: RepaymentDraftInboxUiState, model: RepaymentDraftInboxViewModel) {
    val input = state.review.input
    val unsubmitted = input != null && input.submittedAction == null && state.drafts.any { it.publicId == input.draftPublicId && it.isPending }
    AppFloatingActionBar {
        if (unsubmitted) AppPrimaryButton(text = stringResource(R.string.repayment_review_confirm),
            onClick = model.reviewEditor::submitReview, modifier = Modifier.fillMaxWidth(),
            enabled = state.canModify && !state.isLoading && !state.review.bindingChanged && state.pendingActionDraftId == null
                && state.drafts.none { it.publicId == input?.draftPublicId && it.sourceExpenseRequiresReview })
        else if (state.review.canRetry) AppPrimaryButton(text = stringResource(R.string.repayment_review_retry),
            onClick = { model.reviewEditor.recoverReview(false) }, enabled = state.canModify, modifier = Modifier.fillMaxWidth())
        if (unsubmitted || state.review.canRetry) TextButton(onClick = model.reviewEditor::closeReview, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.debt_proposal_back_keep_draft))
        } else AppPrimaryButton(text = stringResource(R.string.repayment_draft_topbar_back),
            onClick = model.reviewEditor::closeReview, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun RepaymentReviewMoney(currency: String, amount: String, editable: Boolean, onChange: (String, String) -> Unit) {
    var choosingCurrency by rememberSaveable { mutableStateOf(false) }
    if (editable) {
        AppAmountInput(AppAmountInputState(stringResource(R.string.repayment_review_amount),
            CurrencyCode.fromStorageKey(currency), amount, "0"),
            AppAmountInputActions(onValueChange = { onChange(currency, it) },
                onCurrencyClick = { choosingCurrency = true }),
            decorations = AppTextInputDecorations(amountRole = AppAmountRole.Hero))
    } else {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(stringResource(R.string.repayment_review_stored_amount), style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            AppAmountText("$currency $amount", role = AppAmountRole.Hero)
        }
    }
    if (choosingCurrency) RepaymentReviewCurrencyDialog(onClose = { choosingCurrency = false }) { selected ->
        onChange(selected.storageKey, amount)
        choosingCurrency = false
    }
}

@Composable
private fun RepaymentReviewCurrencyDialog(onClose: () -> Unit, onPick: (CurrencyCode) -> Unit) {
    com.ticketbox.ui.components.CurrencyPickerDialog(onChoose = onPick, onDismiss = onClose)
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
    AppPaperCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(stringResource(R.string.repayment_review_original), style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold)
            Text(stringResource(when (row?.status) {
                PendingMutationStatus.Done -> if (row.type == com.ticketbox.data.local.PendingMutationType.ResolvePaymentCapture)
                    R.string.payment_capture_corrected else R.string.repayment_review_done
                PendingMutationStatus.Abandoned -> R.string.repayment_review_stopped
                null -> R.string.repayment_review_receipt_missing
                else -> R.string.repayment_review_waiting
            }), style = MaterialTheme.typography.bodyMedium)
            if (state.review.bindingChanged) Text(stringResource(R.string.debt_write_original_binding_changed),
                style = MaterialTheme.typography.bodyMedium)
            row?.lastError?.let {
                Text(repaymentReviewError(it), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (state.review.canStop) TextButton(onClick = { confirmStop = true }) {
                Text(stringResource(R.string.debt_write_drop))
            }
            if (row?.status == PendingMutationStatus.Abandoned) TextButton(onClick = model.reviewEditor::reviewAgain, enabled = state.canModify) {
                Text(stringResource(R.string.repayment_review_again))
            }
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
    "repayment_source_refresh_pending" -> stringResource(R.string.repayment_review_source_refresh)
    "repayment_review_binding_changed" -> stringResource(R.string.debt_write_original_binding_changed)
    "repayment_review_payload_unsupported", "repayment_review_response_unverified" -> stringResource(R.string.repayment_review_unverified)
    else -> if (error.startsWith("outbox_row_expired")) stringResource(R.string.debt_write_expired) else error
}
