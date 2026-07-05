package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState
import kotlin.math.abs

private data class StatsLeadLine(
    val label: String,
    val value: String,
    val caption: String,
)

@Composable
internal fun StatsLeadInsight(state: StatsUiState) {
    val stats = state.stats ?: return
    val overview = state.reportsOverview
    val totalLine = totalLeadLine(overview = overview, stats = stats)
    val deltaLine = monthDeltaLeadLine(overview = overview)
    val variableLine = variableLeadLine(overview = overview)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        StatsLeadHero(
            month = overview?.month ?: stats.month,
            source = sourceLabel(state.statsSource, overview != null),
            totalLine = totalLine,
        )
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            deltaLine?.let { StatsLeadInline(line = it) }
            variableLine?.let { StatsLeadInline(line = it) }
        }
    }
}

@Composable
private fun StatsLeadHero(
    month: String,
    source: String,
    totalLine: StatsLeadLine,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    text = stringResource(R.string.stats_lead_title),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = source,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            Text(
                text = displayMonthLabel(month),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium.tabularNum(),
            )
        }
        AppAmountText(
            modifier = Modifier.fillMaxWidth(),
            text = totalLine.value,
            color = MaterialTheme.colorScheme.onSurface,
            role = AppAmountRole.Hero,
            minFontSize = 22.sp,
        )
        Text(
            text = totalLine.caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun totalLeadLine(
    overview: ReportsOverview?,
    stats: MonthlyStats,
): StatsLeadLine {
    val currencyDisplay = LocalCurrencyDisplay.current
    val amount = overview?.totalAmountCents ?: stats.totalAmountCents
    val count = overview?.count ?: stats.count
    return StatsLeadLine(
        label = stringResource(R.string.stats_lead_total_label),
        value = formatDisplayAmount(amount, currencyDisplay),
        caption = stringResource(R.string.stats_lead_total_caption, count),
    )
}

@Composable
private fun monthDeltaLeadLine(
    overview: ReportsOverview?,
): StatsLeadLine? {
    val evidence = monthDeltaEvidence(overview) ?: return null
    val currencyDisplay = LocalCurrencyDisplay.current
    val delta = evidence.deltaAmountCents
    val percent = monthDeltaPercent(delta, evidence.previousAmountCents)
    return StatsLeadLine(
        label = monthDeltaLabel(delta),
        value = if (delta == 0L) {
            stringResource(R.string.stats_lead_delta_flat)
        } else {
            formatDisplayAmount(abs(delta), currencyDisplay)
        },
        caption = when {
            delta == 0L -> stringResource(R.string.stats_lead_delta_flat)
            else -> stringResource(R.string.stats_lead_month_delta_percent_hint, percent)
        },
    )
}

@Composable
private fun variableLeadLine(overview: ReportsOverview?): StatsLeadLine? {
    if (overview == null) return null
    val category = overview.categoryComparison
        .filter { it.previousCount > 0 && it.previousAmountCents > 0L && it.deltaAmountCents != 0L }
        .maxByOrNull { abs(it.deltaAmountCents) }
    if (category != null) {
        return StatsLeadLine(
            label = stringResource(R.string.stats_lead_variable_label),
            value = category.category,
            caption = categoryDeltaCaption(category),
        )
    }
    val topMerchant = overview.merchantRanking.firstOrNull() ?: return null
    val currencyDisplay = LocalCurrencyDisplay.current
    val amountText = formatDisplayAmount(topMerchant.amountCents, currencyDisplay)
    val caption = when (overview.rankingMetric) {
        ReportRankingMetric.Amount -> stringResource(
            R.string.stats_lead_top_merchant_amount_caption,
            amountText,
            topMerchant.count,
        )
        ReportRankingMetric.Count -> stringResource(
            R.string.stats_lead_top_merchant_count_caption,
            topMerchant.count,
            amountText,
        )
    }
    return StatsLeadLine(
        label = stringResource(R.string.stats_lead_top_merchant_label),
        value = topMerchant.merchant,
        caption = caption,
    )
}

@Composable
private fun StatsLeadInline(line: StatsLeadLine) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = line.label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
            maxLines = 1,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.Bottom,
        ) {
            Text(
                text = line.value,
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleSmall.tabularNum(),
                fontWeight = AppTextHierarchy.heading.weight,
                maxLines = 2,
                overflow = TextOverflow.Clip,
            )
            Text(
                text = line.caption,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall.tabularNum(),
                maxLines = 2,
                overflow = TextOverflow.Clip,
            )
        }
    }
}

@Composable
private fun sourceLabel(statsSource: StatsSource, hasServerReport: Boolean): String = when {
    hasServerReport -> stringResource(R.string.stats_lead_source_server_report)
    statsSource == StatsSource.LocalFallback -> stringResource(R.string.stats_lead_source_local)
    else -> stringResource(R.string.stats_lead_source_monthly)
}

@Composable
private fun deltaLabel(deltaAmountCents: Long): String {
    val currencyDisplay = LocalCurrencyDisplay.current
    return when {
        deltaAmountCents > 0L -> stringResource(
            R.string.stats_lead_delta_more,
            formatDisplayAmount(deltaAmountCents, currencyDisplay),
        )
        deltaAmountCents < 0L -> stringResource(
            R.string.stats_lead_delta_less,
            formatDisplayAmount(abs(deltaAmountCents), currencyDisplay),
        )
        else -> stringResource(R.string.stats_lead_delta_flat)
    }
}

@Composable
private fun monthDeltaLabel(deltaAmountCents: Long): String = when {
    deltaAmountCents > 0L -> stringResource(R.string.stats_lead_month_delta_more_label)
    deltaAmountCents < 0L -> stringResource(R.string.stats_lead_month_delta_less_label)
    else -> stringResource(R.string.stats_lead_month_delta_flat_label)
}

@Composable
private fun categoryDeltaCaption(category: ReportCategoryComparison): String = when {
    category.deltaAmountCents > 0L -> stringResource(
        R.string.stats_lead_category_more,
        deltaLabel(category.deltaAmountCents),
    )
    category.deltaAmountCents < 0L -> stringResource(
        R.string.stats_lead_category_less,
        deltaLabel(category.deltaAmountCents),
    )
    else -> stringResource(R.string.stats_lead_delta_flat)
}

private fun monthDeltaPercent(
    deltaAmountCents: Long,
    previousAmountCents: Long,
): Int {
    if (previousAmountCents <= 0L) return 0
    return ((abs(deltaAmountCents) * 100L) / previousAmountCents).toInt()
}
