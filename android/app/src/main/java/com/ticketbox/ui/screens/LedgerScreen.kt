package com.ticketbox.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.viewmodel.LedgerUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerScreen(
    state: LedgerUiState,
    onMonthChange: (String) -> Unit,
    onCategoryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    val canExport = state.items.isNotEmpty() && !state.exporting

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.monthFilter,
                onSelectMonth = { month ->
                    onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            LedgerFilterPanel(
                state = state,
                canExport = canExport,
                onOpenMonthPicker = { showMonthPicker = true },
                onCategoryChange = onCategoryChange,
                onClearFilters = onClearFilters,
                onSync = onSync,
                onExportCsv = onExportCsv,
            )
        }
        state.message?.let {
            item {
                Text(it, color = MaterialTheme.colorScheme.secondary)
            }
        }
        if (state.items.isEmpty()) {
            item {
                EmptyLedgerState(state)
            }
        }
        items(state.items, key = { it.id }) { expense ->
            ExpenseCard(expense = expense, showActions = false)
        }
    }
}

@Composable
private fun LedgerFilterPanel(
    state: LedgerUiState,
    canExport: Boolean,
    onOpenMonthPicker: () -> Unit,
    onCategoryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("账本", style = MaterialTheme.typography.headlineSmall)
        MonthSelectorButton(
            selectedMonth = state.monthFilter,
            onClick = onOpenMonthPicker,
        )
        CategoryFilterRow(
            categories = state.categories,
            selectedCategory = state.categoryFilter,
            onCategoryChange = onCategoryChange,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                modifier = Modifier.weight(1f),
                onClick = onSync,
            ) {
                Text(if (state.syncing) "同步中" else "同步账本")
            }
            OutlinedButton(
                modifier = Modifier.weight(1f),
                enabled = canExport,
                onClick = onExportCsv,
            ) {
                Text(if (state.exporting) "导出中" else "导出账单")
            }
            OutlinedButton(onClick = onClearFilters) {
                Text("清筛选")
            }
        }
        if (state.items.isEmpty()) {
            Text(
                text = "当前没有可导出的已确认账单。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun MonthSelectorButton(
    selectedMonth: String,
    onClick: () -> Unit,
) {
    OutlinedButton(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = "月份",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                )
                Text(
                    text = selectedMonth.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份",
                    style = MaterialTheme.typography.titleSmall,
                )
            }
            Icon(
                imageVector = Icons.Filled.ExpandMore,
                contentDescription = "选择月份",
            )
        }
    }
}

@Composable
private fun CategoryFilterRow(
    categories: List<String>,
    selectedCategory: String,
    onCategoryChange: (String) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = "分类",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                SelectableFilterChip(
                    selected = selectedCategory.isBlank(),
                    label = "全部分类",
                    onClick = { onCategoryChange("") },
                )
            }
            items(categories, key = { it }) { category ->
                SelectableFilterChip(
                    selected = selectedCategory == category,
                    label = category,
                    onClick = { onCategoryChange(category) },
                )
            }
        }
    }
}

@Composable
private fun SelectableFilterChip(
    selected: Boolean,
    label: String,
    onClick: () -> Unit,
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label) },
        leadingIcon = if (selected) {
            {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    modifier = Modifier.size(FilterChipDefaults.IconSize),
                )
            }
        } else {
            null
        },
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.22f),
            selectedLabelColor = MaterialTheme.colorScheme.onSurface,
        ),
    )
}

@Composable
private fun MonthPickerSheet(
    months: List<String>,
    selectedMonth: String,
    onSelectMonth: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("选择月份", style = MaterialTheme.typography.titleLarge)
        Text(
            text = "选择后会刷新账本。历史月份多了以后可以上下滑动。",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        LazyColumn(
            modifier = Modifier.heightIn(max = 430.dp),
            contentPadding = PaddingValues(bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item {
                MonthOptionRow(
                    label = "全部月份",
                    selected = selectedMonth.isBlank(),
                    onClick = { onSelectMonth("") },
                )
            }
            if (months.isEmpty()) {
                item {
                    Text(
                        text = "同步后会显示可选月份。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 8.dp),
                    )
                }
            }
            items(months, key = { it }) { month ->
                MonthOptionRow(
                    label = displayMonthLabel(month),
                    selected = selectedMonth == month,
                    onClick = { onSelectMonth(month) },
                )
            }
        }
    }
}

@Composable
private fun MonthOptionRow(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val border = if (selected) {
        BorderStroke(1.dp, MaterialTheme.colorScheme.primary)
    } else {
        null
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        colors = CardDefaults.cardColors(
            containerColor = if (selected) {
                MaterialTheme.colorScheme.primary.copy(alpha = 0.16f)
            } else {
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.34f)
            },
        ),
        border = border,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label, style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.weight(1f))
            if (selected) {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun EmptyLedgerState(state: LedgerUiState) {
    val hasMonth = state.monthFilter.isNotBlank()
    val hasCategory = state.categoryFilter.isNotBlank()
    val title = when {
        hasMonth && hasCategory -> "${displayMonthLabel(state.monthFilter)} 暂无 ${state.categoryFilter} 分类账单"
        hasMonth -> "${displayMonthLabel(state.monthFilter)} 暂无已确认账单"
        hasCategory -> "暂无 ${state.categoryFilter} 分类账单"
        else -> "本地还没有已确认账单"
    }
    val body = if (hasMonth || hasCategory) {
        "可以切换月份、选择全部分类，或先同步服务器。"
    } else {
        "在待确认页确认几笔账单后，账本会在这里显示。"
    }

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

private fun displayMonthLabel(month: String): String {
    val parts = month.split("-")
    if (parts.size != 2) return month
    val year = parts[0]
    val monthNumber = parts[1].trimStart('0').ifBlank { parts[1] }
    return "${year}年${monthNumber}月"
}
