package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DashboardCardUpdateRequestDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.DashboardCardDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.ReportCategoryComparisonDto
import com.ticketbox.data.remote.dto.ReportMerchantRankingDto
import com.ticketbox.data.remote.dto.ReportTrendPointDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.normalizeExpenseCategory

fun ReportsOverviewDto.toDomain(): ReportsOverview = ReportsOverview(
    month = month,
    timezone = timezone,
    granularity = ReportGranularity.fromApiValue(granularity),
    totalAmountCents = totalAmountCents,
    count = count,
    previousMonth = previousMonth,
    previousTotalAmountCents = previousTotalAmountCents,
    previousCount = previousCount,
    yearOverYearMonth = yearOverYearMonth,
    yearOverYearTotalAmountCents = yearOverYearTotalAmountCents,
    yearOverYearCount = yearOverYearCount,
    yearOverYearDeltaAmountCents = yearOverYearDeltaAmountCents,
    yearOverYearDeltaCount = yearOverYearDeltaCount,
    merchantCategory = merchantCategory?.let(::normalizeExpenseCategory),
    rankingMetric = ReportRankingMetric.fromApiValue(rankingMetric),
    trend = trend.map { it.toDomain() },
    merchantRanking = merchantRanking.map { it.toDomain() },
    categoryComparison = categoryComparison.map { it.toDomain() },
    homeCurrencyCode = homeCurrencyCode,
    missingRates = missingRates.map { com.ticketbox.domain.model.CurrencyProjectionGap(it.sourceCurrencyCode, it.homeCurrencyCode, it.rateDate) },
    undatedExpenseCount = undatedExpenseCount,
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
    yearOverYearAmountCents = yearOverYearAmountCents,
    yearOverYearCount = yearOverYearCount,
    yearOverYearDeltaAmountCents = yearOverYearDeltaAmountCents,
    yearOverYearDeltaCount = yearOverYearDeltaCount,
    undatedExpenseCount = undatedExpenseCount,
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
