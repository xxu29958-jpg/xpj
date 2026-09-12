package com.ticketbox.ui.navigation

import android.net.Uri
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.repository.LogicalSessionBinding

/** Navigation identity only. The original expense and occurrence owners still authorize every command. */
@JsonClass(generateAdapter = true)
internal data class RecurringPaymentOrigin(
    val binding: LogicalSessionBinding,
    val seriesPublicId: String,
    val period: String,
    val clientRef: String? = null,
)

private val recurringPaymentOriginAdapter = Moshi.Builder().build().adapter(RecurringPaymentOrigin::class.java)
internal const val RECURRING_PAYMENT_ROUTE = "recurring-payment?origin={origin}"

internal data class RecurringNavigation(val onOpenExpense: (Long) -> Unit, val onRecordPayment: (RecurringPaymentOrigin) -> Unit)

internal fun recurringPaymentOriginJson(origin: RecurringPaymentOrigin): String = recurringPaymentOriginAdapter.toJson(origin)
internal fun readRecurringPaymentOrigin(json: String?): RecurringPaymentOrigin? =
    json?.let { runCatching { recurringPaymentOriginAdapter.fromJson(it) }.getOrNull() }

internal fun recurringPaymentRoute(origin: RecurringPaymentOrigin): String =
    "recurring-payment?origin=${Uri.encode(recurringPaymentOriginJson(origin))}"
