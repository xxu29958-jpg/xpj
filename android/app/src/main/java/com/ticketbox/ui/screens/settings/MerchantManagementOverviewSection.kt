package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MerchantAlias
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun MerchantManagementOverviewSection(
    catalog: List<MerchantCatalog>,
    aliases: List<MerchantAlias>,
) {
    val summary = remember(catalog, aliases) { merchantManagementSummaryModel(catalog, aliases) }
    SettingsSection(
        title = stringResource(R.string.merchant_management_section_overview),
        icon = Icons.Filled.Tune,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.merchant_management_overview_catalog_label),
                        value = summary.totalCatalogCount.toString(),
                        caption = stringResource(R.string.merchant_management_overview_catalog_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.merchant_management_overview_visible_label),
                        value = summary.visibleCatalogCount.toString(),
                        caption = stringResource(R.string.merchant_management_overview_visible_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.merchant_management_overview_alias_label),
                        value = summary.enabledAliasCount.toString(),
                        caption = stringResource(R.string.merchant_management_overview_alias_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.merchant_management_overview_usage_label),
                        value = summary.usageCount.toString(),
                        caption = stringResource(R.string.merchant_management_overview_usage_caption),
                    ),
                ),
            )
            Text(
                text = stringResource(R.string.merchant_management_overview_body, summary.mergedCatalogCount),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
