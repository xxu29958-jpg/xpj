package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.ticketbox.domain.model.GoalDefinition
import com.ticketbox.domain.model.GoalHistoryPage
import com.ticketbox.domain.model.GoalRevision

data class GoalHistoryResponseDto(
    @Json(name = "ledger_id") val ledgerId: String,
    @Json(name = "public_id") val publicId: String,
    val items: List<GoalRevisionDto>,
    @Json(name = "next_before_version") val nextBeforeVersion: Long?,
) {
    fun toDomain() = GoalHistoryPage(items.map { GoalRevision(it.rowVersion, it.changeKind, it.recordedAt,
        it.snapshot.toDomain()) }, nextBeforeVersion)
}

data class GoalRevisionDto(
    @Json(name = "row_version") val rowVersion: Long,
    @Json(name = "change_kind") val changeKind: String,
    @Json(name = "recorded_at") val recordedAt: String,
    val snapshot: GoalDefinitionDto,
)

data class GoalDefinitionDto(
    val name: String,
    @Json(name = "goal_type") val goalType: String,
    val period: String,
    val month: String?,
    val category: String?,
    @Json(name = "target_amount_cents") val targetAmountCents: Long?,
    @Json(name = "home_currency_code") val homeCurrencyCode: String?,
    val status: String,
) {
    fun toDomain() = GoalDefinition(name, goalType, period, month, category, targetAmountCents, homeCurrencyCode, status)
}
