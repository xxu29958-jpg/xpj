package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.viewmodel.canEnterManualRate
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString

@Composable
internal fun ReportsProjectionControls(
    overview: ReportsOverview,
    onCategory: (String?) -> Unit,
    onRepair: (CurrencyProjectionGap?) -> Unit,
    onExport: () -> Unit,
    exporting: Boolean,
    exportMessage: UiText?,
) {
    Column {
        Text(stringResource(R.string.reports_currency, overview.homeCurrencyCode))
        if (overview.missingRates.isNotEmpty()) Text(stringResource(R.string.reports_projection_incomplete))
        overview.missingRates.forEach { gap ->
            if (MissingExchangeRateDto(gap.sourceCurrencyCode, gap.homeCurrencyCode, gap.rateDate).canEnterManualRate()) {
                TextButton(onClick = { onRepair(gap) }, modifier = Modifier.testTag("report-rate-${gap.sourceCurrencyCode}-${gap.rateDate}")) {
                    Text(stringResource(R.string.reports_rate_gap, requireNotNull(gap.sourceCurrencyCode), gap.homeCurrencyCode, requireNotNull(gap.rateDate)))
                }
            } else Text(stringResource(R.string.reports_unknown_fact))
        }
        TextButton(onClick = { onRepair(null) }) { Text(stringResource(R.string.reports_repair_rates)) }
        ReportsMerchantCategoryFilter(overview, onCategory)
        TextButton(onClick = onExport, enabled = !exporting, modifier = Modifier.testTag("reports-export")) {
            Text(stringResource(if (exporting) R.string.reports_exporting else R.string.reports_export))
        }
        exportMessage?.let { Text(it.asString()) }
    }
}

@Composable
private fun ReportsMerchantCategoryFilter(overview: ReportsOverview, onCategory: (String?) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = true }, modifier = Modifier.testTag("reports-category-filter")) {
            Text(stringResource(R.string.reports_merchant_category) + "：" +
                (overview.merchantCategory ?: stringResource(R.string.reports_all_categories)))
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(text = { Text(stringResource(R.string.reports_all_categories)) },
                onClick = { expanded = false; onCategory(null) })
            overview.categoryComparison.map { it.category }.distinct().sorted().forEach { category ->
                DropdownMenuItem(text = { Text(category) }, onClick = { expanded = false; onCategory(category) })
            }
        }
    }
}
