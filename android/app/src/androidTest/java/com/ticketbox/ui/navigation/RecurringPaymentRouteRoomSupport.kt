package com.ticketbox.ui.navigation

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.repository.ExpenseManualCreation
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.decodeManualCreateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.runBlocking

internal fun enqueueRawPeriodPayment(
    creation: ExpenseManualCreation,
    task: RecurringPaymentTask,
    ref: String,
    merchant: String,
    currency: CurrencyCode,
    originalAmountMinor: Long,
    expenseTime: String,
    origin: RecurringPaymentOrigin? = null,
) {
    runBlocking {
        creation.create(
            ExpenseDraft(
                amountCents = originalAmountMinor,
                originalCurrencyCode = currency,
                originalAmountMinor = originalAmountMinor,
                ledgerHomeCurrency = CurrencyCode.CNY,
                merchant = merchant,
                category = "餐饮",
                note = null,
                expenseTime = expenseTime,
                tags = null,
                valueScore = null,
                regretScore = null,
            ),
            task.binding,
            ref,
            origin,
        ).getOrThrow()
    }
}

internal fun periodPaymentTask(
    binding: LogicalSessionBinding,
    recorded: String?,
    amount: Long?,
) = RecurringPaymentTask(
    binding = binding,
    seriesPublicId = "rec-1",
    period = "2026-08",
    clientRef = "period-ref",
    merchant = "房租",
    recordedCurrencyCode = recorded,
    suggestedAmountMinor = amount,
    ledgerHomeCurrencyCode = "CNY",
)

internal fun readPeriodCreateRequest(payload: String) = requireNotNull(
    decodeManualCreateRequest(
        OutboxAdapterGraph().manualCreateAdapter,
        OutboxAdapterGraph().recurringPaymentCreateAdapter,
        payload,
    ),
)
