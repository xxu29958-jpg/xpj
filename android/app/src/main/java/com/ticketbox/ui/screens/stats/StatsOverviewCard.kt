package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.unit.sp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppWindowWidthClass
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.StatsSource

internal data class StatsOverviewTrendData(
    val reportTrend: List<ReportTrendPoint> = emptyList(),
    val includeRecentUpload: Boolean = false,
    val lastUploadAt: String? = null,
)

/** 概览头部事实：同一 state.stats 的月总量、来源、近 7 天、月对比与标签作用域。 */
internal data class StatsOverviewHeaderModel(
    val stats: MonthlyStats,
    val statsSource: StatsSource,
    val recent7DaysAmountCents: Long?,
    val comparison: MonthComparison?,
    val tagScope: TagScopeInsightModel? = null,
)

@Composable
internal fun StatsOverviewCard(
    header: StatsOverviewHeaderModel,
    trendData: StatsOverviewTrendData = StatsOverviewTrendData(),
) {
    val evidenceOnly = false
    val currencyDisplay = LocalCurrencyDisplay.current
    val compactWindow = LocalAppAdaptiveLayoutPolicy.current.widthClass == AppWindowWidthClass.Compact
    val hasTrendData = trendData.reportTrend.any { it.amountCents > 0L }

    if (evidenceOnly && !hasTrendData) {
        return
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        if (evidenceOnly) {
            OverviewRhythmHeader(
                stats = header.stats,
                recent7DaysAmountCents = header.recent7DaysAmountCents,
                statsSource = header.statsSource,
                currencyDisplay = currencyDisplay,
            )
        } else {
            OverviewAmountHeader(
                header = header,
                currencyDisplay = currencyDisplay,
            )
        }
        if (!evidenceOnly) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
            ) {
                CompactMetric(
                    label = stringResource(R.string.stats_overview_count_label),
                    value = stringResource(R.string.stats_overview_count_value, header.stats.count),
                    modifier = Modifier.weight(1f, fill = compactWindow),
                )
                CompactMetric(
                    label = stringResource(R.string.stats_overview_recent7_label),
                    value = header.recent7DaysAmountCents?.let { formatDisplayAmount(it, currencyDisplay) }
                        ?: stringResource(R.string.stats_overview_recent7_unavailable),
                    modifier = Modifier.weight(1f, fill = compactWindow),
                )
            }
        }
        if (trendData.includeRecentUpload && !evidenceOnly) {
            OverviewRecentUploadRow(lastUploadAt = trendData.lastUploadAt)
        }
        if (hasTrendData || !evidenceOnly) {
            HeroSpendTrend(
                reportTrend = trendData.reportTrend,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun OverviewAmountHeader(
    header: StatsOverviewHeaderModel,
    currencyDisplay: CurrencyDisplay,
) {
    val hasCurrentConfirmedSpend = header.stats.count > 0 && header.stats.totalAmountCents > 0L
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        header.tagScope?.let { scope ->
            TagScopeContextRow(model = scope, statsSource = header.statsSource)
        }
        OverviewTitleRow(
            title = stringResource(R.string.stats_overview_month_spend_label),
            showLocalBadge = header.statsSource == StatsSource.LocalFallback,
        )
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            AppAmountText(
                modifier = Modifier.fillMaxWidth(),
                text = formatDisplayAmount(header.stats.totalAmountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                role = AppAmountRole.Hero,
                minFontSize = 22.sp,
            )
            when {
                hasCurrentConfirmedSpend -> header.comparison?.let { MonthDeltaPill(it, currencyDisplay) }
                header.comparison?.let { it.previousAmountCents > 0L } == true -> Text(
                    text = stringResource(R.string.stats_overview_empty_month_comparison_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        header.tagScope?.let { scope ->
            Text(
                text = if (scope.hasSpend) {
                    stringResource(R.string.stats_tag_scope_confirmed_caption, scope.count)
                } else {
                    stringResource(R.string.stats_tag_scope_empty_caption)
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/**
 * 标签筛选时 hero 的作用域行：左为上下文（#标签 · 月份），右为来源标签。
 * 事实与 Trend 页 TagScopeInsight 完全同源（tagScopeInsightModel / tagScopeSourceLabelRes），
 * 只改层级表达，不新算任何数。
 */
@Composable
private fun TagScopeContextRow(
    model: TagScopeInsightModel,
    statsSource: StatsSource,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            modifier = Modifier.weight(1f),
            text = stringResource(R.string.stats_tag_scope_subtitle, model.tag, displayMonthLabel(model.month)),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = stringResource(tagScopeSourceLabelRes(statsSource)),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun OverviewRhythmHeader(
    stats: MonthlyStats,
    recent7DaysAmountCents: Long?,
    statsSource: StatsSource,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        OverviewTitleRow(
            title = stringResource(R.string.stats_overview_rhythm_title),
            showLocalBadge = statsSource == StatsSource.LocalFallback,
        )
        Text(
            text = if (stats.count > 0) {
                stringResource(
                    R.string.stats_overview_rhythm_caption,
                    stats.count,
                    recent7DaysAmountCents?.let { formatDisplayAmount(it, currencyDisplay) }
                        ?: stringResource(R.string.stats_overview_recent7_unavailable),
                )
            } else {
                stringResource(R.string.stats_overview_rhythm_caption_empty)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun OverviewTitleRow(
    title: String,
    showLocalBadge: Boolean,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            modifier = Modifier.weight(1f),
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (showLocalBadge) {
            Text(
                text = stringResource(R.string.stats_overview_local_estimate_badge),
                modifier = Modifier
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(MaterialTheme.colorScheme.secondaryContainer)
                    .padding(horizontal = AppSpacing.smallGap, vertical = AppSpacing.tinyGap),
                color = MaterialTheme.colorScheme.onSecondaryContainer,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
private fun MonthDeltaPill(
    comparison: MonthComparison,
    currencyDisplay: CurrencyDisplay,
) {
    if (comparison.previousAmountCents == 0L) return
    val visuals = LocalThemeVisuals.current
    val delta = comparison.deltaAmountCents
    val (label, tint) = when {
        delta == 0L -> stringResource(R.string.stats_overview_delta_flat) to MaterialTheme.colorScheme.onSurfaceVariant
        delta > 0L -> {
            val percent = comparison.percentChange?.let {
                stringResource(R.string.stats_overview_delta_percent_up, it)
            }.orEmpty()
            stringResource(
                R.string.stats_overview_delta_up,
                formatDisplayAmount(kotlin.math.abs(delta), currencyDisplay),
                percent,
            ) to visuals.warningTint
        }
        else -> {
            val percent = comparison.percentChange?.let {
                stringResource(R.string.stats_overview_delta_percent_down, kotlin.math.abs(it))
            }.orEmpty()
            stringResource(
                R.string.stats_overview_delta_down,
                formatDisplayAmount(kotlin.math.abs(delta), currencyDisplay),
                percent,
            ) to visuals.textDefault
        }
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(tint.copy(alpha = AppAlpha.subtle))
            .padding(horizontal = AppSpacing.contentGap, vertical = AppSpacing.miniGap),
    ) {
        Text(
            text = label,
            color = tint,
            style = MaterialTheme.typography.labelSmall.tabularNum(),
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun CompactMetric(
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
private fun OverviewRecentUploadRow(lastUploadAt: String?) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        CompactMetric(
            label = stringResource(R.string.stats_recent_upload_title),
            value = lastUploadAt?.let { displayTime(it) } ?: stringResource(R.string.stats_recent_upload_empty),
            modifier = Modifier.weight(1f),
        )
        Text(
            text = stringResource(R.string.stats_recent_upload_hint),
            modifier = Modifier.weight(1.25f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
