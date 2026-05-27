package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class ReportTrendPointDto(
    val bucket: String,
    val label: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class ReportMerchantRankingDto(
    val merchant: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class ReportCategoryComparisonDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
    @param:Json(name = "previous_amount_cents")
    val previousAmountCents: Long,
    @param:Json(name = "previous_count")
    val previousCount: Int,
    @param:Json(name = "delta_amount_cents")
    val deltaAmountCents: Long,
    @param:Json(name = "delta_count")
    val deltaCount: Int,
)

data class ReportsOverviewDto(
    val month: String,
    val timezone: String,
    val granularity: String,
    @param:Json(name = "total_amount_cents")
    val totalAmountCents: Long,
    val count: Int,
    @param:Json(name = "previous_month")
    val previousMonth: String,
    @param:Json(name = "previous_total_amount_cents")
    val previousTotalAmountCents: Long,
    @param:Json(name = "previous_count")
    val previousCount: Int,
    @param:Json(name = "merchant_category")
    val merchantCategory: String?,
    @param:Json(name = "ranking_metric")
    val rankingMetric: String,
    val trend: List<ReportTrendPointDto>,
    @param:Json(name = "merchant_ranking")
    val merchantRanking: List<ReportMerchantRankingDto>,
    @param:Json(name = "category_comparison")
    val categoryComparison: List<ReportCategoryComparisonDto>,
)

data class GoalCreateRequestDto(
    val name: String,
    val month: String,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long,
    val category: String? = null,
    @param:Json(name = "goal_type")
    val goalType: String = "spending_limit",
    val period: String = "monthly",
)

/**
 * ADR-0038 PR-2j: PATCH /api/goals/{publicId} body. ``expectedUpdatedAt``
 * is the client's last-seen ``updated_at`` token; server returns 409 on
 * stale snapshot.
 */
data class GoalUpdateRequestDto(
    @param:Json(name = "expected_updated_at")
    val expectedUpdatedAt: String,
    val name: String? = null,
    val month: String? = null,
    val category: String? = null,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long? = null,
)

data class GoalDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val name: String,
    @param:Json(name = "goal_type")
    val goalType: String,
    val period: String,
    val month: String,
    val category: String?,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long,
    @param:Json(name = "spent_amount_cents")
    val spentAmountCents: Long,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long,
    @param:Json(name = "progress_percent")
    val progressPercent: Int,
    @param:Json(name = "progress_state")
    val progressState: String,
    val status: String,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "archived_at")
    val archivedAt: String?,
)

data class GoalListResponseDto(
    val items: List<GoalDto>,
)
