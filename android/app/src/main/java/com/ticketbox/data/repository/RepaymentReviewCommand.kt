package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.RepaymentReviewInputEntity
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.parseExactMoneyMinor

internal fun RepaymentReviewInputEntity.command(binding: LogicalSessionBinding, draft: RepaymentDraft,
    dismiss: Boolean, adapters: OutboxAdapterGraph): PendingMutationIntent {
    if (dismiss) return PendingMutationIntent(PendingMutationType.DismissRepaymentDraft,
        "repayment-draft:$draftPublicId", adapters.repaymentDismissAdapter.toJson(RepaymentDismissPayload(1, draftPublicId, binding)),
        0, originalKey)
    val currencyCode = requireNotNull(CurrencyCode.fromStorageKeyOrNull(currency)) { "请选择支持的币种。" }
    val amount = requireNotNull(parseExactMoneyMinor(amountText, currencyCode)) { "请填写币种精度内的有效金额。" }
    require(amount > 0) { "还款金额必须大于零。" }
    val subject = DebtWriteSubject(requireNotNull(debtPublicId) { "请选择要偿还的欠款。" }, debtLabel, requireNotNull(debtHomeCurrency))
    val changedMoney = currency != draft.originalCurrencyCode || amount != draft.originalAmountMinor
    // Unchanged legacy/Expense-derived money keeps its already known home amount and frozen FX.
    val request = RepaymentDraftConfirmRequestDto(subject.publicId, requireNotNull(debtRowVersion),
        currency.takeIf { changedMoney }, amountText.trim().takeIf { changedMoney })
    val payload = RepaymentReviewPayload(1, draftPublicId, subject, binding.sessionGeneration, binding.bindingRevision,
        request, currency, amountText)
    return PendingMutationIntent(PendingMutationType.ConfirmRepaymentDraft, debtWriteTarget(subject.publicId),
        adapters.repaymentReviewAdapter.toJson(payload), request.expectedRowVersion, originalKey)
}
