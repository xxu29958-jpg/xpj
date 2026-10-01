package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.tabularNum
import kotlin.math.abs

@Composable
internal fun ReportsAnswerHeader(
    model: ReportsAnswerModel,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ReportsAnswerTotal(model)
        ReportsAnswerMetrics(model)
    }
}

@Composable
private fun ReportsAnswerTotal(model: ReportsAnswerModel) {
    val currencyDisplay = LocalCurrencyDisplay.current
    AppAdaptiveEditAmountRow(
        amount = model.totalAmountCents?.let { formatDisplayAmount(it, currencyDisplay) }
            ?: stringResource(R.string.reports_amount_unavailable),
        style = AppAdaptiveAmountRowStyle(role = AppAmountRole.Medium),
    ) {
        Column(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = stringResource(R.string.stats_reports_answer_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.stats_reports_answer_subtitle, displayMonthLabel(model.month), model.count),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun ReportsAnswerMetrics(model: ReportsAnswerModel) {
    AppAdaptiveMetricGrid(itemCount = if (model.hasYearOverYearComparison) 3 else 2) { index, metricModifier ->
        if (index == 0 && model.hasPreviousMonthComparison) {
            ReportsAnswerMetric(
                label = stringResource(R.string.stats_reports_answer_previous_label),
                value = monthDeltaValue(model),
                caption = monthDeltaCaption(model),
                modifier = metricModifier,
            )
        } else if (index == 0) {
            ReportsAnswerMetric(
                label = stringResource(R.string.stats_reports_answer_current_label),
                value = stringResource(R.string.stats_reports_answer_count_value, model.count),
                caption = stringResource(if (model.monthDeltaAmountCents == null) R.string.reports_comparison_unavailable else R.string.stats_reports_answer_no_previous_caption),
                modifier = metricModifier,
            )
        } else if (index == 1 && model.hasYearOverYearComparison) {
            ReportsAnswerMetric(
                label = stringResource(R.string.stats_reports_answer_yoy_label),
                value = signedDeltaValue(model.yearOverYearDeltaAmountCents),
                caption = displayMonthLabel(model.yearOverYearMonth),
                modifier = metricModifier,
            )
        } else ReportsAnswerMetric(
            label = stringResource(R.string.stats_reports_answer_active_label),
            value = model.trendEvidence?.let { stringResource(R.string.stats_reports_answer_active_value, it.positiveBucketCount) }
                ?: stringResource(R.string.reports_amount_unavailable),
            caption = model.trendEvidence?.let { peakCaption(it) } ?: stringResource(R.string.reports_comparison_unavailable),
            modifier = metricModifier,
        )
    }
}

@Composable
private fun ReportsAnswerMetric(
    label: String,
    value: String,
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
            overflow = TextOverflow.Ellipsis,
        )
        AppAmountText(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            role = AppAmountRole.Compact,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
        )
    }
}

@Composable
private fun monthDeltaValue(model: ReportsAnswerModel): String =
    if (model.previousTotalAmountCents?.let { it <= 0L } == true && model.monthDeltaAmountCents?.let { it > 0L } == true) {
        stringResource(R.string.stats_reports_answer_no_previous)
    } else {
        signedDeltaValue(model.monthDeltaAmountCents)
    }

@Composable
private fun monthDeltaCaption(model: ReportsAnswerModel): String =
    model.monthDeltaPercent?.let { percent ->
        stringResource(R.string.stats_reports_answer_percent, percent)
    } ?: displayMonthLabel(model.previousMonth)

@Composable
private fun signedDeltaValue(deltaAmountCents: Long?): String {
    if (deltaAmountCents == null) return stringResource(R.string.reports_amount_unavailable)
    val currencyDisplay = LocalCurrencyDisplay.current
    return when {
        deltaAmountCents > 0L -> stringResource(
            R.string.stats_reports_answer_delta_more,
            formatDisplayAmount(deltaAmountCents, currencyDisplay),
        )
        deltaAmountCents < 0L -> stringResource(
            R.string.stats_reports_answer_delta_less,
            formatDisplayAmount(abs(deltaAmountCents), currencyDisplay),
        )
        else -> stringResource(R.string.stats_reports_answer_delta_flat)
    }
}

@Composable
private fun peakCaption(evidence: ReportsTrendEvidence): String =
    evidence.peak?.takeIf { it.amountCents > 0L }?.let {
        stringResource(R.string.stats_reports_answer_peak_caption, it.label, evidence.peakSharePercent)
    } ?: stringResource(R.string.stats_reports_answer_no_trend)
