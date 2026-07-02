package com.ticketbox.ui.components

import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

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
            .padding(horizontal = AppSpacing.cardPaddingSmall, vertical = AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        Text(stringResource(R.string.components_month_picker_title), style = MaterialTheme.typography.titleLarge)
        Text(
            text = description,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        LazyColumn(
            modifier = Modifier.heightIn(max = AppSpacing.controlMinHeight * 9.25f),
            contentPadding = PaddingValues(bottom = AppSpacing.cardPaddingSmall),
        ) {
            item {
                MonthOptionRow(
                    label = stringResource(R.string.components_month_picker_all_months),
                    selected = selectedMonth.isBlank(),
                    onClick = { onSelectMonth("") },
                )
            }
            if (months.isEmpty()) {
                item {
                    Text(
                        text = stringResource(R.string.components_month_picker_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = AppSpacing.smallGap),
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
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = AppSpacing.controlMinHeight)
                .clickable(onClick = onClick)
                .padding(vertical = AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge,
                color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                fontWeight = if (selected) AppTextHierarchy.heading.weight else FontWeight.Medium,
            )
            Spacer(modifier = Modifier.weight(1f))
            if (selected) {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

fun displayMonthLabel(month: String): String {
    val parts = month.split("-")
    if (parts.size != 2) return month
    val year = parts[0]
    val monthNumber = parts[1].trimStart('0').ifBlank { parts[1] }
    return "${year}年${monthNumber}月"
}
