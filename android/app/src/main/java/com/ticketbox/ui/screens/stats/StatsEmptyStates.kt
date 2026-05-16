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
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppEmptyStateCard
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
            label = selectedMonth.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份",
            trailingIcon = {
                Icon(
                    imageVector = Icons.Filled.ExpandMore,
                    contentDescription = "选择统计月份",
                    modifier = Modifier.size(18.dp),
                )
            },
        )
    }
}

@Composable
internal fun EmptyStatsCard(
    title: String = "还没有统计数据",
    body: String = "确认账单后刷新统计，这里会显示本月总支出、分类占比和高频商家。",
    onRefresh: (() -> Unit)? = null,
) {
    AppEmptyStateCard {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
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
                    Text("刷新统计")
                }
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
        SkeletonBlock(title = "本月总支出", widthFraction = 0.72f)
        SkeletonBlock(title = "分类占比", widthFraction = 0.88f)
        SkeletonBlock(title = "高频商家", widthFraction = 0.64f)
    }
}

@Composable
private fun SkeletonBlock(
    title: String,
    widthFraction: Float,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap - 1.dp)) {
        Text(
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.62f),
            style = MaterialTheme.typography.labelMedium,
        )
        Box(
            modifier = Modifier
                .fillMaxWidth(widthFraction)
                .height(10.dp)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)),
        )
    }
}
