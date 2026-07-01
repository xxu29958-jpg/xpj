package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.HorizontalDivider
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
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.asAmount
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.StatsSource

internal data class StatsOverviewTrendData(
    val dailyTrend: List<DailySpend> = emptyList(),
    val reportTrend: List<ReportTrendPoint> = emptyList(),
    val includeRecentUpload: Boolean = false,
    val lastUploadAt: String? = null,
)

@Composable
internal fun StatsOverviewCard(
    stats: MonthlyStats,
    recent7DaysAmountCents: Long?,
    comparison: MonthComparison?,
    trendData: StatsOverviewTrendData = StatsOverviewTrendData(),
    statsSource: StatsSource = StatsSource.Backend,
) {
    val evidenceOnly = false
    val currencyDisplay = LocalCurrencyDisplay.current
    val hasCurrentConfirmedSpend = stats.count > 0 && stats.totalAmountCents > 0L
    val hasTrendData = trendData.reportTrend.any { it.amountCents > 0L } ||
        trendData.dailyTrend.any { it.amountCents > 0L }

    if (evidenceOnly && !hasTrendData) {
        return
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        if (evidenceOnly) {
            OverviewRhythmHeader(
                stats = stats,
                recent7DaysAmountCents = recent7DaysAmountCents,
                statsSource = statsSource,
                currencyDisplay = currencyDisplay,
            )
        } else {
            OverviewAmountHeader(
                stats = stats,
                statsSource = statsSource,
                hasCurrentConfirmedSpend = hasCurrentConfirmedSpend,
                comparison = comparison,
                currencyDisplay = currencyDisplay,
            )
        }
        if (!evidenceOnly) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
            ) {
                CompactMetric(
                    label = stringResource(R.string.stats_overview_count_label),
                    value = stringResource(R.string.stats_overview_count_value, stats.count),
                    modifier = Modifier.weight(1f),
                )
                CompactMetric(
                    label = stringResource(R.string.stats_overview_recent7_label),
                    value = recent7DaysAmountCents?.let { formatDisplayAmount(it, currencyDisplay) }
                        ?: stringResource(R.string.stats_overview_recent7_unavailable),
                    modifier = Modifier.weight(1f),
                )
            }
        }
        if (trendData.includeRecentUpload && !evidenceOnly) {
            OverviewRecentUploadRow(lastUploadAt = trendData.lastUploadAt)
        }
        if (hasTrendData || !evidenceOnly) {
            HeroSpendTrend(
                dailyTrend = trendData.dailyTrend,
                reportTrend = trendData.reportTrend,
                currencyDisplay = currencyDisplay,
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun OverviewAmountHeader(
    stats: MonthlyStats,
    statsSource: StatsSource,
    hasCurrentConfirmedSpend: Boolean,
    comparison: MonthComparison?,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        OverviewTitleRow(
            title = stringResource(R.string.stats_overview_month_spend_label),
            showLocalBadge = statsSource == StatsSource.LocalFallback,
        )
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = formatDisplayAmount(stats.totalAmountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleLarge.asAmount(AppAmountRole.Hero),
                autoSize = TextAutoSize.StepBased(
                    minFontSize = 22.sp,
                    maxFontSize = AppAmountRole.Hero.role.size,
                    stepSize = 1.sp,
                ),
                maxLines = 1,
                overflow = TextOverflow.Clip,
            )
            when {
                hasCurrentConfirmedSpend -> comparison?.let { MonthDeltaPill(it, currencyDisplay) }
                comparison?.previousAmountCents != null && comparison.previousAmountCents > 0L -> Text(
                    text = stringResource(R.string.stats_overview_empty_month_comparison_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
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
