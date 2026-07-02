package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
fun MonthPickerSheet(
    months: List<String>,
    selectedMonth: String,
    description: String,
    onSelectMonth: (String) -> Unit,
) {
    val selectedLabel = selectedMonth
        .takeIf { it.isNotBlank() }
        ?.let(::displayMonthLabel)
        ?: stringResource(R.string.components_month_picker_all_months)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = AppSpacing.screenHorizontal, vertical = AppSpacing.cardPaddingSmall),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        MonthPickerHeader(description = description)
        MonthPickerSelectionSummary(selectedLabel = selectedLabel)
        MonthPickerOptions(
            months = months,
            selectedMonth = selectedMonth,
            onSelectMonth = onSelectMonth,
        )
    }
}

@Composable
private fun MonthPickerHeader(description: String) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.components_month_picker_title),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = description,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun MonthPickerSelectionSummary(selectedLabel: String) {
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(AppRadius.small))
            .background(visuals.chipSelected.copy(alpha = AppAlpha.soft))
            .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.compactPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.components_month_picker_current_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            text = selectedLabel,
            modifier = Modifier.weight(1f),
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
    LazyColumn(
        modifier = Modifier.heightIn(max = AppSpacing.controlMinHeight * 9.5f),
        contentPadding = PaddingValues(bottom = AppSpacing.bottomContentPadding),
    ) {
        item {
            MonthOptionRow(
                label = stringResource(R.string.components_month_picker_all_months),
                selected = selectedMonth.isBlank(),
                onClick = { onSelectMonth("") },
            )
        }
        if (months.isEmpty()) {
            item { MonthPickerEmptyRow() }
        }
        items(monthPickerEntries(months), key = { it.key }) { entry ->
            when (entry) {
                is MonthPickerEntry.YearHeader -> MonthPickerYearHeader(entry.year)
                is MonthPickerEntry.Month -> MonthOptionRow(
                    label = displayMonthLabel(entry.month),
                    selected = selectedMonth == entry.month,
                    onClick = { onSelectMonth(entry.month) },
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
    val visuals = LocalThemeVisuals.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.extraSmall))
            .background(
                if (selected) visuals.chipSelected.copy(alpha = AppAlpha.heavy) else Color.Transparent,
            )
            .clickable(onClick = onClick)
            .semantics { this.selected = selected }
            .padding(horizontal = AppSpacing.cardPaddingTight, vertical = AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
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
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
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

fun displayMonthLabel(month: String): String {
    val parts = month.split("-")
    if (parts.size != 2) return month
    val year = parts[0]
    val monthNumber = parts[1].trimStart('0').ifBlank { parts[1] }
    return "${year}年${monthNumber}月"
}

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
