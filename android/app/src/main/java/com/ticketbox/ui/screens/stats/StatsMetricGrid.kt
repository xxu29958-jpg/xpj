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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun StatsMetricGrid(
    stats: MonthlyStats,
    lifestyle: LifestyleStats?,
    insight: CategoryInsight?,
    budget: BudgetProgress?,
) {
    val aiCategoryAmount = stats.byCategory
        .firstOrNull { it.category == "AI订阅" || it.category == "AI 订阅" }
        ?.amountCents
        ?.takeIf { it > 0L }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = "AI 订阅",
                value = lifestyle?.aiSubscriptionAmountCents?.takeIf { it > 0L }?.let(::formatAmount)
                    ?: aiCategoryAmount?.let(::formatAmount)
                    ?: "暂无记录",
                accent = 0,
            )
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = "最大一笔",
                value = lifestyle?.maxExpense?.amountCents?.let(::formatAmount) ?: "暂无记录",
                caption = lifestyle?.maxExpense?.merchant?.takeIf { it.isNotBlank() },
                accent = 1,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = "常去商家",
                value = lifestyle?.frequentMerchants?.firstOrNull()?.merchant ?: "暂无记录",
                caption = lifestyle?.frequentMerchants?.firstOrNull()?.let { "${it.count} 笔" },
                accent = 2,
            )
            StatsMetricCard(
                modifier = Modifier.weight(1f),
                label = "分类集中度",
                value = insight?.topCategory ?: "${stats.byCategory.count { it.amountCents > 0L }} 个分类",
                caption = insight?.let { "占本月 ${it.topSharePercent}%" },
                accent = 3,
            )
        }
        budget?.let { BudgetProgressCard(it) }
    }
}

@Composable
private fun BudgetProgressCard(budget: BudgetProgress) {
    val visuals = LocalThemeVisuals.current
    val progress = budget.progress.coerceIn(0f, 1f)
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                    Text("月度预算", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(
                        text = if (budget.overBudget) "已超过预算" else "还可花 ${formatAmount(budget.remainingCents)}",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Black,
                    )
                }
                Text(
                    text = "${(progress * 100).toInt()}%",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = FontWeight.Bold,
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.10f)),
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(progress)
                        .height(7.dp)
                        .clip(RoundedCornerShape(AppRadius.pill))
                        .background(if (budget.overBudget) visuals.warningTint else visuals.primary),
                )
            }
            Text(
                text = "可在设置 > 数据与导出里调整，只用于提醒。",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun StatsMetricCard(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    caption: String? = null,
    accent: Int = 0,
) {
    val visuals = LocalThemeVisuals.current
    val isEmptyValue = value == "暂无记录"
    val accentColors = listOf(
        visuals.chipSelected,
        visuals.warningTint.copy(alpha = 0.28f),
        visuals.glassTint.copy(alpha = 0.88f),
        visuals.shadowTint.copy(alpha = 0.12f),
    )
    AppGlassCard(modifier = modifier, containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(22.dp)
                        .clip(RoundedCornerShape(AppRadius.extraSmall))
                        .background(accentColors[accent % accentColors.size]),
                    contentAlignment = Alignment.Center,
                ) {
                    Box(
                        modifier = Modifier
                            .size(5.dp)
                            .clip(RoundedCornerShape(AppRadius.pill))
                            .background(visuals.primary),
                    )
                }
                Text(
                    text = label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                )
            }
            Text(
                text = value,
                color = if (isEmptyValue) {
                    MaterialTheme.colorScheme.onSurfaceVariant
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
                style = if (isEmptyValue) {
                    MaterialTheme.typography.titleSmall
                } else {
                    MaterialTheme.typography.titleMedium
                },
                fontWeight = FontWeight.Black,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            caption?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}
