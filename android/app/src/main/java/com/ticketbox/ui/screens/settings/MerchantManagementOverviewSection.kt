package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
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
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

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
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                MerchantOverviewMetric(
                    label = stringResource(R.string.merchant_management_overview_catalog_label),
                    value = summary.totalCatalogCount,
                    caption = stringResource(R.string.merchant_management_overview_catalog_caption),
                    modifier = Modifier.weight(1f),
                )
                MerchantOverviewMetric(
                    label = stringResource(R.string.merchant_management_overview_visible_label),
                    value = summary.visibleCatalogCount,
                    caption = stringResource(R.string.merchant_management_overview_visible_caption),
                    modifier = Modifier.weight(1f),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                MerchantOverviewMetric(
                    label = stringResource(R.string.merchant_management_overview_alias_label),
                    value = summary.enabledAliasCount,
                    caption = stringResource(R.string.merchant_management_overview_alias_caption),
                    modifier = Modifier.weight(1f),
                )
                MerchantOverviewMetric(
                    label = stringResource(R.string.merchant_management_overview_usage_label),
                    value = summary.usageCount,
                    caption = stringResource(R.string.merchant_management_overview_usage_caption),
                    modifier = Modifier.weight(1f),
                )
            }
            Text(
                text = stringResource(R.string.merchant_management_overview_body, summary.mergedCatalogCount),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun MerchantOverviewMetric(
    label: String,
    value: Int,
    caption: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
        Text(
            text = value.toString(),
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
    }
}
