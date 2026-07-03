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

internal fun mergeTargetOptions(
    tags: List<ManagedTag>,
    source: ManagedTag,
    freshTarget: ManagedTag?,
): List<ManagedTag> = tags
    .filter { it.publicId != source.publicId }
    .map { tag ->
        if (freshTarget != null && tag.publicId == freshTarget.publicId) {
            freshTarget
        } else {
            tag
        }
    }
