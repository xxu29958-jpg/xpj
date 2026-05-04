package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.viewmodel.StatsUiState

@Composable
fun StatsScreen(
    state: StatsUiState,
    onMonthChange: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = state.month,
                    onValueChange = onMonthChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("统计月份") },
                    placeholder = { Text("2026-05") },
                    singleLine = true,
                )
                if (state.months.isNotEmpty()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(state.months, key = { it }) { month ->
                            AssistChip(
                                onClick = { onMonthChange(month) },
                                label = { Text(month) },
                            )
                        }
                    }
                }
                Button(onClick = onRefresh) {
                    Text(if (state.loading) "刷新中" else "刷新统计")
                }
            }
        }
        state.message?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        state.stats?.let { value ->
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("${value.month} 总支出", style = MaterialTheme.typography.titleMedium)
                        Text(formatAmount(value.totalAmountCents), style = MaterialTheme.typography.headlineMedium)
                        Text("账单 ${value.count} 笔", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            state.lifestyleStats?.let { lifestyle ->
                item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("生活统计", style = MaterialTheme.typography.titleMedium)
                            Text("AI 订阅：${formatAmount(lifestyle.aiSubscriptionAmountCents)}")
                            Text("数码消费：${formatAmount(lifestyle.digitalAmountCents)}")
                            Text("最近 7 天：${formatAmount(lifestyle.recent7DaysAmountCents)}")
                            lifestyle.maxExpense?.let { maxExpense ->
                                Text(
                                    "最大一笔：${formatAmount(maxExpense.amountCents)} · ${
                                        maxExpense.merchant?.takeIf { it.isNotBlank() } ?: "未填写商家"
                                    }",
                                )
                            }
                        }
                    }
                }
                if (lifestyle.frequentMerchants.isNotEmpty()) {
                    item {
                        Card(modifier = Modifier.fillMaxWidth()) {
                            Column(
                                modifier = Modifier.padding(16.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Text("高频商家", style = MaterialTheme.typography.titleMedium)
                                lifestyle.frequentMerchants.forEach { merchant ->
                                    Text("${merchant.merchant} · ${merchant.count} 笔")
                                }
                            }
                        }
                    }
                }
            }
            items(value.byCategory, key = { it.category }) { category ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(category.category, style = MaterialTheme.typography.titleMedium)
                        Text("${formatAmount(category.amountCents)} · ${category.count} 笔")
                    }
                }
            }
        }
    }
}
