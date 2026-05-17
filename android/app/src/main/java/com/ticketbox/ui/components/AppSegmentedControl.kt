package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
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
    LazyRow(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap),
    ) {
        items(options, key = { it.value }) { option ->
            AppFilterChip(
                selected = selectedValue == option.value,
                enabled = option.enabled,
                onClick = { onValueChange(option.value) },
                label = option.label,
            )
        }
    }
}
