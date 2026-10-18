package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import com.ticketbox.data.remote.dto.PaymentCaptureDecisionDto
import com.ticketbox.data.remote.dto.PaymentCaptureDto
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.parseExactMoneyMinor
import com.ticketbox.ui.components.AppAmountInput
import com.ticketbox.ui.components.AppAmountInputActions
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.formatMinorAmount
import com.ticketbox.ui.design.AppSpacing
import java.util.UUID

@Composable
internal fun PaymentCaptureReviewCard(capture: PaymentCaptureDto, original: OutboxRow?, canModify: Boolean,
    onSubmit: (PaymentCaptureDecisionDto, String) -> Unit, onRecover: (OutboxRow, Boolean) -> Unit) {
    var kind by rememberSaveable(capture.publicId) { mutableStateOf("") }
    var amount by rememberSaveable(capture.publicId) { mutableStateOf("") }
    var reason by rememberSaveable(capture.publicId) { mutableStateOf("") }
    var key by rememberSaveable(capture.publicId) { mutableStateOf(UUID.randomUUID().toString()) }
    val currency = CurrencyCode.fromStorageKey(capture.originalCurrency)
    val editable = canModify && original == null
    AppPaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.payment_capture_review_title), style = MaterialTheme.typography.titleMedium)
            Text("${capture.merchant.orEmpty()} · ${capture.capturedAt.take(10)}", style = MaterialTheme.typography.bodySmall)
            Text(stringResource(R.string.payment_capture_review_body), style = MaterialTheme.typography.bodyMedium)
            capture.candidates.filter { it.amountMinor != null }.distinctBy { it.kind to it.amountMinor }.forEach { candidate ->
                TextButton(onClick = { amount = formatMinorAmount(requireNotNull(candidate.amountMinor), currency) }, enabled = editable) {
                    Text("${stringResource(paymentKindLabel(candidate.kind))} · ${formatMinorAmount(requireNotNull(candidate.amountMinor), currency)} ${currency.storageKey}")
                }
            }
            if (original == null) {
                listOf("expense", "repayment", "dismissed").forEach { option ->
                    TextButton(onClick = { kind = option }, enabled = editable) {
                        Text((if (kind == option) "✓ " else "") + stringResource(paymentKindLabel(option)))
                    }
                }
                if (kind != "dismissed") AppAmountInput(AppAmountInputState(stringResource(R.string.payment_capture_amount),
                    currency, amount, "0.00", enabled = editable), AppAmountInputActions({ amount = it }))
                AppTextInput(AppTextInputState(stringResource(R.string.payment_capture_reason), reason, enabled = editable),
                    AppTextInputActions({ reason = it }))
                val minor = parseExactMoneyMinor(amount, currency)
                AppPrimaryButton(stringResource(R.string.payment_capture_submit), onClick = {
                    onSubmit(PaymentCaptureDecisionDto(capture.rowVersion, kind, capture.originalCurrency,
                        minor.takeUnless { kind == "dismissed" }, capture.merchant, reason.trim()), key)
                }, enabled = editable && kind.isNotBlank() && reason.isNotBlank() && (kind == "dismissed" || (minor ?: 0) > 0))
            } else {
                Text(stringResource(if (original.status == PendingMutationStatus.Done) R.string.payment_capture_completed
                    else R.string.payment_capture_saved))
                if (original.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
                    Text(stringResource(R.string.payment_capture_failed), style = MaterialTheme.typography.bodySmall)
                    TextButton(onClick = { onRecover(original, false) }, enabled = canModify) { Text(stringResource(R.string.repayment_review_retry)) }
                    TextButton(onClick = { onRecover(original, true); key = UUID.randomUUID().toString() }, enabled = canModify) {
                        Text(stringResource(R.string.payment_capture_stop))
                    }
                }
            }
        }
    }
}

@Composable
internal fun PaymentCaptureReceiptCard(receipt: PaymentCaptureDto, onOpenExpense: (Long) -> Unit,
    onOpenRepayment: (String) -> Unit) {
    AppPaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.payment_capture_recent), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(when (receipt.kind) {
                "expense" -> R.string.payment_capture_expense_ready
                "repayment" -> R.string.payment_capture_repayment_ready
                else -> R.string.payment_capture_ignored
            }))
            receipt.expenseId?.let { id ->
                TextButton(onClick = { onOpenExpense(id) }) { Text(stringResource(R.string.payment_capture_open_expense)) }
            }
            if (receipt.kind == "repayment") receipt.repaymentPublicId?.let { id ->
                TextButton(onClick = { onOpenRepayment(id) }) { Text(stringResource(R.string.repayment_review_open)) }
            }
        }
    }
}

private fun paymentKindLabel(kind: String): Int = when (kind) {
    "expense" -> R.string.payment_capture_kind_expense
    "repayment" -> R.string.payment_capture_kind_repayment
    "dismissed" -> R.string.repayment_draft_dismiss
    "refund" -> R.string.payment_capture_refund
    else -> R.string.payment_capture_amount
}
