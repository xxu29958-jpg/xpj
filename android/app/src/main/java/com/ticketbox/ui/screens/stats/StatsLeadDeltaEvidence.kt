package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.ReportsOverview

internal data class MonthDeltaEvidence(
    val previousAmountCents: Long,
    val deltaAmountCents: Long,
    val percentChange: Int?,
)

internal fun monthDeltaEvidence(
    overview: ReportsOverview?,
    comparison: MonthComparison?,
): MonthDeltaEvidence? {
    if (!hasPreviousBaseline(overview, comparison)) return null
    val previousAmount = overview?.previousTotalAmountCents ?: comparison?.previousAmountCents ?: return null
    val delta = overview?.let { it.totalAmountCents - it.previousTotalAmountCents }
        ?: comparison?.deltaAmountCents
        ?: return null
    return MonthDeltaEvidence(
        previousAmountCents = previousAmount,
        deltaAmountCents = delta,
        percentChange = comparison?.percentChange,
    )
}

private fun hasPreviousBaseline(
    overview: ReportsOverview?,
    comparison: MonthComparison?,
): Boolean = overview?.let { it.previousCount > 0 }
    ?: ((comparison?.previousAmountCents ?: 0L) > 0L)
