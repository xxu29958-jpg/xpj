package com.ticketbox.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.theme.LocalThemeVisuals

@Composable
fun AppFilterChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    val visuals = LocalThemeVisuals.current
    FilterChip(
        selected = selected,
        enabled = enabled,
        onClick = onClick,
        label = {
            Text(
                text = label,
                fontWeight = if (selected) FontWeight.Black else FontWeight.Medium,
            )
        },
        modifier = modifier,
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = visuals.chipSelected,
            selectedLabelColor = MaterialTheme.colorScheme.primary,
            containerColor = visuals.chipUnselected.copy(alpha = 0.86f),
            labelColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ),
        border = BorderStroke(
            width = 1.dp,
            color = if (selected) {
                MaterialTheme.colorScheme.primary.copy(alpha = 0.18f)
            } else {
                MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.38f)
            },
        ),
    )
}
