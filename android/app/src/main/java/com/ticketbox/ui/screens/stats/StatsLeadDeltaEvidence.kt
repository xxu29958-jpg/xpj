package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportsOverview

internal data class MonthDeltaEvidence(
    val previousAmountCents: Long,
    val deltaAmountCents: Long,
)

internal fun monthDeltaEvidence(
    overview: ReportsOverview?,
): MonthDeltaEvidence? {
    val previousAmount = overview?.previousTotalAmountCents ?: return null
    val currentAmount = overview.totalAmountCents ?: return null
    if (overview.previousCount <= 0 || previousAmount <= 0L) return null
    val delta = currentAmount - previousAmount
    return MonthDeltaEvidence(
        previousAmountCents = previousAmount,
        deltaAmountCents = delta,
    )
}
