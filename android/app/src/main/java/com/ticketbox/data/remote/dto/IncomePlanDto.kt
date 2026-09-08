package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/**
 * v1.1 monthly income plan DTOs. Mirrors backend
 * `backend/app/schemas/_income_plan.py`. Adding a field requires an
 * ADR-0036 review (income plan rows are stored locally but the
 * `source_type` value is one of the few fields that DOES go out to the
 * AI advisor — see allowed-fields list in ADR-0036).
 */
data class IncomePlanDto(
    @param:Json(name = "public_id") val publicId: String,
    val label: String,
    @param:Json(name = "source_type") val sourceType: String,
    val frequency: String,
    @param:Json(name = "income_month") val incomeMonth: String?,
    @param:Json(name = "amount_cents") val amountCents: Long,
    @param:Json(name = "pay_day") val payDay: Int,
    val status: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "updated_at") val updatedAt: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "archived_at") val archivedAt: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String? = null,
)

data class IncomePlanListResponseDto(
    val items: List<IncomePlanDto>,
    @param:Json(name = "total_active_amount_cents") val totalActiveAmountCents: Long?,
    val month: String,
    @param:Json(name = "scheduled_amount_cents") val scheduledAmountCents: Long?,
    @param:Json(name = "effective_plan_count") val effectivePlanCount: Int,
    @param:Json(name = "expected_amount_cents") val expectedAmountCents: Long?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String? = null,
    @param:Json(name = "missing_currency_codes") val missingCurrencyCodes: List<String> = emptyList(),
)

data class IncomePlanCreateRequestDto(
    @param:Json(name = "intent_month") val intentMonth: String,
    val label: String,
    @param:Json(name = "source_type") val sourceType: String,
    val frequency: String = "monthly",
    @param:Json(name = "income_month") val incomeMonth: String? = null,
    @param:Json(name = "amount_cents") val amountCents: Long,
    @param:Json(name = "pay_day") val payDay: Int,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
)

/**
 * ADR-0041: PATCH /api/income-plans/{publicId} body. ``expectedRowVersion``
 * is the client's last-seen ``row_version`` token; server returns 409
 * on stale snapshot.
 */
@JsonClass(generateAdapter = true)
data class IncomePlanUpdateRequestDto(
    @param:Json(name = "intent_month") val intentMonth: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val label: String? = null,
    @param:Json(name = "source_type") val sourceType: String? = null,
    val frequency: String? = null,
    @param:Json(name = "income_month") val incomeMonth: String? = null,
    @param:Json(name = "amount_cents") val amountCents: Long? = null,
    @param:Json(name = "pay_day") val payDay: Int? = null,
)

/** Archive/restore retain the displayed month and the current OCC token. */
data class IncomePlanTokenRequestDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "intent_month") val intentMonth: String,
)
