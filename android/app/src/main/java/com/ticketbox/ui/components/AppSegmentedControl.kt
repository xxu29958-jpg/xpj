package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.ticketbox.ui.design.AppSpacing

data class AppSegmentedItem<T : Any>(
    val value: T,
    val label: String,
    val enabled: Boolean = true,
)

@Composable
fun <T : Any> AppSegmentedControl(
    options: List<AppSegmentedItem<T>>,
    selectedValue: T,
    onValueChange: (T) -> Unit,
    modifier: Modifier = Modifier,
) {
    FlowRow(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        options.forEach { option ->
            AppFilterChip(
                selected = selectedValue == option.value,
                onClick = { onValueChange(option.value) },
                label = option.label,
                options = AppFilterChipOptions(enabled = option.enabled),
            )
        }
    }
}
