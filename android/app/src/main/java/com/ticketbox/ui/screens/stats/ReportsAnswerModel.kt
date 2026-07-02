package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportGranularity
import kotlin.math.abs

private const val DominantPeakPercent = 75
private const val SparseTrendBucketLimit = 3

internal enum class ReportsTrendMode {
    Empty,
    Sparse,
    DominantPeak,
    Chart,
}

internal data class ReportsTrendEvidence(
    val peak: ReportTrendChartPoint?,
    val totalAmountCents: Long,
    val positiveBucketCount: Int,
    val peakSharePercent: Int,
    val otherPositiveBucketCount: Int,
    val otherTotalAmountCents: Long,
    val otherAverageAmountCents: Long,
) {
    val mode: ReportsTrendMode = when {
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
    val totalAmountCents: Long,
    val count: Int,
    val previousMonth: String,
    val previousTotalAmountCents: Long,
    val monthDeltaAmountCents: Long,
    val monthDeltaPercent: Int?,
    val yearOverYearMonth: String,
    val yearOverYearDeltaAmountCents: Long,
    val trendPoints: List<ReportTrendChartPoint>,
    val trendEvidence: ReportsTrendEvidence,
)

internal fun reportsAnswerModel(overview: ReportsOverview): ReportsAnswerModel {
    val trendPoints = reportTrendChartPoints(overview.trend)
    val monthDelta = overview.totalAmountCents - overview.previousTotalAmountCents
    return ReportsAnswerModel(
        month = overview.month,
        granularity = overview.granularity,
        totalAmountCents = overview.totalAmountCents.coerceAtLeast(0L),
        count = overview.count.coerceAtLeast(0),
        previousMonth = overview.previousMonth,
        previousTotalAmountCents = overview.previousTotalAmountCents.coerceAtLeast(0L),
        monthDeltaAmountCents = monthDelta,
        monthDeltaPercent = percentChange(monthDelta, overview.previousTotalAmountCents),
        yearOverYearMonth = overview.yearOverYearMonth,
        yearOverYearDeltaAmountCents = overview.yearOverYearDeltaAmountCents,
        trendPoints = trendPoints,
        trendEvidence = reportsTrendEvidence(trendPoints),
    )
}

internal fun reportsTrendEvidence(points: List<ReportTrendChartPoint>): ReportsTrendEvidence {
    val normalized = points.map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
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
        peakSharePercent = if (total > 0L) (((peak?.amountCents ?: 0L) * 100L) / total).toInt() else 0,
        otherPositiveBucketCount = otherPositivePoints.size,
        otherTotalAmountCents = otherTotal,
        otherAverageAmountCents = if (otherPositivePoints.isNotEmpty()) otherTotal / otherPositivePoints.size else 0L,
    )
}

private fun percentChange(deltaAmountCents: Long, baselineAmountCents: Long): Int? {
    if (baselineAmountCents <= 0L) return null
    return ((abs(deltaAmountCents) * 100L) / baselineAmountCents).toInt()
}
