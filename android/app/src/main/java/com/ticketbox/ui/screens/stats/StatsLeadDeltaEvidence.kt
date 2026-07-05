package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportsOverview

internal data class MonthDeltaEvidence(
    val previousAmountCents: Long,
    val deltaAmountCents: Long,
)

internal fun monthDeltaEvidence(
    overview: ReportsOverview?,
): MonthDeltaEvidence? {
    if (!hasPreviousBaseline(overview)) return null
    val previousAmount = overview?.previousTotalAmountCents ?: return null
    val delta = overview.totalAmountCents - overview.previousTotalAmountCents
    return MonthDeltaEvidence(
        previousAmountCents = previousAmount,
        deltaAmountCents = delta,
    )
}

private fun hasPreviousBaseline(overview: ReportsOverview?): Boolean =
    overview?.let { it.previousCount > 0 && it.previousTotalAmountCents > 0L } == true
