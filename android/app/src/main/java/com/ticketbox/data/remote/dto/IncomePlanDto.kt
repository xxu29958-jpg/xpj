package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

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
    @param:Json(name = "amount_cents") val amountCents: Long,
    @param:Json(name = "pay_day") val payDay: Int,
    val status: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "updated_at") val updatedAt: String,
    @param:Json(name = "archived_at") val archivedAt: String?,
)

data class IncomePlanListResponseDto(
    val items: List<IncomePlanDto>,
    @param:Json(name = "total_active_amount_cents") val totalActiveAmountCents: Long,
)

data class IncomePlanCreateRequestDto(
    val label: String,
    @param:Json(name = "source_type") val sourceType: String,
    @param:Json(name = "amount_cents") val amountCents: Long,
    @param:Json(name = "pay_day") val payDay: Int,
)

/**
 * ADR-0038 PR-2j: PATCH /api/income-plans/{publicId} body. ``expectedUpdatedAt``
 * is the client's last-seen ``updated_at`` token; server returns 409
 * on stale snapshot.
 */
data class IncomePlanUpdateRequestDto(
    @param:Json(name = "expected_updated_at") val expectedUpdatedAt: String,
    val label: String? = null,
    @param:Json(name = "source_type") val sourceType: String? = null,
    @param:Json(name = "amount_cents") val amountCents: Long? = null,
    @param:Json(name = "pay_day") val payDay: Int? = null,
)
