package com.ticketbox.ui.navigation

import android.net.Uri
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import java.util.UUID

/** Navigation identity only. CreateExpense / Confirm / link stay on their current owners. */
@JsonClass(generateAdapter = true)
internal data class RecurringPaymentTask(
    val binding: LogicalSessionBinding,
    val seriesPublicId: String,
    val period: String,
    val clientRef: String,
    val merchant: String,
    val recordedCurrencyCode: String?,
    val suggestedAmountMinor: Long?,
    val ledgerHomeCurrencyCode: String,
) {
    init {
        if (recordedCurrencyCode == null) require(suggestedAmountMinor == null)
    }
}

private val recurringPaymentTaskAdapter = Moshi.Builder().build().adapter(RecurringPaymentTask::class.java)
internal const val RECURRING_PAYMENT_ROUTE = "recurring-payment?task={task}"

internal data class RecurringExpenseNavigation(
    val onOpenExpense: (Long) -> Unit,
    val onRecordPayment: (RecurringPaymentTask) -> Unit = {},
)

internal fun recurringPaymentTaskJson(task: RecurringPaymentTask): String = recurringPaymentTaskAdapter.toJson(task)

internal fun readRecurringPaymentTask(json: String?): RecurringPaymentTask? =
    json?.let { runCatching { recurringPaymentTaskAdapter.fromJson(it) }.getOrNull() }

internal fun recurringPaymentRoute(task: RecurringPaymentTask): String =
    "recurring-payment?task=${Uri.encode(recurringPaymentTaskJson(task))}"

internal fun recurringPaymentTask(
    state: RecurringOccurrenceUiState,
    existing: RecurringPaymentTask? = null,
): RecurringPaymentTask? {
    val binding = state.access?.binding ?: return null
    val item = state.item ?: return null
    val occurrence = state.occurrence ?: return null
    val home = CurrencyCode.fromStorageKeyOrNull(state.ledgerHomeCurrencyCode)?.storageKey ?: return null
    if (!state.canWrite || occurrence.state != "unfulfilled") return null
    val recorded = CurrencyCode.fromStorageKeyOrNull(occurrence.homeCurrencyCode)?.storageKey
    if (existing?.binding == binding && existing.seriesPublicId == item.publicId && existing.period == occurrence.period) {
        return existing
    }
    return RecurringPaymentTask(
        binding = binding,
        seriesPublicId = item.publicId,
        period = occurrence.period,
        clientRef = UUID.randomUUID().toString(),
        merchant = item.merchant,
        recordedCurrencyCode = recorded,
        suggestedAmountMinor = if (recorded == null) null else occurrence.plannedAmountCents,
        ledgerHomeCurrencyCode = home,
    )
}
