package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
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
    Column(
        modifier = Modifier.fillMaxWidth(),
    ) {
        AppSheetScaffold(
            title = stringResource(R.string.components_month_picker_title),
            subtitle = description,
        ) {
            MonthPickerOptions(
                months = months,
                selectedMonth = selectedMonth,
                onSelectMonth = onSelectMonth,
            )
        }
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
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        MonthPickerOptionRow(
            label = stringResource(R.string.components_month_picker_all_months),
            selected = selectedMonth.isBlank(),
            onClick = { onSelectMonth("") },
        )
        if (months.isEmpty()) {
            MonthPickerEmptyRow()
        }
        monthPickerEntries(months).forEach { entry ->
            when (entry) {
                is MonthPickerEntry.YearHeader -> MonthPickerYearHeader(entry.year)
                is MonthPickerEntry.Month -> {
                    MonthPickerOptionRow(
                        label = displayMonthLabel(entry.month),
                        selected = selectedMonth == entry.month,
                        onClick = { onSelectMonth(entry.month) },
                    )
                }
            }
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
fun displayMonthLabel(month: String): String {
    val parts = monthLabelParts(month) ?: return month
    return stringResource(R.string.components_month_label, parts.year, parts.monthNumber)
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
