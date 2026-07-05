package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.ManagedTag
import kotlin.test.Test
import kotlin.test.assertEquals

class TagManagementScreenModelTest {
    @Test
    fun summarySeparatesActiveAndUnusedTags() {
        val summary = tagManagementSummaryModel(
            listOf(
                tag("a", usage = 4),
                tag("b", usage = 0),
                tag("c", usage = 2),
            ),
        )

        assertEquals(
            TagManagementSummaryModel(
                totalCount = 3,
                activeCount = 2,
                unusedCount = 1,
                usageCount = 6,
            ),
            summary,
        )
    }

    @Test
    fun summaryDoesNotLetNegativeUsagePolluteCounts() {
        val summary = tagManagementSummaryModel(listOf(tag("a", usage = -3)))

        assertEquals(1, summary.totalCount)
        assertEquals(0, summary.activeCount)
        assertEquals(1, summary.unusedCount)
        assertEquals(0, summary.usageCount)
    }

    @Test
    fun bodyStateSeparatesLoadTruthFromEmptyAndKeepsVisibleRows() {
        assertEquals(
            TagManagementBodyState.Loading,
            tagManagementBodyState(hasTags = false, loading = true, loadFailed = false),
        )
        assertEquals(
            TagManagementBodyState.LoadFailed,
            tagManagementBodyState(hasTags = false, loading = false, loadFailed = true),
        )
        assertEquals(
            TagManagementBodyState.Empty,
            tagManagementBodyState(hasTags = false, loading = false, loadFailed = false),
        )
        assertEquals(
            TagManagementBodyState.Content,
            tagManagementBodyState(hasTags = true, loading = true, loadFailed = true),
        )
    }

    @Test
    fun mergeTargetsUseFreshConflictTokenForSuggestedTarget() {
        val source = tag("source", usage = 1)
        val staleTarget = tag("target", usage = 2, rowVersion = 1L)
        val freshTarget = tag("target", usage = 3, rowVersion = 9L)
        val other = tag("other", usage = 4)

        val targets = mergeTargetOptions(
            tags = listOf(source, staleTarget, other),
            source = source,
            freshTarget = freshTarget,
        )

        assertEquals(listOf(freshTarget, other), targets)
    }

    private fun tag(
        id: String,
        usage: Int,
        rowVersion: Long = 1L,
    ): ManagedTag = ManagedTag(publicId = id, name = id, usageCount = usage, rowVersion = rowVersion)
}
