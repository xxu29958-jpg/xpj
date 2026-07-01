package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.DashboardCard

internal data class DashboardCardsSummary(
    val totalCount: Int,
    val visibleCount: Int,
    val hiddenCount: Int,
    val firstVisibleTitle: String?,
)

internal fun dashboardCardsSummary(cards: List<DashboardCard>): DashboardCardsSummary {
    val visible = cards.filter { it.visible }
    return DashboardCardsSummary(
        totalCount = cards.size,
        visibleCount = visible.size,
        hiddenCount = cards.size - visible.size,
        firstVisibleTitle = visible.firstOrNull()?.title,
    )
}
