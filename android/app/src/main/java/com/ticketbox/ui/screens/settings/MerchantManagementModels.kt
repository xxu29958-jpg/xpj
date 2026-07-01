package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog

internal data class MerchantManagementSummaryModel(
    val totalCatalogCount: Int,
    val visibleCatalogCount: Int,
    val mergedCatalogCount: Int,
    val enabledAliasCount: Int,
    val totalAliasCount: Int,
    val usageCount: Int,
)

internal fun merchantManagementSummaryModel(
    catalog: List<MerchantCatalog>,
    aliases: List<MerchantAlias>,
): MerchantManagementSummaryModel =
    MerchantManagementSummaryModel(
        totalCatalogCount = catalog.size.coerceAtLeast(0),
        visibleCatalogCount = catalog.count { it.isActive },
        mergedCatalogCount = catalog.count { it.isMerged },
        enabledAliasCount = aliases.count { it.enabled },
        totalAliasCount = aliases.size.coerceAtLeast(0),
        usageCount = catalog.sumOf { it.usageCount.coerceAtLeast(0) },
    )
