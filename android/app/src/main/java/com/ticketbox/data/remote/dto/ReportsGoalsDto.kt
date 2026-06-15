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

/**
 * POST /api/goals body. One DTO serves both goal types (the backend has a single
 * GoalCreateRequest schema with additionalProperties=false). spending_limit sends
 * [month] + [targetAmountCents]; ADR-0049 §6 debt_repayment sends [goalType] =
 * "debt_repayment" + [debtPublicIds] and leaves the spend-shape fields null —
 * Moshi omits nulls, so the wire body carries only the fields that goal type
 * needs (the backend 422s a debt goal that carries month/category/target, and a
 * spending goal that carries debt_public_ids). See [GoalDraft.toRequest] (spending)
 * and [debtGoalCreateRequest] (debt).
 */
data class GoalCreateRequestDto(
    val name: String,
    @param:Json(name = "goal_type")
    val goalType: String = "spending_limit",
    val period: String = "monthly",
    val month: String? = null,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long? = null,
    val category: String? = null,
    @param:Json(name = "debt_public_ids")
    val debtPublicIds: List<String>? = null,
)

/**
 * ADR-0041: PATCH /api/goals/{publicId} body. ``expectedRowVersion``
 * is the client's last-seen ``row_version`` token; server returns 409 on
 * stale snapshot.
 */
data class GoalUpdateRequestDto(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
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
    // ADR-0049 §6 (slice 7): the spending-shape numeric fields are null for a
    // debt_repayment goal (it has no monthly spend target). The month-scoped
    // GET /api/goals never returns debt goals, so a spending-only response keeps
    // these populated; only the debt-goal surface (GET ?goal_type=debt_repayment /
    // GET /api/goals/{id} for a debt goal) sends nulls + the [debtRepayment] block.
    val month: String?,
    val category: String?,
    @param:Json(name = "target_amount_cents")
    val targetAmountCents: Long?,
    @param:Json(name = "spent_amount_cents")
    val spentAmountCents: Long?,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long?,
    @param:Json(name = "progress_percent")
    val progressPercent: Int?,
    @param:Json(name = "progress_state")
    val progressState: String,
    val status: String,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "archived_at")
    val archivedAt: String?,
    // Populated only for debt_repayment goals (ADR-0049 §6).
    @param:Json(name = "debt_repayment")
    val debtRepayment: DebtRepaymentEvaluationDto? = null,
)

data class GoalListResponseDto(
    val items: List<GoalDto>,
)
