package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import kotlin.test.Test
import kotlin.test.assertEquals

class MerchantManagementScreenModelTest {
    @Test
    fun summarySeparatesCatalogAndAliasStates() {
        val summary = merchantManagementSummaryModel(
            catalog = listOf(
                catalog("c1", status = "active", usage = 6),
                catalog("c2", status = "hidden", usage = 2),
                catalog("c3", status = "merged", usage = 4),
            ),
            aliases = listOf(
                alias("a1", enabled = true),
                alias("a2", enabled = false),
                alias("a3", enabled = true),
            ),
        )

        assertEquals(
            MerchantManagementSummaryModel(
                totalCatalogCount = 3,
                visibleCatalogCount = 1,
                mergedCatalogCount = 1,
                enabledAliasCount = 2,
                totalAliasCount = 3,
                usageCount = 12,
            ),
            summary,
        )
    }

    @Test
    fun summaryDoesNotLetNegativeUsagePolluteCounts() {
        val summary = merchantManagementSummaryModel(
            catalog = listOf(catalog("c1", status = "active", usage = -5)),
            aliases = emptyList(),
        )

        assertEquals(1, summary.totalCatalogCount)
        assertEquals(1, summary.visibleCatalogCount)
        assertEquals(0, summary.mergedCatalogCount)
        assertEquals(0, summary.enabledAliasCount)
        assertEquals(0, summary.totalAliasCount)
        assertEquals(0, summary.usageCount)
    }

    private fun catalog(id: String, status: String, usage: Int): MerchantCatalog =
        MerchantCatalog(
            publicId = id,
            displayName = id,
            merchantKey = id,
            status = status,
            mergedIntoPublicId = null,
            usageCount = usage,
            createdAt = "2026-07-01T00:00:00Z",
            updatedAt = "2026-07-01T00:00:00Z",
            rowVersion = 1L,
            deletedAt = null,
        )

    private fun alias(id: String, enabled: Boolean): MerchantAlias =
        MerchantAlias(
            publicId = id,
            canonicalMerchant = "canonical-$id",
            canonicalKey = "canonical-$id",
            alias = "alias-$id",
            aliasKey = "alias-$id",
            enabled = enabled,
            createdAt = "2026-07-01T00:00:00Z",
            updatedAt = "2026-07-01T00:00:00Z",
            rowVersion = 1L,
        )
}
