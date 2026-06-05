package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
fun MonthPickerSheet(
    months: List<String>,
    selectedMonth: String,
    description: String,
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
            text = description,
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
                        text = "更新后会显示可选月份。",
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
    val selectedBackground = if (selected) {
        MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)
    } else {
        Color.Transparent
    }
    AppSolidCard(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(selectedBackground)
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

fun displayMonthLabel(month: String): String {
    val parts = month.split("-")
    if (parts.size != 2) return month
    val year = parts[0]
    val monthNumber = parts[1].trimStart('0').ifBlank { parts[1] }
    return "${year}年${monthNumber}月"
}
