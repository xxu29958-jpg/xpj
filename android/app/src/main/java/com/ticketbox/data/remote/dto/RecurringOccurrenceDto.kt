package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RecurringOccurrenceDto(
    @param:Json(name = "series_public_id") val seriesPublicId: String,
    val period: String,
    @param:Json(name = "series_row_version") val seriesRowVersion: Long,
    @param:Json(name = "row_version") val rowVersion: Long,
    val state: String,
    @param:Json(name = "planned_amount_cents") val plannedAmountCents: Long,
    @param:Json(name = "reserved_amount_cents") val reservedAmountCents: Long,
    @param:Json(name = "expense_public_id") val expensePublicId: String?,
    @param:Json(name = "paid_amount_cents") val paidAmountCents: Long?,
    @param:Json(name = "next_due_date") val nextDueDate: String?,
    @param:Json(name = "expense_id") val expenseId: Long? = null,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String? = null,
    @param:Json(name = "paid_home_currency_code") val paidHomeCurrencyCode: String? = null,
)

/** Explicit action is mandatory: a missing payment field must never mean "clear". */
@JsonClass(generateAdapter = true)
data class RecurringOccurrencePaymentRequestDto(
    val action: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "expected_series_row_version") val expectedSeriesRowVersion: Long,
    @param:Json(name = "expense_public_id") val expensePublicId: String? = null,
    @param:Json(name = "expected_expense_row_version") val expectedExpenseRowVersion: Long? = null,
)
