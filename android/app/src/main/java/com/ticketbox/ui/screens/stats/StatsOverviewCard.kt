package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.AppTypography
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun StatsOverviewCard(
    stats: MonthlyStats,
    recent7DaysAmountCents: Long,
    comparison: MonthComparison?,
) {
    val currencyDisplay = LocalCurrencyDisplay.current

    AppContentCard(
        contentPadding = PaddingValues(
            horizontal = AppSpacing.cardPaddingSmall,
            vertical = AppSpacing.cardPaddingTight,
        ),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Text(
            text = "本月支出",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.Bottom,
        ) {
            Text(
                modifier = Modifier.weight(1f),
                text = formatDisplayAmount(stats.totalAmountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.titleLarge.copy(
                    fontSize = AppTypography.amountLarge.size,
                    lineHeight = 38.sp,
                    letterSpacing = 0.sp,
                    fontWeight = AppTypography.amountLarge.weight,
                ).tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            comparison?.let { MonthDeltaPill(it, currencyDisplay) }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        ) {
            CompactMetric(
                label = "账单",
                value = "${stats.count} 笔",
                modifier = Modifier.weight(1f),
            )
            CompactMetric(
                label = "最近 7 天",
                value = formatDisplayAmount(recent7DaysAmountCents, currencyDisplay),
                modifier = Modifier.weight(1f),
            )
        }
        HeroTrendLine()
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
        delta == 0L -> "持平" to MaterialTheme.colorScheme.onSurfaceVariant
        delta > 0L -> {
            val percent = comparison.percentChange?.let { " +${it}%" }.orEmpty()
            "↑ ${formatDisplayAmount(kotlin.math.abs(delta), currencyDisplay)}$percent" to visuals.warningTint
        }
        else -> {
            val percent = comparison.percentChange?.let { " ${kotlin.math.abs(it)}%" }.orEmpty()
            "↓ ${formatDisplayAmount(kotlin.math.abs(delta), currencyDisplay)}$percent" to visuals.primary
        }
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(tint.copy(alpha = 0.14f))
            .padding(horizontal = 10.dp, vertical = 4.dp),
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
private fun HeroTrendLine() {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        listOf(0.30f, 0.42f, 0.35f, 0.68f, 0.50f, 0.46f, 0.78f, 0.58f, 0.48f, 0.64f).forEachIndexed { index, weight ->
            Box(
                modifier = Modifier
                    .weight(weight)
                    .height(if (index == 6) 10.dp else 7.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(visuals.primary.copy(alpha = if (index == 6) 0.72f else 0.30f)),
            )
        }
    }
}
