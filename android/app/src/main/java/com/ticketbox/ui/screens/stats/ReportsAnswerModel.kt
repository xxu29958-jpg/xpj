package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.moneyPercent
import java.time.LocalDate
import java.math.BigInteger

private const val DominantPeakPercent = 75
private const val SparseTrendBucketLimit = 3

internal enum class ReportsTrendMode {
    Empty,
    Sparse,
    DominantPeak,
    Chart,
    Signed,
}

internal data class ReportsTrendEvidence(
    val peak: ReportTrendChartPoint?,
    val totalAmountCents: Long,
    val positiveBucketCount: Int,
    val peakSharePercent: Int,
    val otherPositiveBucketCount: Int,
    val otherTotalAmountCents: Long,
    val otherAverageAmountCents: Long,
    val hasNegativeAmounts: Boolean = false,
) {
    val mode: ReportsTrendMode = when {
        hasNegativeAmounts -> ReportsTrendMode.Signed
        totalAmountCents <= 0L || positiveBucketCount == 0 -> ReportsTrendMode.Empty
        positiveBucketCount <= SparseTrendBucketLimit -> ReportsTrendMode.Sparse
        peakSharePercent >= DominantPeakPercent -> ReportsTrendMode.DominantPeak
        else -> ReportsTrendMode.Chart
    }

    val shouldUseDominanceBreakdown: Boolean = mode == ReportsTrendMode.DominantPeak
}

internal data class ReportsAnswerModel(
    val month: String,
    val granularity: ReportGranularity,
    val totalAmountCents: Long?,
    val count: Int,
    val previousMonth: String,
    val hasPreviousMonthComparison: Boolean,
    val previousTotalAmountCents: Long?,
    val monthDeltaAmountCents: Long?,
    val monthDeltaPercent: Long?,
    val yearOverYearMonth: String,
    val hasYearOverYearComparison: Boolean,
    val yearOverYearDeltaAmountCents: Long?,
    val trendPoints: List<ReportTrendChartPoint>,
    val trendEvidence: ReportsTrendEvidence?,
    val homeCurrencyCode: String,
)

internal fun reportsAnswerModel(overview: ReportsOverview): ReportsAnswerModel =
    reportsAnswerModel(overview, reportTrendChartPoints(elapsedReportTrend(overview)))

internal fun reportsAnswerModel(
    overview: ReportsOverview,
    today: LocalDate,
): ReportsAnswerModel = reportsAnswerModel(
    overview = overview,
    trendPoints = reportTrendChartPoints(elapsedReportTrend(overview, today)),
)

private fun reportsAnswerModel(
    overview: ReportsOverview,
    trendPoints: List<ReportTrendChartPoint>,
): ReportsAnswerModel {
    val current = overview.totalAmountCents
    val previous = overview.previousTotalAmountCents
    val monthDelta = if (current != null && previous != null) current - previous else null
    val hasPreviousMonthComparison = monthDelta != null && overview.previousCount > 0
    val hasYearOverYearComparison = overview.yearOverYearDeltaAmountCents != null && overview.yearOverYearCount > 0 && overview.yearOverYearTotalAmountCents != null
    return ReportsAnswerModel(
        month = overview.month,
        granularity = overview.granularity,
        totalAmountCents = overview.totalAmountCents,
        count = overview.count.coerceAtLeast(0),
        previousMonth = overview.previousMonth,
        hasPreviousMonthComparison = hasPreviousMonthComparison,
        previousTotalAmountCents = overview.previousTotalAmountCents,
        monthDeltaAmountCents = monthDelta,
        monthDeltaPercent = if (hasPreviousMonthComparison && current != null && current >= 0L && previous != null && previous > 0L) {
            percentChange(requireNotNull(monthDelta), requireNotNull(previous))
        } else {
            null
        },
        yearOverYearMonth = overview.yearOverYearMonth,
        hasYearOverYearComparison = hasYearOverYearComparison,
        yearOverYearDeltaAmountCents = overview.yearOverYearDeltaAmountCents,
        trendPoints = trendPoints,
        trendEvidence = if (overview.totalAmountCents == null || overview.trend.any { it.amountCents == null }) null else reportsTrendEvidence(trendPoints),
        homeCurrencyCode = overview.homeCurrencyCode,
    )
}

internal fun reportsTrendEvidence(points: List<ReportTrendChartPoint>): ReportsTrendEvidence {
    val normalized = points
    val total = normalized.sumOf { it.amountCents }
    val peakIndex = normalized.indices.maxByOrNull { normalized[it].amountCents }
    val peak = peakIndex?.let { normalized[it] }
    val otherPositivePoints = normalized.filterIndexed { index, point ->
        index != peakIndex && point.amountCents > 0L
    }
    val otherTotal = otherPositivePoints.sumOf { it.amountCents }
    return ReportsTrendEvidence(
        peak = peak,
        totalAmountCents = total,
        positiveBucketCount = normalized.count { it.amountCents > 0L },
        peakSharePercent = if (total > 0L && points.none { it.amountCents < 0L })
            BigInteger.valueOf(peak?.amountCents ?: 0L).multiply(BigInteger.valueOf(100L))
                .divide(BigInteger.valueOf(total)).toInt() else 0,
        otherPositiveBucketCount = otherPositivePoints.size,
        otherTotalAmountCents = otherTotal,
        otherAverageAmountCents = if (otherPositivePoints.isNotEmpty()) otherTotal / otherPositivePoints.size else 0L,
        hasNegativeAmounts = points.any { it.amountCents < 0L },
    )
}

private fun percentChange(deltaAmountCents: Long, baselineAmountCents: Long): Long? =
    moneyPercent(
        numeratorAmountMinor = deltaAmountCents,
        denominatorAmountMinor = baselineAmountCents,
        absoluteNumerator = true,
    )
