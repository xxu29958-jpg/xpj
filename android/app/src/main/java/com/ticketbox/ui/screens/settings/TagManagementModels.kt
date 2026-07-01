package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.ManagedTag

internal data class TagManagementSummaryModel(
    val totalCount: Int,
    val activeCount: Int,
    val unusedCount: Int,
    val usageCount: Int,
)

internal fun tagManagementSummaryModel(tags: List<ManagedTag>): TagManagementSummaryModel {
    val total = tags.size.coerceAtLeast(0)
    val unused = tags.count { it.usageCount <= 0 }
    return TagManagementSummaryModel(
        totalCount = total,
        activeCount = total - unused,
        unusedCount = unused,
        usageCount = tags.sumOf { it.usageCount.coerceAtLeast(0) },
    )
}
