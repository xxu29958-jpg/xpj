package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAdaptiveAmountRowDefaults
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ReportsDataSheet(
    overview: ReportsOverview,
    exporting: Boolean,
    exportMessage: UiText?,
    onExport: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        AppSheetScaffold(
            modifier = Modifier.testTag("reports-data-sheet"),
            title = stringResource(R.string.reports_data_title),
            subtitle = stringResource(R.string.reports_scope, displayMonthLabel(overview.month), overview.homeCurrencyCode),
            actions = {
                exportMessage?.let { Text(it.asString()) }
                AppPrimaryButton(
                    text = stringResource(if (exporting) R.string.reports_exporting else R.string.reports_export),
                    modifier = Modifier.fillMaxWidth().testTag("reports-export"), enabled = !exporting, onClick = onExport,
                )
                TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.reports_return_chart))
                }
            },
        ) {
            Text(stringResource(R.string.reports_data_description), style = MaterialTheme.typography.bodyMedium)
            elapsedReportTrend(overview).forEach { point ->
                AppListRow {
                    Column(modifier = Modifier.weight(1f).padding(end = AppSpacing.contentGap),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                        Text(point.label.ifBlank { point.bucket }, style = MaterialTheme.typography.titleMedium)
                        Text(stringResource(R.string.stats_reports_answer_count_value, point.count),
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    AppEndAlignedAmountText(
                        text = point.amountCents?.let { formatDisplayAmount(it, LocalCurrencyDisplay.current) }
                            ?: stringResource(R.string.reports_amount_unavailable),
                        role = AppAmountRole.Medium,
                        modifier = Modifier.weight(AppAdaptiveAmountRowDefaults.listTrailingWeight).align(Alignment.CenterVertically),
                    )
                }
            }
            AppListRow(showDivider = false) {
                Text(stringResource(R.string.stats_reports_answer_title), style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f).padding(end = AppSpacing.contentGap))
                AppEndAlignedAmountText(
                    text = overview.totalAmountCents?.let { formatDisplayAmount(it, LocalCurrencyDisplay.current) }
                        ?: stringResource(R.string.reports_amount_unavailable),
                    role = AppAmountRole.Medium,
                    modifier = Modifier.weight(AppAdaptiveAmountRowDefaults.listTrailingWeight).align(Alignment.CenterVertically),
                )
            }
        }
    }
}
