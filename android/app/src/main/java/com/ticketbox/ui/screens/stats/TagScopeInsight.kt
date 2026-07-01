package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.StatsSource

internal data class TagScopeInsightModel(
    val tag: String,
    val month: String,
    val totalAmountCents: Long,
    val count: Int,
    val recentAmountCents: Long,
    val recentActiveDayCount: Int,
) {
    val hasSpend: Boolean = totalAmountCents > 0L && count > 0
    val hasRecentSpend: Boolean = recentAmountCents > 0L && recentActiveDayCount > 0
}

internal fun tagScopeInsightModel(
    stats: MonthlyStats,
    selectedTag: String,
    dailyTrend: List<DailySpend>,
): TagScopeInsightModel? {
    val cleanTag = selectedTag.trim()
    if (cleanTag.isBlank()) return null
    val recent = dailyTrend.map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
    return TagScopeInsightModel(
        tag = cleanTag,
        month = stats.month,
        totalAmountCents = stats.totalAmountCents.coerceAtLeast(0L),
        count = stats.count.coerceAtLeast(0),
        recentAmountCents = recent.sumOf { it.amountCents },
        recentActiveDayCount = recent.count { it.amountCents > 0L },
    )
}

@Composable
internal fun TagScopeInsight(
    stats: MonthlyStats,
    selectedTag: String,
    dailyTrend: List<DailySpend>,
    statsSource: StatsSource,
    modifier: Modifier = Modifier,
) {
    val model = remember(stats, selectedTag, dailyTrend) {
        tagScopeInsightModel(stats = stats, selectedTag = selectedTag, dailyTrend = dailyTrend)
    } ?: return
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        TagScopeHeader(model = model, statsSource = statsSource)
        TagScopeMetrics(model = model)
        RecentTrendCard(dailyTrend)
    }
}

@Composable
private fun TagScopeHeader(
    model: TagScopeInsightModel,
    statsSource: StatsSource,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Top,
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
            ) {
                Text(
                    text = stringResource(R.string.stats_tag_scope_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.stats_tag_scope_subtitle, model.tag, displayMonthLabel(model.month)),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                text = tagScopeSourceLabel(statsSource),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Text(
            text = formatDisplayAmount(model.totalAmountCents, currencyDisplay),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.headlineSmall.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            autoSize = TextAutoSize.StepBased(minFontSize = 18.sp, maxFontSize = 28.sp, stepSize = 1.sp),
            maxLines = 1,
            overflow = TextOverflow.Clip,
        )
        Text(
            text = if (model.hasSpend) {
                stringResource(R.string.stats_tag_scope_confirmed_caption, model.count)
            } else {
                stringResource(R.string.stats_tag_scope_empty_caption)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun TagScopeMetrics(model: TagScopeInsightModel) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        TagScopeMetric(
            label = stringResource(R.string.stats_tag_scope_month_count_label),
            value = stringResource(R.string.stats_overview_count_value, model.count),
            modifier = Modifier.weight(1f),
        )
        TagScopeMetric(
            label = stringResource(R.string.stats_tag_scope_recent_label),
            value = if (model.hasRecentSpend) {
                formatDisplayAmount(model.recentAmountCents, currencyDisplay)
            } else {
                stringResource(R.string.stats_tag_scope_recent_empty)
            },
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun TagScopeMetric(
    label: String,
    value: String,
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
            style = MaterialTheme.typography.titleMedium.tabularNum(),
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun tagScopeSourceLabel(statsSource: StatsSource): String =
    if (statsSource == StatsSource.LocalFallback) {
        stringResource(R.string.stats_tag_scope_source_local)
    } else {
        stringResource(R.string.stats_tag_scope_source_monthly)
    }
