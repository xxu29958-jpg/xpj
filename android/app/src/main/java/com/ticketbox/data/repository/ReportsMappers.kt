package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DashboardCardUpdateRequestDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.DashboardCardDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.ReportCategoryComparisonDto
import com.ticketbox.data.remote.dto.ReportMerchantRankingDto
import com.ticketbox.data.remote.dto.ReportTrendPointDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.normalizeExpenseCategory

/** ADR-0049 §6 goal_type for debt_repayment goals (single source for the list query + create). */
internal const val DEBT_REPAYMENT_GOAL_TYPE = "debt_repayment"

fun ReportsOverviewDto.toDomain(): ReportsOverview = ReportsOverview(
    month = month,
    timezone = timezone,
    granularity = ReportGranularity.fromApiValue(granularity),
    totalAmountCents = totalAmountCents,
    count = count,
    previousMonth = previousMonth,
    previousTotalAmountCents = previousTotalAmountCents,
    previousCount = previousCount,
    merchantCategory = merchantCategory?.let(::normalizeExpenseCategory),
    rankingMetric = ReportRankingMetric.fromApiValue(rankingMetric),
    trend = trend.map { it.toDomain() },
    merchantRanking = merchantRanking.map { it.toDomain() },
    categoryComparison = categoryComparison.map { it.toDomain() },
)

private fun ReportTrendPointDto.toDomain(): ReportTrendPoint = ReportTrendPoint(
    bucket = bucket,
    label = label,
    amountCents = amountCents,
    count = count,
)

private fun ReportMerchantRankingDto.toDomain(): ReportMerchantRanking = ReportMerchantRanking(
    merchant = merchant,
    amountCents = amountCents,
    count = count,
)

private fun ReportCategoryComparisonDto.toDomain(): ReportCategoryComparison = ReportCategoryComparison(
    category = normalizeExpenseCategory(category),
    amountCents = amountCents,
    count = count,
    previousAmountCents = previousAmountCents,
    previousCount = previousCount,
    deltaAmountCents = deltaAmountCents,
    deltaCount = deltaCount,
)

fun GoalDto.toDomain(): Goal = Goal(
    publicId = publicId,
    ledgerId = ledgerId,
    name = name,
    goalType = goalType,
    period = period,
    // ADR-0049 §6 (slice 7): the spending-shape fields are null for a debt_repayment
    // goal — coalesce so the domain [Goal] stays non-null for the spending-goal UI
    // (which never receives a debt goal); the debt-goal UI reads [debtRepayment].
    month = month.orEmpty(),
    category = category?.let(::normalizeExpenseCategory),
    targetAmountCents = targetAmountCents ?: 0L,
    spentAmountCents = spentAmountCents ?: 0L,
    remainingAmountCents = remainingAmountCents ?: 0L,
    progressPercent = progressPercent ?: 0,
    progressState = GoalProgressState.fromApiValue(progressState),
    status = status,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
    archivedAt = archivedAt,
    debtRepayment = debtRepayment?.toDomain(),
)

fun GoalDraft.toRequest(): GoalCreateRequestDto = GoalCreateRequestDto(
    name = name.trim(),
    month = month.trim(),
    targetAmountCents = targetAmountCents,
    category = category.cleanCategoryOrNull(),
)

fun GoalUpdate.toRequest(): GoalUpdateRequestDto = GoalUpdateRequestDto(
    expectedRowVersion = expectedRowVersion,
    name = name?.trim()?.takeIf { it.isNotBlank() },
    month = month?.trim()?.takeIf { it.isNotBlank() },
    targetAmountCents = targetAmountCents,
    category = category.cleanCategoryOrNull(),
)

fun DashboardCardsResponseDto.toDomain(): DashboardCards = DashboardCards(
    surface = DashboardSurface.entries.firstOrNull { it.apiValue == surface } ?: DashboardSurface.Android,
    items = items.map { it.toDomain() },
)

private fun DashboardCardDto.toDomain(): DashboardCard = DashboardCard(
    key = key,
    title = title,
    visible = visible,
    position = position,
)

fun List<DashboardCardUpdate>.toRequest(): DashboardCardsUpdateRequestDto = DashboardCardsUpdateRequestDto(
    cards = map {
        DashboardCardUpdateRequestDto(
            key = it.key.trim(),
            visible = it.visible,
            position = it.position,
        )
    },
)

private fun String?.cleanCategoryOrNull(): String? =
    this?.trim()?.takeIf { it.isNotBlank() }?.let(::normalizeExpenseCategory)
