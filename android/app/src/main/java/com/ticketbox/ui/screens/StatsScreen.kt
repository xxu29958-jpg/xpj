package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.BudgetProgress
import com.ticketbox.domain.model.CategoryInsight
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.AppEmptyStateCard
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.DeepHeroPanel
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.MonthSelectorButton
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.StatsUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen(
    state: StatsUiState,
    onMonthChange: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.month,
                description = "选择后刷新统计。本页按消费时间统计，没有消费时间时按确认时间。",
                onSelectMonth = { month ->
                    onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                AppPageHeader(
                    title = "统计",
                    subtitle = "不是财务报表，是生活消费感知",
                ) {
                    SafeBadge()
                }
                MonthSelectorButton(
                    selectedMonth = state.month,
                    label = "统计月份",
                    onClick = { showMonthPicker = true },
                )
            }
        }
        state.message?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        val stats = state.stats
        if (stats == null) {
            item { EmptyStatsCard(onRefresh = onRefresh) }
        } else {
            item {
                StatsOverviewCard(
                    stats = stats,
                    recent7DaysAmountCents = state.lifestyleStats?.recent7DaysAmountCents
                        ?: state.dailyTrend.sumOf { it.amountCents },
                    comparison = state.monthComparison,
                    budget = state.budgetProgress,
                )
            }
            item {
                RecentTrendCard(state.dailyTrend)
            }
            state.categoryInsight?.let { insight ->
                item {
                    CategoryInsightCard(insight)
                }
            }
            state.lifestyleStats?.let { lifestyle ->
                item {
                    LifestyleCard(lifestyle)
                }
                if (lifestyle.frequentMerchants.isNotEmpty()) {
                    item {
                        FrequentMerchantsCard(lifestyle.frequentMerchants)
                    }
                }
            }
            val visibleCategories = stats.byCategory.filter { it.amountCents > 0L && it.count > 0 }
            if (visibleCategories.isEmpty()) {
                item {
                    EmptyStatsCard(
                        title = "${displayMonthLabel(stats.month)} 暂无分类支出",
                        body = "确认几笔账单后，这里会显示分类占比。",
                    )
                }
            } else {
                item {
                    Text("分类占比", style = MaterialTheme.typography.titleMedium)
                }
                items(visibleCategories, key = { it.category }) { category ->
                    CategoryShareRow(
                        category = category,
                        totalAmountCents = stats.totalAmountCents,
                    )
                }
            }
        }
    }
}

@Composable
private fun CategoryInsightCard(insight: CategoryInsight) {
    val concentration = if (insight.isConcentrated) "支出比较集中" else "支出比较分散"
    AppGlassCard(containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "分类洞察",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                fontWeight = FontWeight.Black,
            )
            Text(
                text = "主要花在「${insight.topCategory}」，占本月 ${insight.topSharePercent}%。",
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricPill(
                    modifier = Modifier.weight(1f),
                    label = concentration,
                    value = formatAmount(insight.topAmountCents),
                )
                MetricPill(
                    modifier = Modifier.weight(1f),
                    label = "${insight.categoryCount} 个分类",
                    value = "均笔 ${formatAmount(insight.averagePerExpenseCents)}",
                )
            }
        }
    }
}

@Composable
private fun RecentTrendCard(trend: List<DailySpend>) {
    val maxAmount = trend.maxOfOrNull { it.amountCents } ?: 0L

    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("最近 7 天趋势", style = MaterialTheme.typography.titleMedium)
                Text(
                    text = "本地账本",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (trend.isEmpty() || maxAmount == 0L) {
                Text(
                    text = "手机里暂无最近支出，同步后会显示每日变化。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(92.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
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

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            contentAlignment = androidx.compose.ui.Alignment.BottomCenter,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(barHeight)
                    .clip(RoundedCornerShape(999.dp))
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

@Composable
private fun StatsOverviewCard(
    stats: MonthlyStats,
    recent7DaysAmountCents: Long,
    comparison: MonthComparison?,
    budget: BudgetProgress?,
) {
    DeepHeroPanel {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(
                text = "本月支出",
                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.82f),
                style = MaterialTheme.typography.labelLarge,
            )
            Text(
                text = formatAmount(stats.totalAmountCents),
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onPrimary,
            )
            Text(
                text = "${stats.count} 笔 · 最近 7 天 ${formatAmount(recent7DaysAmountCents)}",
                color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.80f),
                style = MaterialTheme.typography.bodyMedium,
            )
            HeroTrendLine()
            statsHeroContextLine(comparison = comparison, budget = budget)?.let { contextLine ->
                Text(
                    text = contextLine,
                    color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.76f),
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun HeroTrendLine() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        listOf(0.30f, 0.42f, 0.35f, 0.68f, 0.50f, 0.46f, 0.78f, 0.58f, 0.48f, 0.64f).forEachIndexed { index, weight ->
            Box(
                modifier = Modifier
                    .weight(weight)
                    .height(if (index == 6) 10.dp else 7.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(MaterialTheme.colorScheme.onPrimary.copy(alpha = if (index == 6) 0.95f else 0.46f)),
            )
        }
    }
}

private fun monthComparisonText(comparison: MonthComparison): String {
    if (comparison.previousAmountCents == 0L) {
        return if (comparison.currentAmountCents == 0L) {
            "本月和上月暂无本地账单"
        } else {
            "上月暂无记录 · 本月 ${formatAmount(comparison.currentAmountCents)}"
        }
    }
    val delta = comparison.deltaAmountCents
    if (delta == 0L) return "和上月持平"
    val direction = if (delta > 0L) "多花" else "少花"
    val percent = comparison.percentChange
        ?.let { value -> " · ${if (value > 0) "+" else ""}$value%" }
        .orEmpty()
    return "比上月$direction ${formatAmount(kotlin.math.abs(delta))}$percent"
}

private fun statsHeroContextLine(
    comparison: MonthComparison?,
    budget: BudgetProgress?,
): String? {
    val parts = buildList {
        comparison?.let { add(monthComparisonText(it)) }
        budget?.let {
            val remaining = if (it.overBudget) {
                "预算超 ${formatAmount(kotlin.math.abs(it.remainingCents))}"
            } else {
                "预算余 ${formatAmount(it.remainingCents)}"
            }
            add("$remaining · ${it.percent}%")
        }
    }
    return parts.joinToString(" · ").takeIf { it.isNotBlank() }
}

@Composable
private fun MetricPill(
    modifier: Modifier = Modifier,
    label: String,
    value: String,
) {
    val visuals = LocalThemeVisuals.current
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(visuals.chipSelected.copy(alpha = 0.58f))
            .padding(horizontal = 11.dp, vertical = 7.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.86f),
            style = MaterialTheme.typography.labelSmall,
        )
        Text(
            text = value,
            color = visuals.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun LifestyleCard(lifestyle: LifestyleStats) {
    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("生活统计", style = MaterialTheme.typography.titleMedium)
            if (lifestyle.aiSubscriptionAmountCents > 0L) {
                LifestyleRow("AI 订阅", formatAmount(lifestyle.aiSubscriptionAmountCents))
            }
            if (lifestyle.digitalAmountCents > 0L) {
                LifestyleRow("数码消费", formatAmount(lifestyle.digitalAmountCents))
            }
            lifestyle.maxExpense?.let { maxExpense ->
                LifestyleRow(
                    label = "最大一笔",
                    value = "${formatAmount(maxExpense.amountCents)} · ${
                        maxExpense.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家"
                    }",
                )
            }
            if (
                lifestyle.aiSubscriptionAmountCents == 0L &&
                lifestyle.digitalAmountCents == 0L &&
                lifestyle.maxExpense == null
            ) {
                Text(
                    text = "暂无特别统计项。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun LifestyleRow(
    label: String,
    value: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value)
    }
}

@Composable
private fun FrequentMerchantsCard(merchants: List<FrequentMerchant>) {
    val visuals = LocalThemeVisuals.current
    AppGlassCard(containerAlpha = 0.92f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("高频商家", style = MaterialTheme.typography.titleMedium)
            merchants.take(5).forEachIndexed { index, merchant ->
                if (index > 0) {
                    HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = merchant.merchant,
                        style = MaterialTheme.typography.bodyLarge,
                    )
                    Text(
                        text = "${merchant.count} 笔",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun CategoryShareRow(
    category: CategoryStats,
    totalAmountCents: Long,
) {
    val visuals = LocalThemeVisuals.current
    val progress = if (totalAmountCents > 0) {
        (category.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(visuals.solidCard.copy(alpha = 0.86f))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(category.category, style = MaterialTheme.typography.titleSmall)
                Text(
                    text = "${category.count} 笔",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Text(
                text = formatAmount(category.amountCents),
                color = MaterialTheme.colorScheme.primary,
                style = MaterialTheme.typography.titleMedium,
            )
        }
        LinearProgressIndicator(
            progress = { progress },
            modifier = Modifier
                .fillMaxWidth()
                .height(8.dp)
                .clip(RoundedCornerShape(999.dp)),
            color = visuals.primary,
            trackColor = visuals.chipUnselected.copy(alpha = 0.72f),
        )
    }
}

@Composable
private fun EmptyStatsCard(
    title: String = "还没有统计数据",
    body: String = "确认账单后刷新统计，这里会显示本月总支出、分类占比和高频商家。",
    onRefresh: (() -> Unit)? = null,
) {
    AppEmptyStateCard {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
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
            .clip(RoundedCornerShape(20.dp))
            .background(visuals.chipUnselected.copy(alpha = 0.48f))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
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
    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Text(
            text = title,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.62f),
            style = MaterialTheme.typography.labelMedium,
        )
        Box(
            modifier = Modifier
                .fillMaxWidth(widthFraction)
                .height(10.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.12f)),
        )
    }
}
