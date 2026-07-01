package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun StatsMonthChip(
    selectedMonth: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Start,
    ) {
        AppFilterChip(
            selected = true,
            onClick = onClick,
            label = selectedMonth.takeIf { it.isNotBlank() }?.let(::displayMonthLabel)
                ?: stringResource(R.string.stats_empty_month_chip_all),
            trailingIcon = {
                Icon(
                    imageVector = Icons.Filled.ExpandMore,
                    contentDescription = stringResource(R.string.stats_empty_month_chip_description),
                    modifier = Modifier.size(AppSpacing.cardPadding),
                )
            },
        )
    }
}

@Composable
internal fun EmptyStatsCard(
    title: String = stringResource(R.string.stats_empty_card_title),
    body: String = stringResource(R.string.stats_empty_card_body),
    onRefresh: (() -> Unit)? = null,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(
            text = body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        StatsSkeletonPlaceholder()
        onRefresh?.let {
            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = it,
            ) {
                Text(stringResource(R.string.stats_empty_card_refresh))
            }
        }
    }
}

@Composable
private fun StatsSkeletonPlaceholder() {
    val visuals = LocalThemeVisuals.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.medium))
            .background(visuals.chipUnselected.copy(alpha = 0.48f))
            .padding(AppSpacing.cardPaddingTight),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        SkeletonBlock(title = stringResource(R.string.stats_empty_skeleton_month_spend), widthFraction = 0.72f)
        SkeletonBlock(title = stringResource(R.string.stats_empty_skeleton_category_share), widthFraction = 0.88f)
        SkeletonBlock(title = stringResource(R.string.stats_empty_skeleton_frequent_merchants), widthFraction = 0.64f)
    }
}

@Composable
private fun SkeletonBlock(
    title: String,
    widthFraction: Float,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        Text(
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.62f),
            style = MaterialTheme.typography.labelMedium,
        )
        Box(
            modifier = Modifier
                .fillMaxWidth(widthFraction)
                .height(AppSpacing.contentGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)),
        )
    }
}
