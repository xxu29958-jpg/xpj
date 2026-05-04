package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.viewmodel.LedgerUiState

@Composable
fun LedgerScreen(
    state: LedgerUiState,
    onMonthChange: (String) -> Unit,
    onCategoryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
) {
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = state.monthFilter,
                    onValueChange = onMonthChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("月份") },
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
                OutlinedTextField(
                    value = state.categoryFilter,
                    onValueChange = onCategoryChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("分类") },
                    placeholder = { Text("留空显示全部") },
                    singleLine = true,
                )
                if (state.categories.isNotEmpty()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(state.categories, key = { it }) { category ->
                            AssistChip(
                                onClick = { onCategoryChange(category) },
                                label = { Text(category) },
                            )
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onSync) {
                        Text(if (state.syncing) "同步中" else "同步账本")
                    }
                    OutlinedButton(onClick = onExportCsv) {
                        Text(if (state.exporting) "导出中" else "导出")
                    }
                    OutlinedButton(onClick = onClearFilters) {
                        Text("全部")
                    }
                }
            }
        }
        state.message?.let {
            item {
                Text(it, color = MaterialTheme.colorScheme.secondary)
            }
        }
        if (state.items.isEmpty()) {
            item {
                Text("本地还没有已确认账单", modifier = Modifier.padding(vertical = 8.dp))
            }
        }
        items(state.items, key = { it.id }) { expense ->
            ExpenseCard(expense = expense, showActions = false)
        }
    }
}
