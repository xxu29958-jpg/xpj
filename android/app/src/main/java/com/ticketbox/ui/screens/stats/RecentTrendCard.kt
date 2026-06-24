package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun RecentTrendCard(trend: List<DailySpend>) {
    val maxAmount = trend.maxOfOrNull { it.amountCents } ?: 0L

    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(
                horizontal = AppSpacing.cardPaddingSmall,
                vertical = AppSpacing.cardPaddingTight,
            ),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(stringResource(R.string.stats_recent_trend_title), style = MaterialTheme.typography.titleMedium)
                Text(
                    text = stringResource(R.string.stats_recent_trend_source),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (trend.isEmpty() || maxAmount == 0L) {
                Text(
                    text = stringResource(R.string.stats_recent_trend_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(92.dp),
                    horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                ) {
                    trend.forEach { day ->
                        DailyTrendBar(
                            modifier = Modifier.weight(1f),
                            day = day,
                            maxAmount = maxAmount,
                        )
                    }
                }
            }
        }
    }
}

@Composable
internal fun RecentUploadCard(lastUploadAt: String?) {
    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(
                horizontal = AppSpacing.cardPaddingSmall,
                vertical = AppSpacing.cardPaddingTight,
            ),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(R.string.stats_recent_upload_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = lastUploadAt?.let { displayTime(it) } ?: stringResource(R.string.stats_recent_upload_empty),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.stats_recent_upload_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun DailyTrendBar(
    modifier: Modifier,
    day: DailySpend,
    maxAmount: Long,
) {
    val visuals = LocalThemeVisuals.current
    val progress = if (maxAmount > 0) {
        (day.amountCents.toFloat() / maxAmount.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val barHeight = if (day.amountCents > 0L) {
        (12 + 46 * progress).dp
    } else {
        8.dp
    }
    val barColor = if (day.amountCents > 0L) {
        visuals.primary
    } else {
        visuals.chipUnselected.copy(alpha = 0.72f)
    }
    // WCAG 1.1.1: the bar height is the only amount cue; give TalkBack the date + amount.
    val barA11y = stringResource(R.string.stats_recent_trend_bar_a11y, day.label, formatAmount(day.amountCents))

    Column(
        modifier = modifier.semantics(mergeDescendants = true) { contentDescription = barA11y },
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            contentAlignment = Alignment.BottomCenter,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(barHeight)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(barColor),
            )
        }
        Text(
            text = day.label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}
