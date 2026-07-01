package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun MerchantRankingBlock(
    rows: List<ReportMerchantRanking>,
    rankingMetric: ReportRankingMetric,
) {
    val maxValue = merchantRankingMaxValue(rows, rankingMetric)
    val merchantFallback = stringResource(R.string.stats_reports_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap + AppSpacing.tinyGap)) {
        Text(
            text = stringResource(merchantRankingTitleRes(rankingMetric)),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.body.weight,
        )
        rows.forEach { row ->
            MerchantRankingRow(
                label = row.merchant.ifBlank { merchantFallback },
                row = row,
                rankingMetric = rankingMetric,
                maxValue = maxValue,
            )
        }
    }
}

@Composable
private fun MerchantRankingRow(
    label: String,
    row: ReportMerchantRanking,
    rankingMetric: ReportRankingMetric,
    maxValue: Long,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val value = merchantRankingBarValue(row, rankingMetric)
    val progress = if (maxValue > 0L) (value.toFloat() / maxValue.toFloat()).coerceIn(0f, 1f) else 0f
    val primaryText = when (rankingMetric) {
        ReportRankingMetric.Count -> stringResource(R.string.stats_reports_bar_count, row.count)
        ReportRankingMetric.Amount -> formatDisplayAmount(row.amountCents, currencyDisplay)
    }
    val supportingText = when (rankingMetric) {
        ReportRankingMetric.Count -> stringResource(
            R.string.stats_reports_merchant_total_amount,
            formatDisplayAmount(row.amountCents, currencyDisplay),
        )
        ReportRankingMetric.Amount -> stringResource(R.string.stats_reports_bar_count, row.count)
    }

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap)) {
        MerchantRankingTopLine(label = label, primaryText = primaryText)
        MerchantRankingBar(progress = progress)
        Text(
            text = supportingText,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun MerchantRankingTopLine(label: String, primaryText: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.bodyMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = primaryText,
            style = MaterialTheme.typography.labelLarge.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
        )
    }
}

@Composable
private fun MerchantRankingBar(progress: Float) {
    val chartTokens = LocalChartTokens.current
    val fillColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(AppSpacing.miniGap)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(chartTokens.grid),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(progress)
                .height(AppSpacing.miniGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(fillColor.copy(alpha = AppAlpha.heavy)),
        )
    }
}

internal fun merchantRankingBarValue(row: ReportMerchantRanking, rankingMetric: ReportRankingMetric): Long =
    when (rankingMetric) {
        ReportRankingMetric.Count -> row.count.coerceAtLeast(0).toLong()
        ReportRankingMetric.Amount -> row.amountCents.coerceAtLeast(0L)
    }

internal fun merchantRankingMaxValue(rows: List<ReportMerchantRanking>, rankingMetric: ReportRankingMetric): Long =
    rows.maxOfOrNull { merchantRankingBarValue(it, rankingMetric) }?.coerceAtLeast(1L) ?: 1L

private fun merchantRankingTitleRes(rankingMetric: ReportRankingMetric): Int = when (rankingMetric) {
    ReportRankingMetric.Count -> R.string.stats_reports_merchant_frequency_title
    ReportRankingMetric.Amount -> R.string.stats_reports_merchant_spend_title
}
