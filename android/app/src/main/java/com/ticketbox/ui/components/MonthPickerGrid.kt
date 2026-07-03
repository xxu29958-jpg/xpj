package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun MonthGridRow(
    months: List<String>,
    selectedMonth: String,
    onSelectMonth: (String) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        months.forEach { month ->
            MonthGridCell(
                modifier = Modifier.weight(1f),
                label = displayMonthCellLabel(month),
                selected = selectedMonth == month,
                onClick = { onSelectMonth(month) },
            )
        }
        repeat(MonthGridColumns - months.size) {
            Spacer(modifier = Modifier.weight(1f))
        }
    }
}

@Composable
private fun MonthGridCell(
    label: String,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val shape = RoundedCornerShape(AppRadius.extraSmall)
    Box(
        modifier = modifier
            .heightIn(min = AppSpacing.controlMinHeight)
            .clip(shape)
            .background(if (selected) visuals.chipSelected.copy(alpha = AppAlpha.soft) else Color.Transparent)
            .clickable(onClick = onClick)
            .semantics { this.selected = selected }
            .padding(horizontal = AppSpacing.miniGap, vertical = AppSpacing.smallGap),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) AppTextHierarchy.heading.weight else FontWeight.Medium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

internal const val MonthGridColumns = 4
