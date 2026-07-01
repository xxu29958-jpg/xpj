package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.Top,
    ) {
        Column(
            modifier = Modifier.weight(1f),
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
        Text(
            text = formatDisplayAmount(model.totalAmountCents, currencyDisplay),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.headlineSmall.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            autoSize = TextAutoSize.StepBased(
                minFontSize = 18.sp,
                maxFontSize = 28.sp,
                stepSize = 1.sp,
            ),
            maxLines = 1,
            overflow = TextOverflow.Clip,
        )
    }
}

@Composable
private fun ReportsAnswerMetrics(model: ReportsAnswerModel) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ReportsAnswerMetric(
            label = stringResource(R.string.stats_reports_answer_previous_label),
            value = monthDeltaValue(model),
            caption = monthDeltaCaption(model),
            modifier = Modifier.weight(1f),
        )
        ReportsAnswerMetric(
            label = stringResource(R.string.stats_reports_answer_yoy_label),
            value = signedDeltaValue(model.yearOverYearDeltaAmountCents),
            caption = displayMonthLabel(model.yearOverYearMonth),
            modifier = Modifier.weight(1f),
        )
        ReportsAnswerMetric(
            label = stringResource(R.string.stats_reports_answer_active_label),
            value = stringResource(
                R.string.stats_reports_answer_active_value,
                model.trendEvidence.positiveBucketCount,
            ),
            caption = peakCaption(model.trendEvidence),
            modifier = Modifier.weight(1f),
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
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
            autoSize = TextAutoSize.StepBased(
                minFontSize = 11.sp,
                maxFontSize = 14.sp,
                stepSize = 1.sp,
            ),
            maxLines = 1,
            overflow = TextOverflow.Clip,
        )
        Text(
            text = caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun monthDeltaValue(model: ReportsAnswerModel): String =
    if (model.previousTotalAmountCents <= 0L && model.monthDeltaAmountCents > 0L) {
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
private fun signedDeltaValue(deltaAmountCents: Long): String {
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
