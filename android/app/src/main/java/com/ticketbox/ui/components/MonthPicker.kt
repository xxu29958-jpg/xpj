package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
fun MonthPickerSheet(
    months: List<String>,
    selectedMonth: String,
    description: String,
    onSelectMonth: (String) -> Unit,
) {
    val selectedLabel = if (selectedMonth.isBlank()) {
        stringResource(R.string.components_month_picker_all_months)
    } else {
        displayMonthLabel(selectedMonth)
    }
    Column(
        modifier = Modifier.fillMaxWidth(),
    ) {
        AppSheetScaffold(
            title = stringResource(R.string.components_month_picker_title),
            subtitle = description,
        ) {
            MonthPickerSelectionSummary(selectedLabel = selectedLabel)
            MonthPickerOptions(
                months = months,
                selectedMonth = selectedMonth,
                onSelectMonth = onSelectMonth,
            )
        }
    }
}

@Composable
private fun MonthPickerSelectionSummary(selectedLabel: String) {
    AppListRow {
        Text(
            text = stringResource(R.string.components_month_picker_current_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Spacer(modifier = Modifier.weight(1f))
        Text(
            text = selectedLabel,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun MonthPickerOptions(
    months: List<String>,
    selectedMonth: String,
    onSelectMonth: (String) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        MonthOptionRow(
            label = stringResource(R.string.components_month_picker_all_months),
            selected = selectedMonth.isBlank(),
            onClick = { onSelectMonth("") },
        )
        if (months.isEmpty()) {
            MonthPickerEmptyRow()
        }
        val pendingRow = mutableListOf<String>()
        monthPickerEntries(months).forEach { entry ->
            when (entry) {
                is MonthPickerEntry.YearHeader -> {
                    if (pendingRow.isNotEmpty()) {
                        MonthGridRow(
                            months = pendingRow.toList(),
                            selectedMonth = selectedMonth,
                            onSelectMonth = onSelectMonth,
                        )
                        pendingRow.clear()
                    }
                    MonthPickerYearHeader(entry.year)
                }
                is MonthPickerEntry.Month -> {
                    pendingRow += entry.month
                    if (pendingRow.size == MonthGridColumns) {
                        MonthGridRow(
                            months = pendingRow.toList(),
                            selectedMonth = selectedMonth,
                            onSelectMonth = onSelectMonth,
                        )
                        pendingRow.clear()
                    }
                }
            }
        }
        if (pendingRow.isNotEmpty()) {
            MonthGridRow(
                months = pendingRow.toList(),
                selectedMonth = selectedMonth,
                onSelectMonth = onSelectMonth,
            )
        }
    }
}

@Composable
private fun MonthOptionRow(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
) {
    AppListRow(
        modifier = Modifier
            .semantics { this.selected = selected },
        onClick = onClick,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyLarge,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            fontWeight = if (selected) AppTextHierarchy.heading.weight else FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(modifier = Modifier.weight(1f))
        if (selected) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(AssistChipDefaults.IconSize),
            )
        }
    }
}

@Composable
private fun MonthPickerYearHeader(year: String) {
    Text(
        text = stringResource(R.string.components_month_picker_year_header, year),
        modifier = Modifier.padding(
            start = AppSpacing.cardPaddingTight,
            top = AppSpacing.compactGap,
            bottom = AppSpacing.miniGap,
        ),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = AppTextHierarchy.heading.weight,
    )
}

@Composable
private fun MonthPickerEmptyRow() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactGap),
    ) {
        Text(
            text = stringResource(R.string.components_month_picker_empty),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
fun displayMonthLabel(month: String): String {
    val parts = monthLabelParts(month) ?: return month
    return stringResource(R.string.components_month_label, parts.year, parts.monthNumber)
}

@Composable
internal fun displayMonthCellLabel(month: String): String {
    val parts = monthLabelParts(month) ?: return displayMonthLabel(month)
    return stringResource(R.string.components_month_picker_month_cell, parts.monthNumber)
}

internal fun monthLabelParts(month: String): MonthLabelParts? {
    val parts = month.split("-")
    if (parts.size != 2) return null
    val year = parts[0]
    val monthNumber = parts[1].trimStart('0').ifBlank { parts[1] }
    return MonthLabelParts(year = year, monthNumber = monthNumber)
}

internal data class MonthLabelParts(
    val year: String,
    val monthNumber: String,
)

internal sealed interface MonthPickerEntry {
    val key: String

    data class YearHeader(val year: String, val sequence: Int) : MonthPickerEntry {
        override val key: String = "year-$sequence-$year"
    }

    data class Month(val month: String) : MonthPickerEntry {
        override val key: String = "month-$month"
    }
}

internal fun monthPickerEntries(months: List<String>): List<MonthPickerEntry> {
    val entries = mutableListOf<MonthPickerEntry>()
    var currentYear: String? = null
    var headerSequence = 0
    months.distinct().forEach { month ->
        val year = monthPickerYear(month)
        if (year != null && year != currentYear) {
            entries += MonthPickerEntry.YearHeader(year, headerSequence)
            headerSequence += 1
            currentYear = year
        } else if (year == null) {
            currentYear = null
        }
        entries += MonthPickerEntry.Month(month)
    }
    return entries
}

private fun monthPickerYear(month: String): String? {
    val parts = month.split("-")
    val year = parts.firstOrNull().orEmpty()
    if (parts.size != 2 || year.length != 4 || year.any { !it.isDigit() }) return null
    return year
}
