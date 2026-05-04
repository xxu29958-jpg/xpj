package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CategoryStats
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.FrequentMerchant
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.MonthComparison
import com.ticketbox.domain.model.MonthlyStats
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.MonthSelectorButton
import com.ticketbox.ui.components.RefreshableLazyColumn
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatAmount
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

    RefreshableLazyColumn(
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("统计", style = MaterialTheme.typography.headlineSmall)
                MonthSelectorButton(
                    selectedMonth = state.month,
                    label = "统计月份",
                    onClick = { showMonthPicker = true },
                )
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onRefresh,
                ) {
                    Text(if (state.loading) "刷新中" else "刷新统计")
                }
            }
        }
        state.message?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        val stats = state.stats
        if (stats == null) {
            item { EmptyStatsCard() }
        } else {
            item {
                StatsOverviewCard(
                    stats = stats,
                    lifestyle = state.lifestyleStats,
                    comparison = state.monthComparison,
                )
            }
            item {
                RecentTrendCard(state.dailyTrend)
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
            if (stats.byCategory.isEmpty()) {
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
                items(stats.byCategory, key = { it.category }) { category ->
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
private fun RecentTrendCard(trend: List<DailySpend>) {
    val maxAmount = trend.maxOfOrNull { it.amountCents } ?: 0L

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.70f),
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
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
                    text = "本地缓存暂无最近支出，同步后会显示每日变化。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(132.dp),
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
    val progress = if (maxAmount > 0) {
        (day.amountCents.toFloat() / maxAmount.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val barHeight = if (day.amountCents > 0L) {
        (16 + 76 * progress).dp
    } else {
        8.dp
    }
    val barColor = if (day.amountCents > 0L) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.62f)
    }

    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(92.dp),
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
    lifestyle: LifestyleStats?,
    comparison: MonthComparison?,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.76f),
        ),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = displayMonthLabel(stats.month),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge,
            )
            Text(
                text = formatAmount(stats.totalAmountCents),
                style = MaterialTheme.typography.displaySmall,
                color = MaterialTheme.colorScheme.primary,
            )
            comparison?.let {
                MonthComparisonPill(it)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MetricPill(
                    modifier = Modifier.weight(1f),
                    label = "账单",
                    value = "${stats.count} 笔",
                )
                MetricPill(
                    modifier = Modifier.weight(1f),
                    label = "最近 7 天",
                    value = formatAmount(lifestyle?.recent7DaysAmountCents ?: 0L),
                )
            }
        }
    }
}

@Composable
private fun MonthComparisonPill(comparison: MonthComparison) {
    val text = monthComparisonText(comparison)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.48f))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(
            text = "月环比",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(text, style = MaterialTheme.typography.bodyMedium)
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

@Composable
private fun MetricPill(
    modifier: Modifier = Modifier,
    label: String,
    value: String,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.42f))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(value, style = MaterialTheme.typography.titleSmall)
    }
}

@Composable
private fun LifestyleCard(lifestyle: LifestyleStats) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.70f),
        ),
    ) {
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
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.70f),
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("高频商家", style = MaterialTheme.typography.titleMedium)
            merchants.take(5).forEachIndexed { index, merchant ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.72f))
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
    val progress = if (totalAmountCents > 0) {
        (category.amountCents.toFloat() / totalAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.68f))
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
            color = MaterialTheme.colorScheme.primary,
            trackColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.58f),
        )
    }
}

@Composable
private fun EmptyStatsCard(
    title: String = "还没有统计数据",
    body: String = "确认账单后刷新统计，这里会显示本月总支出、分类占比和高频商家。",
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.72f),
        ),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                text = body,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
