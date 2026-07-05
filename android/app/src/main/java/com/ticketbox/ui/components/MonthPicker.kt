package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
    listState: MonthPickerListState = MonthPickerListState.Loaded,
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
                listState = listState,
                onSelectMonth = onSelectMonth,
            )
        }
    }
}

@Composable
private fun MonthPickerOptions(
    months: List<String>,
    selectedMonth: String,
    listState: MonthPickerListState,
    onSelectMonth: (String) -> Unit,
) {
    val entries = monthPickerEntries(months)
    val statusRowKind = monthPickerStatusRowKind(months, listState)
    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = AppSpacing.controlMinHeight * 7),
    ) {
        item(key = "all-months") {
            MonthPickerOptionRow(
                label = stringResource(R.string.components_month_picker_all_months),
                selected = selectedMonth.isBlank(),
                onClick = { onSelectMonth("") },
            )
        }
        statusRowKind?.let { kind ->
            item(key = "month-picker-status-${kind.name}") {
                MonthPickerStatusRow(
                    text = when (kind) {
                        MonthPickerStatusRowKind.Loading -> stringResource(R.string.components_month_picker_loading)
                        MonthPickerStatusRowKind.Failed -> stringResource(R.string.components_month_picker_failed)
                        MonthPickerStatusRowKind.Empty -> stringResource(R.string.components_month_picker_empty)
                    },
                )
            }
        }
        items(
            items = entries,
            key = { entry -> entry.key },
        ) { entry ->
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

enum class MonthPickerListState { Unknown, Loading, Loaded, Failed }

internal enum class MonthPickerStatusRowKind { Loading, Failed, Empty }

internal fun monthPickerStatusRowKind(
    months: List<String>,
    listState: MonthPickerListState,
): MonthPickerStatusRowKind? {
    if (months.isNotEmpty()) return null
    return when (listState) {
        MonthPickerListState.Unknown,
        MonthPickerListState.Loading -> MonthPickerStatusRowKind.Loading
        MonthPickerListState.Failed -> MonthPickerStatusRowKind.Failed
        MonthPickerListState.Loaded -> MonthPickerStatusRowKind.Empty
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
